"""Offline checks for money, identity, dependency boundaries, and read behavior.

No PostgreSQL server, source downloads, or installed Psycopg are required.
"""
from dataclasses import replace
from decimal import Decimal
import os
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from sunshine_scraper.processing import clean_record
from sunshine_scraper.storage.connection import (DatabaseConfigurationError,
                                                DatabaseSettings)
from sunshine_scraper.storage.models import Disclosure, MAX_BIGINT, salary_to_cents
from sunshine_scraper.storage.repository import PostgresSalaryRepository


def source_row(**changes):
    row = {'First Name': ' Alex\xa0 ', 'Surname': 'Example',
           'Position': ' Software   Developer ', 'Employer': 'Example Hospital',
           'Year': '2024', 'Salary': '$123,456.78'}
    row.update(changes)
    return row


class DisclosureTests(unittest.TestCase):
    def test_adapter_preserves_names_aliases_and_exact_money(self):
        raw = source_row()
        disclosure = Disclosure.from_source_row(raw)
        exported, _ = clean_record(raw, 'dataset')
        self.assertEqual(disclosure.first_name, 'Alex')
        self.assertEqual(disclosure.last_name, 'Example')
        self.assertEqual(disclosure.job_title, exported['Job Title'])
        self.assertEqual(disclosure.employer, exported['Employer'])
        self.assertEqual(disclosure.year, 2024)
        self.assertEqual(disclosure.salary_cents, 12345678)

    def test_money_is_exact_including_bigint_boundary(self):
        for value, expected in [('0.29', 29), (100, 10000),
                                (Decimal('100.0100'), 10001),
                                ('92233720368547758.07', MAX_BIGINT)]:
            with self.subTest(value=value):
                self.assertEqual(salary_to_cents(value), expected)

    def test_money_rejects_lossy_invalid_or_unrepresentable_values(self):
        for value in [0.29, True, None, '', 'NaN', 'Infinity', '-1', '1.001',
                      '92233720368547758.08', '1e-10000000']:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    salary_to_cents(value)

    def test_replayed_content_has_same_key_despite_case_and_whitespace(self):
        first = Disclosure.from_source_row(source_row())
        second = Disclosure.from_source_row(source_row(
            **{'First Name': 'alex', 'Surname': ' EXAMPLE ',
               'Position': 'software developer', 'Employer': 'example hospital',
               'Salary': '123456.7800'}))
        self.assertEqual(first.content_key, second.content_key)
        self.assertEqual(len(first.content_key), 64)

    def test_salary_correction_is_new_content_not_employee_identity(self):
        original = Disclosure.from_source_row(source_row())
        changed = replace(original, salary_cents=original.salary_cents + 1)
        self.assertNotEqual(original.content_key, changed.content_key)

    def test_first_last_name_boundaries_are_not_lost(self):
        first = Disclosure.from_source_row(source_row(
            **{'First Name': 'Alex Morgan', 'Surname': 'Lee'}))
        second = Disclosure.from_source_row(source_row(
            **{'First Name': 'Alex', 'Surname': 'Morgan Lee'}))
        self.assertNotEqual(first.content_key, second.content_key)

    def test_invalid_rows_and_direct_models_are_rejected(self):
        for row in [None, source_row(**{'First Name': ''}),
                    source_row(**{'Year': '202'}),
                    source_row(**{'Employer': []})]:
            with self.subTest(row=row):
                with self.assertRaises(ValueError):
                    Disclosure.from_source_row(row)
        valid = Disclosure.from_source_row(source_row())
        for changes in [{'year': True}, {'salary_cents': -1},
                        {'first_name': ' Alex '}, {'salary_cents': 1.0}]:
            with self.assertRaises(ValueError):
                replace(valid, **changes)


class ConfigurationTests(unittest.TestCase):
    def test_environment_is_explicit_and_secret_is_not_in_repr(self):
        url = 'postgresql://user:private-password@localhost/sunshine'
        settings = DatabaseSettings.from_environment({'SUNSHINE_DATABASE_URL': url})
        self.assertEqual(settings.database_url, url)
        self.assertNotIn('private-password', repr(settings))
        with self.assertRaises(DatabaseConfigurationError):
            DatabaseSettings.from_environment({})
        with self.assertRaises(DatabaseConfigurationError):
            DatabaseSettings(url, connect_timeout=0)

    def test_imports_do_not_load_psycopg_or_touch_a_database(self):
        # A fresh interpreter catches accidental top-level driver imports even
        # if another test has already imported these modules.
        program = (
            'import sys; '
            'import sunshine_scraper.storage.models; '
            'import sunshine_scraper.storage.connection; '
            'import sunshine_scraper.storage.repository; '
            'assert "psycopg" not in sys.modules'
        )
        result = subprocess.run([sys.executable, '-c', program],
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')

    def test_cli_without_settings_returns_actionable_error_before_connection(self):
        from sunshine_scraper.storage.__main__ import main
        with patch.dict(os.environ, {}, clear=True):
            with patch('sunshine_scraper.storage.__main__.open_connection') as connect:
                with self.assertLogs('sunshine_scraper.storage.__main__', level='ERROR'):
                    self.assertEqual(main(['check']), 1)
                connect.assert_not_called()


class RepositoryTests(unittest.TestCase):
    def test_returns_named_results_and_binds_query_inputs(self):
        connection = Mock()
        connection.execute.return_value.fetchall.return_value = [
            ('Alex', 'Example', 'Example Hospital', 12345678)]
        rows = PostgresSalaryRepository(connection).get_top_salaries(2024, 5)
        self.assertEqual(rows[0].name, 'Alex Example')
        self.assertEqual(rows[0].salary_cents, 12345678)
        self.assertEqual(connection.execute.call_args.args[1], (2024, 5))
        self.assertIn('%s', connection.execute.call_args.args[0])
        connection.commit.assert_not_called()
        connection.close.assert_not_called()

    def test_bad_filters_are_rejected_before_sql_execution(self):
        connection = Mock()
        reader = PostgresSalaryRepository(connection)
        for year, limit in [('2024 OR 1=1', 10), (True, 10), (2024, 0),
                            (2024, 101), (2024, True)]:
            with self.assertRaises(ValueError):
                reader.get_top_salaries(year, limit)
        connection.execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
