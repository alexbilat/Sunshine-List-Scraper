"""Check scraper behavior with controlled inputs, including expected failures.

Run from the repository root: python -m unittest discover -s tests -v
unittest finds methods whose names start with test_ and reports failed assertions.
Most tests follow arrange (prepare inputs), act (call code), assert (check results).

Mock is a stand-in object: return_value sets what a call returns; side_effect
can raise an exception or supply successive outcomes from a list. patch replaces
an object temporarily and restores it when the decorated test/context ends.
Patch the name used by the module under test, so its calls use the replacement.

Network access, retry sleeps, and the database are replaced. Some tests still
exercise real TSV writing and PNG generation, using temporary folders.
Real-database behaviour is covered by tests/test_postgres_integration.py.
"""
from contextlib import contextmanager
from decimal import Decimal
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
import requests
import matplotlib
# Use a noninteractive backend before importing reporting: save images without
# opening chart windows, so these tests also work on machines without a display.
matplotlib.use('Agg')
from sunshine_scraper.client import (request_page, fetch_all_records, fetch_csv_download,
                                    fetch_csv_records, fetch_ckan_resource_version,
                                    discover_resource_links)
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.pipeline import run
from sunshine_scraper.export import write_records
from sunshine_scraper.reporting import create_charts
from sunshine_scraper.storage.connection import (DatabaseAccessError,
                                                DatabaseConfigurationError, DatabaseSettings)
from sunshine_scraper.storage.migrations import MigrationError
from sunshine_scraper.storage.models import Disclosure, TitleCount, YearSummary
from sunshine_scraper.sync import SyncResult


def response(status=200, records=None):
    """Build a fake HTTP response with the attributes the client actually uses."""
    # This is not a requests.Response; it only mimics status_code and json().
    result = Mock(status_code=status)
    result.json.return_value = {'success': True, 'result': {'records': records or []}}
    return result


def person(**changes):
    """Build a fresh valid row, overriding selected fields for a specific scenario."""
    row = {'First Name': ' Alex\xa0 ', 'Last Name': 'Bilat',
           'Job Title': 'Developer', 'Employer': 'Ontario',
           'Calendar Year': '2024', 'Salary Paid': '$123,456.00'}
    # **changes collects keyword arguments into a dict. Tests pass **{...} when
    # field names contain spaces and cannot be written as ordinary keywords.
    row.update(changes)
    return row


class RequestTests(unittest.TestCase):
    """Exercise HTTP recovery, discovery, and API pagination without a live server."""

    # Stacked patches inject mocks bottom-up: get first, then sleep.
    # Replacing sleep lets us inspect delays without actually waiting.
    @patch('sunshine_scraper.client.time.sleep')
    @patch('sunshine_scraper.client.requests.get')
    def test_timeout_and_503_retry_then_success(self, get, sleep):
        """A timeout and HTTP 503 should retry, then return the successful response."""
        good = response()
        # Each successive GET raises/returns the next item in this sequence.
        get.side_effect = [requests.Timeout(), response(503), good]
        # assertLogs captures messages and fails if none meet the requested level.
        with self.assertLogs('sunshine_scraper.client', level='WARNING'):
            # assertIs checks that the exact successful object is returned.
            self.assertIs(request_page('url'), good)
        # call_args_list records every call; args[0] is the requested sleep delay.
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [1, 2])
        self.assertEqual(get.call_args.kwargs['timeout'], 30)

    @patch('sunshine_scraper.client.time.sleep')
    @patch('sunshine_scraper.client.requests.get')
    def test_status_policy_and_exhaustion(self, get, sleep):
        """Permanent statuses stop immediately; temporary failures exhaust bounded retries."""
        # With two extra retries, temporary errors make three total requests.
        for status, attempts in [(404, 1), (401, 1), (429, 3), (500, 3)]:
            # Clear call history so the next status has independent counts.
            get.reset_mock(); sleep.reset_mock()
            get.side_effect = None; get.return_value = response(status)
            # An expected exception makes this assertion pass, not fail.
            with self.assertRaises(ScraperError):
                request_page('url')
            self.assertEqual(get.call_count, attempts)
            self.assertEqual(sleep.call_count, attempts - 1)
        # max_retries=0 means even a retryable connection failure stops at once.
        get.side_effect = requests.ConnectionError('offline')
        with self.assertRaises(ScraperError):
            request_page('url', max_retries=0)

    def test_bad_request_options(self):
        """Reject invalid settings before a network request can be attempted."""
        # NaN is a non-finite float; it is not a usable timeout.
        # **options supplies each dictionary entry as a named argument.
        for options in ({'timeout': 0}, {'timeout': float('nan')},
                        {'max_retries': -1}, {'backoff': -1}):
            with self.assertRaises(ScraperError):
                request_page('url', **options)

    @patch('sunshine_scraper.client.request_page')
    def test_malformed_payloads(self, request):
        """Reject broken JSON structures and JSON decoding failures with useful context."""
        # These are valid Python values but violate CKAN's expected schema.
        for payload in (None, [], {}, {'success': False},
                        {'success': True, 'result': {}},
                        {'success': True, 'result': {'records': {}}}):
            request.return_value = response()
            request.return_value.json.return_value = payload
            # Also check message context: which page caused the failure?
            with self.assertRaisesRegex(ScraperError, 'offset 0'):
                fetch_all_records('api', 'abc')
        # Separately simulate json() failing to decode the response body.
        request.return_value.json.side_effect = ValueError('bad JSON')
        with self.assertRaisesRegex(ScraperError, 'valid JSON'):
            fetch_all_records('api', 'abc')

    @patch('sunshine_scraper.client.request_page')
    def test_pagination_and_failed_partial_resource(self, request):
        """Check page offsets, later-page failure, and protection against repeated pages."""
        # A tiny page size tests pagination without constructing 100,000 rows.
        # Two rows fill page one; one row on page two ends the dataset.
        request.side_effect = [response(records=[person(), person()]), response(records=[person()])]
        self.assertEqual(len(fetch_all_records('api', 'abc', page_size=2)), 3)
        self.assertEqual(request.call_args.kwargs['params']['offset'], 2)
        # Page one succeeds, but page two fails: returning partial data is forbidden.
        request.side_effect = [response(records=[person(), person()]), ScraperError('failed')]
        with self.assertRaisesRegex(ScraperError, 'offset 2'):
            fetch_all_records('api', 'abc', page_size=2)
        # A server repeating the same full page must not cause an endless loop.
        request.side_effect = [response(records=[person(), person()])] * 2
        with self.assertRaisesRegex(ScraperError, 'repeated'):
            fetch_all_records('api', 'abc', page_size=2)

    @patch('sunshine_scraper.client.request_page')
    def test_discovery_deduplicates_and_rejects_empty_page(self, request):
        """Two links to the same ID count once; a page with no resource links fails."""
        # b'...' supplies HTML bytes, like response.content from requests.
        # The different query string/trailing slash still identifies resource abc.
        request.return_value.content = b'<a href="/public-sector-salary-disclosure/resource/abc">a</a><a href="/public-sector-salary-disclosure/resource/abc/?x=1">b</a>'
        self.assertEqual(len(discover_resource_links('page')), 1)
        request.return_value.content = b'<html></html>'
        with self.assertRaises(ScraperError):
            discover_resource_links('page')

    @patch('sunshine_scraper.client.request_page')
    def test_discovery_includes_current_and_future_year_downloads(self, request):
        """Mix old CKAN links with the English downloads for advertised new years."""
        landing = Mock(content=b'''
            <a href="https://data.ontario.ca/dataset/public-sector-salary-disclosure-2020/resource/old">old</a>
            <a href="/public-sector-salary-disclosure/2021/all-sectors-and-seconded-employees/">main</a>
            <a href="https://www.ontario.ca/public-sector-salary-disclosure/2021/all-sectors-and-seconded-employees?x=1">again</a>
            <a href="/public-sector-salary-disclosure/2021/addendum/">changes</a>
            <a href="/public-sector-salary-disclosure/2021/organizations-no-salaries-disclose/">organizations</a>
            <a href="/public-sector-salary-disclosure/2026/all-sectors-and-seconded-employees/">future</a>
        ''')
        manifest = Mock()
        manifest.json.return_value = {
            '2021': {
                'Compendium': {'en': {'csv': '/files/main/main.csv'},
                               'fr': {'csv': '/files/french/main.csv'}},
                'Addendum': {'en': {'csv': '/files/changes/addendum.csv'}},
                'NoSalary': {'en': {'csv': '/files/organizations/no-salaries.csv'}},
            },
            '2026': {'Compendium': {'en': {'csv': '/files/future/main.csv'}}},
            '2027': {'Compendium': {'en': {'csv': '/files/unadvertised/main.csv'}}},
        }
        request.side_effect = [landing, manifest]
        links = discover_resource_links('https://www.ontario.ca/page/public-sector-salary-disclosure',
                                        timeout=12, max_retries=0)
        self.assertEqual(links, [
            'https://data.ontario.ca/dataset/public-sector-salary-disclosure-2020/resource/old',
            'https://www.ontario.ca/files/main/main.csv',
            'https://www.ontario.ca/files/changes/addendum.csv',
            'https://www.ontario.ca/files/future/main.csv',
        ])
        self.assertEqual(request.call_count, 2)
        request.assert_called_with(
            'https://www.ontario.ca/public-sector-salary-disclosure_artifacts/pssdfiles.json',
            timeout=12, max_retries=0)

    @patch('sunshine_scraper.client.request_page')
    def test_missing_or_broken_manifest_does_not_silently_omit_a_year(self, request):
        """A published modern year must resolve to a usable English CSV link."""
        landing = Mock(content=b'<a href="/public-sector-salary-disclosure/2025/all-sectors-and-seconded-employees/">main</a>')
        for payload in (None, [], {}, {'2025': None},
                        {'2025': {'Compendium': {'en': {'csv': ''}}}},
                        {'2025': {'Compendium': {'en': {'csv': '/file.html'}}}}):
            with self.subTest(payload=payload):
                manifest = Mock()
                manifest.json.return_value = payload
                request.side_effect = [landing, manifest]
                with self.assertRaises(ScraperError):
                    discover_resource_links('https://www.ontario.ca/page/public-sector-salary-disclosure')
        manifest = Mock()
        manifest.json.side_effect = ValueError('not JSON')
        request.side_effect = [landing, manifest]
        with self.assertRaisesRegex(ScraperError, 'manifest is not valid JSON'):
            discover_resource_links('https://www.ontario.ca/page/public-sector-salary-disclosure')

    @patch('sunshine_scraper.client.request_page')
    def test_csv_download_preserves_quotes_commas_unicode_and_bom(self, request):
        """Read Ontario-style CSV without splitting commas inside quoted fields."""
        request.return_value.content = (
            '\ufeffFirst name,Last name,Employer,Position,Salary,Year\r\n'
            'Zo\u00eb,Bilat,"Ontario, Agency","Manager, \"\"Research\"\"",'
            '"$123,456.78",2025\r\n'
        ).encode('utf-8')
        rows = fetch_csv_records('https://www.ontario.ca/files/new/data.csv', timeout=15)
        self.assertEqual(len(rows), 1)
        disclosure = Disclosure.from_source_row(rows[0])
        self.assertEqual((disclosure.first_name, disclosure.last_name), ('Zo\u00eb', 'Bilat'))
        self.assertEqual(disclosure.employer, 'Ontario, Agency')
        self.assertEqual(disclosure.job_title, 'Manager, "Research"')
        self.assertEqual(disclosure.salary_cents, 12345678)
        request.assert_called_once_with('https://www.ontario.ca/files/new/data.csv', timeout=15)

    @patch('sunshine_scraper.client.request_page')
    def test_broken_csv_download_is_not_returned_as_a_partial_dataset(self, request):
        header = b'First Name,Last Name,Employer,Salary,Year\n'
        good_row = b'Alex,Bilat,Ontario,123456,2025\n'
        for content in (b'', b'<html>Error</html>', b'Employer,Year\nOntario,2025\n',
                        header + good_row + b'A,B,C,1,2025,extra\n',
                        header + good_row + b'"unfinished', header + b'\xff'):
            with self.subTest(content=content):
                request.return_value.content = content
                with self.assertRaises(ScraperError):
                    fetch_csv_records('https://www.ontario.ca/files/new/data.csv')


    @patch('sunshine_scraper.client.time.sleep')
    @patch('sunshine_scraper.client.requests.get')
    def test_304_is_accepted_only_when_requested(self, get, sleep):
        """A conditional request may answer 304; any other request treats it as an error."""
        get.return_value = response(304)
        with self.assertRaises(ScraperError):
            request_page('url')
        self.assertEqual(request_page('url', not_modified_ok=True).status_code, 304)

    @patch('sunshine_scraper.client.request_page')
    def test_duplicate_csv_headers_fail_instead_of_overwriting_values(self, request):
        for duplicate in ('Salary', ' salary ', 'SALARY'):
            with self.subTest(duplicate=duplicate):
                request.return_value.content = (
                    f'First Name,Last Name,Employer,Salary,Year,{duplicate}\n'
                    'Alex,Bilat,Ontario,123456,2025,654321\n'
                ).encode('utf-8')
                with self.assertRaisesRegex(ScraperError, 'duplicate.*column headers'):
                    fetch_csv_records('https://www.ontario.ca/files/new/data.csv')

    @patch('sunshine_scraper.client.request_page')
    def test_truncated_csv_rows_fail_but_explicit_blank_cells_are_allowed(self, request):
        header = b'First Name,Last Name,Employer,Salary,Year,Job Title\n'
        good_row = b'Alex,Bilat,Ontario,123456,2025,Developer\n'
        for truncated in (b'Other,Bilat,Ontario,123456\n',
                          b'Other,Bilat,Ontario,123456,2025\n'):
            with self.subTest(row=truncated):
                request.return_value.content = header + good_row + truncated
                with self.assertRaisesRegex(ScraperError, 'line 3: fewer values'):
                    fetch_csv_records('https://www.ontario.ca/files/new/data.csv')
        # A trailing delimiter explicitly supplies an empty optional title.
        request.return_value.content = header + b'Alex,Bilat,Ontario,123456,2025,\n'
        rows = fetch_csv_records('https://www.ontario.ca/files/new/data.csv')
        self.assertEqual(Disclosure.from_source_row(rows[0]).job_title, '')

    @patch('sunshine_scraper.client.requests.get')
    def test_csv_304_without_validators_fails_instead_of_skipping_a_new_source(self, get):
        get.return_value = response(304)
        with self.assertRaisesRegex(ScraperError, 'HTTP 304'):
            fetch_csv_download('https://x.test/a.csv')
        self.assertIsNone(fetch_csv_download('https://x.test/a.csv', etag='"v1"'))
        self.assertIsNone(fetch_csv_download('https://x.test/a.csv', last_modified='Mon'))

    @patch('sunshine_scraper.client.request_page')
    def test_conditional_csv_download(self, request):
        """Stored validators are sent; 304 returns None; 200 returns new validators."""
        request.return_value = Mock(status_code=304)
        self.assertIsNone(fetch_csv_download('https://x.test/a.csv', etag='"v1"',
                                             last_modified='Mon, 23 Mar 2026 14:45:50 GMT'))
        self.assertEqual(request.call_args.kwargs['headers'],
                         {'If-None-Match': '"v1"',
                          'If-Modified-Since': 'Mon, 23 Mar 2026 14:45:50 GMT'})
        content = b'First Name,Last Name,Employer,Salary,Year\nAlex,Bilat,Ontario,123456,2025\n'
        request.return_value = Mock(status_code=200, content=content,
                                    headers={'ETag': '"v2"', 'Last-Modified': 'later'})
        download = fetch_csv_download('https://x.test/a.csv')
        self.assertIsNone(request.call_args.kwargs['headers'])
        self.assertFalse(request.call_args.kwargs['not_modified_ok'])
        self.assertEqual(len(download.records), 1)
        self.assertEqual((download.etag, download.last_modified), ('"v2"', 'later'))
        self.assertEqual(len(download.content_sha256), 64)

    @patch('sunshine_scraper.client.request_page')
    def test_ckan_version_uses_resource_show(self, request):
        """CKAN's own modification time is read from resource_show, beside datastore_search."""
        request.return_value.json.return_value = {
            'success': True, 'result': {'last_modified': '2023-06-15T20:38:17',
                                        'metadata_modified': '2023-07-03T16:47:19'}}
        version = fetch_ckan_resource_version(
            'https://data.ontario.ca/api/3/action/datastore_search', 'abc')
        self.assertEqual(version, '2023-06-15T20:38:17')
        self.assertEqual(request.call_args.args[0],
                         'https://data.ontario.ca/api/3/action/resource_show')
        # metadata_modified is the fallback when last_modified is missing.
        request.return_value.json.return_value = {
            'success': True, 'result': {'last_modified': None, 'metadata_modified': 'm'}}
        self.assertEqual(fetch_ckan_resource_version('https://x.test/action/datastore_search', 'a'), 'm')
        for payload in (None, {'success': False}, {'success': True, 'result': []}):
            request.return_value.json.return_value = payload
            with self.assertRaises(ScraperError):
                fetch_ckan_resource_version('https://x.test/action/datastore_search', 'a')


class FakeReader:
    """Stands in for PostgresSalaryRepository with fixed query results."""

    def __init__(self, records):
        self.records = records

    def count_records(self):
        return len(self.records)

    def iter_export_records(self):
        yield from self.records

    def yearly_summary(self):
        return [YearSummary(2024, len(self.records), Decimal('12345600'))] if self.records else []

    def top_job_titles(self, limit):
        return [TitleCount('Developer', len(self.records))] if self.records else []


def export_row(name='Alex Bilat', salary='123456.00', uuid='a'):
    """One row as the repository's export query yields it."""
    return {'Name': name, 'Salary': salary, 'Job Title': 'Developer',
            'Employer': 'Ontario', 'Year': 2024, 'UUID': uuid}


SETTINGS = DatabaseSettings('postgresql://user@localhost/test')


class PipelineTests(unittest.TestCase):
    """Exercise coordination and output protection with a fake database."""

    def setUp(self):
        # A MagicMock connection supports "with connection.transaction():".
        self.connection = MagicMock()

        @contextmanager
        def fake_open_connection(settings, autocommit=False):
            yield self.connection

        for target, replacement in [
                ('sunshine_scraper.pipeline.open_connection', fake_open_connection),
                ('sunshine_scraper.pipeline.ensure_schema_current', Mock())]:
            patcher = patch(target, replacement)
            patcher.start()
            # addCleanup restores the original even if the test fails.
            self.addCleanup(patcher.stop)

    def run_with(self, sync_result, records, directory, charts=None):
        """Run the pipeline with a fixed sync outcome and fixed database rows."""
        paths = [Path(directory) / name for name in ('output.txt', 'yearly.png', 'titles.png')]
        with patch('sunshine_scraper.pipeline.run_sync', return_value=sync_result) as sync, \
                patch('sunshine_scraper.pipeline.PostgresSalaryRepository',
                      return_value=FakeReader(records)), \
                patch('sunshine_scraper.pipeline.create_charts', charts or Mock()):
            result = run('page', 'api', *paths, settings=SETTINGS)
        return result, paths, sync

    def test_partial_run_exports_and_returns_failure(self):
        """One failed dataset still allows export from the database, but the run is incomplete."""
        partial = SyncResult('partial', 1, 2, loaded=['b'], failed=['a'])
        with tempfile.TemporaryDirectory() as directory:
            with self.assertLogs('sunshine_scraper.pipeline', level='INFO') as logs:
                result, paths, _ = self.run_with(partial, [export_row()], directory)
            self.assertFalse(result)
            self.assertIn('Incomplete run', ' '.join(logs.output))
            # Header plus the one stored record.
            self.assertEqual(len(paths[0].read_text(encoding='utf-8').splitlines()), 2)

    def test_empty_database_preserves_output(self):
        """An empty database must not replace an existing output file."""
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output.txt'; output.write_text('old')
            with self.assertRaises(ScraperError):
                self.run_with(SyncResult('failed', 1, 1, failed=['a']), [], directory)
            self.assertEqual(output.read_text(), 'old')

    def test_chart_failure_keeps_tsv(self):
        """A chart error reports failure while retaining the already-written TSV."""
        with tempfile.TemporaryDirectory() as directory:
            result, paths, _ = self.run_with(SyncResult('succeeded', 1, 1, loaded=['a']),
                                             [export_row()], directory,
                                             charts=Mock(side_effect=OSError('denied')))
            self.assertFalse(result)
            self.assertTrue(paths[0].exists())

    def test_complete_run_exports_database_rows_in_order(self):
        """The TSV is exactly what the database returns, in its salary order."""
        import csv
        charts = Mock()
        rows = [export_row('Other Bilat', '200000.00', 'b'), export_row()]
        with tempfile.TemporaryDirectory() as directory:
            result, paths, sync = self.run_with(SyncResult('succeeded', 1, 2, loaded=['a', 'b']),
                                                rows, directory, charts=charts)
            self.assertTrue(result)
            with paths[0].open(encoding='utf-8', newline='') as source:
                exported = list(csv.DictReader(source, delimiter='\t'))
        self.assertEqual([row['Salary'] for row in exported], ['200000.00', '123456.00'])
        self.assertEqual(exported[0]['UUID'], 'b')
        self.assertEqual(sync.call_args.kwargs['full_refresh'], False)
        charts.assert_called_once()

    def test_unchanged_sources_still_count_as_complete(self):
        """Skipping a dataset Ontario has not changed is success, not a gap."""
        with tempfile.TemporaryDirectory() as directory:
            result, _, _ = self.run_with(SyncResult('succeeded', 1, 1, unchanged=['a']),
                                         [export_row()], directory)
            self.assertTrue(result)

    def test_overlapping_run_is_a_quiet_no_op(self):
        """While another sync holds the lock, nothing is exported and the run succeeds."""
        with tempfile.TemporaryDirectory() as directory:
            result, paths, _ = self.run_with(SyncResult('locked'), [export_row()], directory)
            self.assertTrue(result)
            self.assertFalse(paths[0].exists())

    def test_database_settings_are_checked_before_any_download(self):
        with patch.dict('os.environ', {}, clear=True), \
                patch('sunshine_scraper.pipeline.run_sync') as sync:
            with self.assertRaises(DatabaseConfigurationError):
                run('page', 'api', 'out.txt', 'yearly.png', 'titles.png')
            sync.assert_not_called()

    def test_outdated_schema_stops_before_sync(self):
        with patch('sunshine_scraper.pipeline.ensure_schema_current',
                   side_effect=MigrationError('pending')), \
                patch('sunshine_scraper.pipeline.run_sync') as sync:
            with self.assertRaises(MigrationError):
                run('page', 'api', 'out.txt', 'yearly.png', 'titles.png', settings=SETTINGS)
            sync.assert_not_called()

    def test_tsv_quotes_embedded_delimiters(self):
        """A TSV-aware reader must recover tabs and quotes inside a field unchanged."""
        import csv
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            # The embedded tab and quote must remain within one field.
            # Missing columns are intentional: this test targets the writer directly.
            write_records([{'Name': 'Alex', 'Job Title': 'A\tB"C'}], output)
            with output.open(newline='', encoding='utf-8') as source:
                rows = list(csv.DictReader(source, delimiter='\t'))
            self.assertEqual(rows[0]['Job Title'], 'A\tB"C')

    def test_failed_export_preserves_previous_file(self):
        """Failed replacement keeps the old export and removes its temporary file."""
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            # Seed an earlier export so preservation can be checked after failure.
            output = Path(directory) / 'out.txt'; output.write_text('old')
            # Simulate final publication failing after the temporary TSV is written.
            # PermissionError is a subclass of OSError, hence the assertion below.
            with patch('sunshine_scraper.export.os.replace', side_effect=PermissionError('denied')):
                with self.assertRaises(OSError):
                    write_records([{'Name': 'Alex'}], output)
            self.assertEqual(output.read_text(), 'old')
            # No leftover temporary export should remain beside the original.
            self.assertEqual(list(Path(directory).iterdir()), [output])

    def test_empty_titles_and_failed_chart_close_figures(self):
        """Empty titles skip that chart; a save error must still close the figure."""
        from matplotlib import pyplot as plt
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            create_charts([], [], root / 'empty.png', root / 'titles.png')
            self.assertTrue((root / 'empty.png').exists())
            self.assertFalse((root / 'titles.png').exists())
            # This subdirectory is deliberately absent to force a real save error.
            with self.assertRaises(OSError):
                create_charts([], [], root / 'missing' / 'chart.png', root / 'titles.png')
            # No open matplotlib figures should remain after success or failure.
            self.assertEqual(plt.get_fignums(), [])


class EntryPointTests(unittest.TestCase):
    """Exercise the command-line boundary while replacing the actual scrape."""

    def test_exit_codes(self):
        """main translates completion, failures, and user interruption into exit codes."""
        # Load the script as a module so we can call main without exiting Python.
        # Its __main__ guard prevents the real scrape from running on import.
        spec = importlib.util.spec_from_file_location('entry', 'Sunshine_List_Scaper.py')
        entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
        # Replace entry.run: test only the CLI's mapping of outcomes to exit codes.
        for result, code in [(True, 0), (False, 1)]:
            with patch.object(entry, 'run', return_value=result):
                self.assertEqual(entry.main(), code)
        # Logged errors/tracebacks are expected fixtures here, not failed tests.
        # Ctrl+C uses 130; expected and unexpected failures use 1.
        for error, code in [(ScraperError('offline'), 1), (OSError('denied'), 1),
                            (DatabaseConfigurationError('no URL'), 1),
                            (DatabaseAccessError('unreachable'), 1),
                            (MigrationError('pending'), 1),
                            (RuntimeError('bug'), 1), (KeyboardInterrupt(), 130)]:
            with patch.object(entry, 'run', side_effect=error):
                self.assertEqual(entry.main(), code)


# Direct execution uses unittest's runner; discovery imports the test module.
if __name__ == '__main__':
    unittest.main()
