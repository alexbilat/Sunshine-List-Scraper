"""Offline failure scenarios; no real API requests or retry sleeps."""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
import matplotlib
matplotlib.use('Agg')
from sunshine_scraper.client import request_page, fetch_all_records, discover_resource_links
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.processing import process_records
from sunshine_scraper.pipeline import run
from sunshine_scraper.export import write_records
from sunshine_scraper.reporting import create_charts


def response(status=200, records=None):
    result = Mock(status_code=status)
    result.json.return_value = {'success': True, 'result': {'records': records or []}}
    return result


def person(**changes):
    row = {'First Name': ' Alex\xa0 ', 'Last Name': 'Bilat',
           'Job Title': 'Developer', 'Employer': 'Ontario',
           'Calendar Year': '2024', 'Salary Paid': '$123,456.00'}
    row.update(changes)
    return row


class RequestTests(unittest.TestCase):
    @patch('sunshine_scraper.client.time.sleep')
    @patch('sunshine_scraper.client.requests.get')
    def test_timeout_and_503_retry_then_success(self, get, sleep):
        good = response()
        get.side_effect = [requests.Timeout(), response(503), good]
        with self.assertLogs('sunshine_scraper.client', level='WARNING'):
            self.assertIs(request_page('url'), good)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(get.call_args.kwargs['timeout'], 30)

    @patch('sunshine_scraper.client.time.sleep')
    @patch('sunshine_scraper.client.requests.get')
    def test_status_policy_and_exhaustion(self, get, sleep):
        for status, attempts in [(404, 1), (401, 1), (429, 3), (500, 3)]:
            get.reset_mock(); sleep.reset_mock()
            get.side_effect = None; get.return_value = response(status)
            with self.assertRaises(ScraperError):
                request_page('url')
            self.assertEqual(get.call_count, attempts)
            self.assertEqual(sleep.call_count, attempts - 1)
        get.side_effect = requests.ConnectionError('offline')
        with self.assertRaises(ScraperError):
            request_page('url', max_retries=0)

    def test_bad_request_options(self):
        for options in ({'timeout': 0}, {'timeout': float('nan')},
                        {'max_retries': -1}, {'backoff': -1}):
            with self.assertRaises(ScraperError):
                request_page('url', **options)

    @patch('sunshine_scraper.client.request_page')
    def test_malformed_payloads(self, request):
        for payload in (None, [], {}, {'success': False},
                        {'success': True, 'result': {}},
                        {'success': True, 'result': {'records': {}}}):
            request.return_value = response()
            request.return_value.json.return_value = payload
            with self.assertRaisesRegex(ScraperError, 'offset 0'):
                fetch_all_records('api', 'abc')
        request.return_value.json.side_effect = ValueError('bad JSON')
        with self.assertRaisesRegex(ScraperError, 'valid JSON'):
            fetch_all_records('api', 'abc')

    @patch('sunshine_scraper.client.request_page')
    def test_pagination_and_failed_partial_resource(self, request):
        request.side_effect = [response(records=[person(), person()]), response(records=[person()])]
        self.assertEqual(len(fetch_all_records('api', 'abc', page_size=2)), 3)
        self.assertEqual(request.call_args.kwargs['params']['offset'], 2)
        request.side_effect = [response(records=[person(), person()]), ScraperError('failed')]
        with self.assertRaisesRegex(ScraperError, 'offset 2'):
            fetch_all_records('api', 'abc', page_size=2)
        request.side_effect = [response(records=[person(), person()])] * 2
        with self.assertRaisesRegex(ScraperError, 'repeated'):
            fetch_all_records('api', 'abc', page_size=2)

    @patch('sunshine_scraper.client.request_page')
    def test_discovery_deduplicates_and_rejects_empty_page(self, request):
        request.return_value.content = b'<a href="/public-sector-salary-disclosure/resource/abc">a</a><a href="/public-sector-salary-disclosure/resource/abc/?x=1">b</a>'
        self.assertEqual(len(discover_resource_links('page')), 1)
        request.return_value.content = b'<html></html>'
        with self.assertRaises(ScraperError):
            discover_resource_links('page')


class ProcessingTests(unittest.TestCase):
    def test_invalid_rows_and_duplicates(self):
        rows, years, seen = [], {}, set()
        bad = [None, [], 'row', {}, person(**{'First Name': None}),
               person(**{'Employer': {}}), person(**{'Salary Paid': 'NaN'}),
               person(**{'Salary Paid': 'inf'}), person(**{'Salary Paid': '-1'}),
               person(**{'Salary Paid': None}), person(**{'Calendar Year': 'unknown'})]
        with self.assertLogs('sunshine_scraper.processing', level='INFO') as logs:
            self.assertEqual(process_records([person(), *bad], 'a', rows, years, seen), (1, len(bad)))
            self.assertEqual(process_records([person(**{'First Name': 'alex'})], 'b', rows, years, seen), (0, 0))
        self.assertIn('1 duplicates', ' '.join(logs.output))
        self.assertEqual(rows[0]['Name'], 'Alex Bilat')
        self.assertEqual(rows[0]['UUID'], 'a')
        self.assertEqual(years, {'2024': [123456.0]})

    def test_fallback_fields_and_optional_title(self):
        rows, years, seen = [], {}, set()
        process_records([person(**{'Calendar Year': None, 'Year': 2023,
            'Salary Paid': None, 'Salary': '150000', 'Job Title': None})], 'a', rows, years, seen)
        self.assertEqual(rows[0]['Salary'], 150000)
        self.assertEqual(rows[0]['Year'], '2023')
        self.assertEqual(rows[0]['Job Title'], '')


class PipelineTests(unittest.TestCase):
    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a', '/b'])
    @patch('sunshine_scraper.pipeline.fetch_all_records')
    def test_partial_run_exports_and_returns_failure(self, fetch, discover):
        fetch.side_effect = [ScraperError('offline'), [person()]]
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('output.txt', 'yearly.png', 'titles.png')]
            with self.assertLogs('sunshine_scraper.pipeline', level='INFO') as logs:
                self.assertFalse(run('page', 'api', *paths))
            self.assertTrue(all(path.stat().st_size > 0 for path in paths))
            self.assertIn('Incomplete run', ' '.join(logs.output))
            self.assertEqual(len(paths[0].read_text().splitlines()), 2)

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a'])
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[])
    def test_empty_run_preserves_output(self, fetch, discover):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'; output.write_text('old')
            with self.assertRaises(ScraperError):
                run('page', 'api', output, 'yearly.png', 'titles.png')
            self.assertEqual(output.read_text(), 'old')

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a'])
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[person()])
    @patch('sunshine_scraper.pipeline.create_charts', side_effect=OSError('denied'))
    def test_chart_failure_keeps_tsv(self, charts, fetch, discover):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            self.assertFalse(run('page', 'api', output, 'yearly.png', 'titles.png'))
            self.assertTrue(output.exists())

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a', '/b'])
    @patch('sunshine_scraper.pipeline.fetch_all_records')
    @patch('sunshine_scraper.pipeline.create_charts')
    def test_complete_run_sorts_and_deduplicates(self, charts, fetch, discover):
        fetch.side_effect = [[person()], [person(), person(**{'First Name': 'Other', 'Salary Paid': '200000'})]]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            self.assertTrue(run('page', 'api', output, 'yearly.png', 'titles.png'))
            lines = output.read_text().splitlines()
            self.assertEqual(lines[0], 'Name\tSalary\tJob Title\tEmployer\tYear\tUUID')
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[1].startswith('Other Bilat\t200000.0'))
            charts.assert_called_once()

    def test_tsv_quotes_embedded_delimiters(self):
        import csv
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            write_records([{'Name': 'Alex', 'Job Title': 'A\tB"C'}], output)
            with output.open(newline='', encoding='utf-8') as source:
                rows = list(csv.DictReader(source, delimiter='\t'))
            self.assertEqual(rows[0]['Job Title'], 'A\tB"C')

    def test_failed_export_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'; output.write_text('old')
            with patch('sunshine_scraper.export.os.replace', side_effect=PermissionError('denied')):
                with self.assertRaises(OSError):
                    write_records([{'Name': 'Alex'}], output)
            self.assertEqual(output.read_text(), 'old')
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_empty_titles_and_failed_chart_close_figures(self):
        from matplotlib import pyplot as plt
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_charts([], {}, root / 'empty.png', root / 'titles.png')
            self.assertTrue((root / 'empty.png').exists())
            self.assertFalse((root / 'titles.png').exists())
            with self.assertRaises(OSError):
                create_charts([], {}, root / 'missing' / 'chart.png', root / 'titles.png')
            self.assertEqual(plt.get_fignums(), [])


class EntryPointTests(unittest.TestCase):
    def test_exit_codes(self):
        spec = importlib.util.spec_from_file_location('entry', 'Sunshine_List_Scaper.py')
        entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
        for result, code in [(True, 0), (False, 1)]:
            with patch.object(entry, 'run', return_value=result):
                self.assertEqual(entry.main(), code)
        for error, code in [(ScraperError('offline'), 1), (OSError('denied'), 1),
                            (RuntimeError('bug'), 1), (KeyboardInterrupt(), 130)]:
            with patch.object(entry, 'run', side_effect=error):
                self.assertEqual(entry.main(), code)


if __name__ == '__main__':
    unittest.main()
