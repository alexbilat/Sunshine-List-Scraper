"""Offline checks for the HTTP API: routes, validation, JSON shapes, and errors.

TestClient sends real HTTP requests to the app in memory; no server or
PostgreSQL is needed. Data routes use a fake SalaryReader. Connection tests
patch psycopg.connect so the real dependency and error handling still run.
"""
from contextlib import nullcontext
import os
import unittest
from unittest.mock import MagicMock, call, patch

from fastapi.testclient import TestClient
import psycopg

import config
from sunshine_scraper.api.app import app, get_open_reader
from sunshine_scraper.storage.connection import DatabaseAccessError

from fakes import FakeSalaryReader

SECRET_URL = 'postgresql://sunshine:hunter2@db.internal/sunshine'


class DataRouteTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeSalaryReader()
        # Routes call open_reader(); the fake one yields the in-memory reader.
        app.dependency_overrides[get_open_reader] = lambda: self.open_fake_reader
        self.addCleanup(app.dependency_overrides.clear)
        # The rate limiter is shared app state; start each test with a full budget.
        app.state.rate_limiter.reset()
        self.client = TestClient(app)

    def open_fake_reader(self):
        return nullcontext(self.reader)

    def test_years_send_exact_cents_and_display_strings(self):
        response = self.client.get('/api/years')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [
            {'year': 2023, 'people': 0, 'average_salary_cents': None, 'average_salary': None},
            # 11172839.5 cents rounds half-up to 11172840.
            {'year': 2024, 'people': 2, 'average_salary_cents': 11172840,
             'average_salary': '111728.40'},
        ])

    def test_top_titles_default_and_custom_limit(self):
        response = self.client.get('/api/titles/top')
        self.assertEqual(response.json(), [{'job_title': 'Professor', 'appearances': 3},
                                           {'job_title': 'Nurse', 'appearances': 2}])
        self.client.get('/api/titles/top', params={'limit': 25})
        self.assertEqual(self.reader.calls, [('top_job_titles', 10), ('top_job_titles', 25)])

    def test_top_salaries_for_a_year(self):
        response = self.client.get('/api/salaries/top', params={'year': 2024, 'limit': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()[0], {
            'name': 'Alex Example', 'first_name': 'Alex', 'last_name': 'Example',
            'employer': 'Example Hospital', 'salary_cents': 12345678, 'salary': '123456.78'})
        self.assertEqual(self.reader.calls, [('get_top_salaries', 2024, 2)])

    def test_invalid_input_is_rejected_before_reaching_the_reader(self):
        for path, params in [('/api/salaries/top', {}),                       # year missing
                             ('/api/salaries/top', {'year': 'latest'}),       # not an integer
                             ('/api/salaries/top', {'year': 10000}),
                             ('/api/salaries/top', {'year': 2024, 'limit': 0}),
                             ('/api/titles/top', {'limit': 101})]:
            with self.subTest(path=path, params=params):
                response = self.client.get(path, params=params)
                self.assertEqual(response.status_code, 422)
        self.assertEqual(self.reader.calls, [])

    def test_only_reads_are_allowed(self):
        response = self.client.post('/api/years')
        self.assertEqual(response.status_code, 405)  # Method Not Allowed

    def test_reader_database_error_becomes_503(self):
        self.reader.yearly_summary = MagicMock(side_effect=DatabaseAccessError('down'))
        with self.assertLogs('sunshine_scraper.api.app', level='ERROR'):
            response = self.client.get('/api/years')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Database unavailable'})


class ConnectionTests(unittest.TestCase):
    """Run the real read_only_connection code against a patched driver."""

    def setUp(self):
        app.state.rate_limiter.reset()
        self.client = TestClient(app)
        patcher = patch.dict(os.environ, {'SUNSHINE_DATABASE_URL': SECRET_URL})
        patcher.start()
        self.addCleanup(patcher.stop)

    def patched_connection(self, execute_side_effect=None):
        connection = MagicMock()
        connection.execute.side_effect = execute_side_effect
        connect = patch('psycopg.connect')
        mock_connect = connect.start()
        self.addCleanup(connect.stop)
        mock_connect.return_value.__enter__.return_value = connection
        return connection

    def assert_unavailable_without_secrets(self, path):
        with self.assertLogs('sunshine_scraper.api.app', level='ERROR') as logs:
            response = self.client.get(path)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Database unavailable'})
        for text in [response.text, *logs.output]:
            self.assertNotIn('hunter2', text)

    def test_health_marks_the_transaction_read_only_before_querying(self):
        connection = self.patched_connection()
        response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok'})
        # Read-only first, then the per-transaction query time cap (passed as
        # a parameter, not pasted into the SQL), then the actual query.
        self.assertEqual(connection.execute.call_args_list, [
            call('SET TRANSACTION READ ONLY'),
            call("SELECT set_config('statement_timeout', %s, true)",
                 (f'{config.api_statement_timeout_ms}ms',)),
            call('SELECT 1')])

    def test_missing_database_url_is_503(self):
        with patch.dict(os.environ, clear=True):
            self.assert_unavailable_without_secrets('/api/health')

    def test_unreachable_server_is_503_without_secrets(self):
        connect = patch('psycopg.connect',
                        side_effect=psycopg.OperationalError(f'cannot reach {SECRET_URL}'))
        connect.start()
        self.addCleanup(connect.stop)
        self.assert_unavailable_without_secrets('/api/health')

    def test_invalid_input_never_opens_a_connection(self):
        # Regression: validation must run before any database work, so a bad
        # request is a 422 (the caller's fault) even while the database is down.
        with patch('psycopg.connect') as connect:
            response = self.client.get('/api/salaries/top', params={'year': 2024, 'limit': 500})
        self.assertEqual(response.status_code, 422)
        connect.assert_not_called()

    def test_query_failure_inside_a_route_is_503_without_secrets(self):
        # The connection opens, then the query itself fails. open_connection
        # must still translate the driver error into DatabaseAccessError.
        self.patched_connection(execute_side_effect=[
            None, None, psycopg.errors.UndefinedTable(f'no table at {SECRET_URL}')])
        self.assert_unavailable_without_secrets('/api/years')


if __name__ == '__main__':
    unittest.main()
