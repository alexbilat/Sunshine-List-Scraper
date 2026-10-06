"""Check scraper behavior with controlled inputs, including expected failures.

Run from the repository root: python -m unittest discover -s tests -v
unittest finds methods whose names start with test_ and reports failed assertions.
Most tests follow arrange (prepare inputs), act (call code), assert (check results).

Mock is a stand-in object: return_value sets what a call returns; side_effect
can raise an exception or supply successive outcomes from a list. patch replaces
an object temporarily and restores it when the decorated test/context ends.
Patch the name used by the module under test, so its calls use the replacement.

Network access and retry sleeps are replaced. Some tests still exercise real
TSV writing and PNG generation, using automatically cleaned temporary folders.
"""
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import requests
import matplotlib
# Use a noninteractive backend before importing reporting: save images without
# opening chart windows, so these tests also work on machines without a display.
matplotlib.use('Agg')
from sunshine_scraper.client import (request_page, fetch_all_records,
                                    fetch_csv_records, discover_resource_links)
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.processing import clean_record, process_records
from sunshine_scraper.pipeline import run
from sunshine_scraper.export import write_records
from sunshine_scraper.reporting import create_charts


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
        record, _ = clean_record(rows[0], 'new')
        self.assertEqual(record['Name'], 'Zo\u00eb Bilat')
        self.assertEqual(record['Employer'], 'Ontario, Agency')
        self.assertEqual(record['Job Title'], 'Manager, "Research"')
        self.assertEqual(record['Salary'], 123456.78)
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


class ProcessingTests(unittest.TestCase):
    """Exercise row cleaning directly; no HTTP calls or output files are needed."""

    def test_invalid_rows_and_duplicates(self):
        """Bad rows and cross-resource duplicates must not enter records or salary totals."""
        # Mirror pipeline state: accepted records, salaries by year, duplicate keys.
        rows, years, seen = [], {}, set()
        # Cover wrong row types, missing identity/year fields, and unusable salaries.
        bad = [None, [], 'row', {}, person(**{'First Name': None}),
               person(**{'Employer': {}}), person(**{'Salary Paid': 'NaN'}),
               person(**{'Salary Paid': 'inf'}), person(**{'Salary Paid': '-1'}),
               person(**{'Salary Paid': None}), person(**{'Calendar Year': 'unknown'})]
        with self.assertLogs('sunshine_scraper.processing', level='INFO') as logs:
            # *bad expands its items into this list, alongside one valid person.
            self.assertEqual(process_records([person(), *bad], 'a', rows, years, seen), (1, len(bad)))
            # Reuse the SAME collections for resource b to test cross-resource dedup.
            self.assertEqual(process_records([person(**{'First Name': 'alex'})], 'b', rows, years, seen), (0, 0))
        self.assertIn('1 duplicates', ' '.join(logs.output))
        self.assertEqual(rows[0]['Name'], 'Alex Bilat')
        # The first accepted occurrence keeps its source ID; no double-counting.
        self.assertEqual(rows[0]['UUID'], 'a')
        self.assertEqual(years, {'2024': [123456.0]})

    def test_fallback_fields_and_optional_title(self):
        """Alternate year/salary fields work, and an absent job title remains optional."""
        # Mirror pipeline state: accepted records, salaries by year, duplicate keys.
        rows, years, seen = [], {}, set()
        process_records([person(**{'Calendar Year': None, 'Year': 2023,
            'Salary Paid': None, 'Salary': '150000', 'Job Title': None})], 'a', rows, years, seen)
        self.assertEqual(rows[0]['Salary'], 150000)
        self.assertEqual(rows[0]['Year'], '2023')
        self.assertEqual(rows[0]['Job Title'], '')

    def test_historical_column_names_keep_names_titles_and_years(self):
        """Regression examples for the three main datasets previously rejected."""
        examples = [
            {'First Name': 'Alex', 'Surname': 'Bilat', 'Employer': 'Ontario',
             'Position': 'Developer', 'Salary Paid': '$123,456.00', 'Calendar Year': '2001'},
            {'First Name': 'Alex', 'Last name': 'Bilat', 'Employer': 'Ontario',
             'Job title': 'Developer', 'Salary Paid': '$123,456.00', 'Calendar year': '2014'},
            {'First name': 'Alex', 'Last name': 'Bilat', 'Employer': 'Ontario',
             'Job title': 'Developer', 'Salary': '123456', 'Year': '2020'},
            {' FIRST\xa0NAME ': 'Alex', '\ufeffLAST_NAME': 'Bilat', ' employer ': 'Ontario',
             'JOB_TITLE': 'Developer', 'SALARY_PAID': '123456', 'calendar_year': '2025'},
        ]
        for example, expected_year in zip(examples, ('2001', '2014', '2020', '2025')):
            with self.subTest(year=expected_year):
                record, _ = clean_record(example, 'source')
                self.assertEqual(record['Name'], 'Alex Bilat')
                self.assertEqual(record['Job Title'], 'Developer')
                self.assertEqual(record['Year'], expected_year)
                self.assertEqual(record['Salary'], 123456)

    def test_aliases_do_not_create_duplicate_disclosures(self):
        rows, years, seen = [], {}, set()
        process_records([person()], 'old', rows, years, seen)
        alternative = {'first name': 'Alex', 'surname': 'Bilat', 'employer': 'Ontario',
                       'position': 'Developer', 'salary': '123456', 'year': '2024'}
        process_records([alternative], 'new', rows, years, seen)
        self.assertEqual(len(rows), 1)
        self.assertEqual(years, {'2024': [123456]})

    def test_blank_preferred_columns_use_populated_aliases(self):
        record, _ = clean_record(person(**{'Last Name': ' ', 'Surname': 'Bilat',
            'Job Title': '', 'Position': 'Developer', 'Calendar Year': '\xa0',
            'Year': '2024', 'Salary Paid': '', 'Salary': '123456'}), 'source')
        self.assertEqual(record['Name'], 'Alex Bilat')
        self.assertEqual(record['Job Title'], 'Developer')
        self.assertEqual(record['Year'], '2024')
        self.assertEqual(record['Salary'], 123456)


class PipelineTests(unittest.TestCase):
    """Exercise coordination and output protection using synthetic datasets."""

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a', '/b'])
    @patch('sunshine_scraper.pipeline.fetch_all_records')
    def test_partial_run_exports_and_returns_failure(self, fetch, discover):
        """One failed dataset still allows export from another, but the run is incomplete."""
        # Resource a fails; resource b supplies one valid record.
        fetch.side_effect = [ScraperError('offline'), [person()]]
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / name for name in ('output.txt', 'yearly.png', 'titles.png')]
            with self.assertLogs('sunshine_scraper.pipeline', level='INFO') as logs:
                # *paths expands the TSV and two chart paths as positional arguments.
                self.assertFalse(run('page', 'api', *paths))
            self.assertTrue(all(path.stat().st_size > 0 for path in paths))
            self.assertIn('Incomplete run', ' '.join(logs.output))
            # Header plus the one accepted person; chart existence is checked above.
            self.assertEqual(len(paths[0].read_text().splitlines()), 2)

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a'])
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[])
    def test_empty_run_preserves_output(self, fetch, discover):
        """An empty collection must not replace an existing output file."""
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            # Seed an earlier export so preservation can be checked after failure.
            output = Path(directory) / 'out.txt'; output.write_text('old')
            with self.assertRaises(ScraperError):
                run('page', 'api', output, 'yearly.png', 'titles.png')
            self.assertEqual(output.read_text(), 'old')

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a'])
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[person()])
    @patch('sunshine_scraper.pipeline.create_charts', side_effect=OSError('denied'))
    def test_chart_failure_keeps_tsv(self, charts, fetch, discover):
        """A chart error reports failure while retaining the already-written TSV."""
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            self.assertFalse(run('page', 'api', output, 'yearly.png', 'titles.png'))
            # TSV writing happens before chart generation, so this file survives.
            self.assertTrue(output.exists())

    @patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a', '/b'])
    @patch('sunshine_scraper.pipeline.fetch_all_records')
    @patch('sunshine_scraper.pipeline.create_charts')
    def test_complete_run_sorts_and_deduplicates(self, charts, fetch, discover):
        """A successful run merges resources, removes duplicates, and sorts salaries."""
        # Two resources share one person; the second also has a higher salary.
        # Chart generation is mocked here to focus on coordination and TSV contents.
        fetch.side_effect = [[person()], [person(), person(**{'First Name': 'Other', 'Salary Paid': '200000'})]]
        # Real file operations stay inside a scratch directory, deleted on exit.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            self.assertTrue(run('page', 'api', output, 'yearly.png', 'titles.png'))
            lines = output.read_text().splitlines()
            self.assertEqual(lines[0], 'Name\tSalary\tJob Title\tEmployer\tYear\tUUID')
            # Header plus TWO unique people, with the higher salary first.
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[1].startswith('Other Bilat\t200000.0'))
            charts.assert_called_once()

    @patch('sunshine_scraper.pipeline.discover_resource_links')
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[person()])
    @patch('sunshine_scraper.pipeline.fetch_csv_records')
    @patch('sunshine_scraper.pipeline.create_charts')
    def test_current_csv_rows_join_historical_rows_in_the_export(self, charts, csv_fetch, fetch, discover):
        """Both download methods reach the same cleaning, sorting, and TSV writer."""
        csv_url = 'https://www.ontario.ca/files/2025/Compendium/new-id/current.csv?download=1'
        discover.return_value = ['/resource/old-id', csv_url]
        csv_fetch.return_value = [{'First name': 'Other', 'Last name': 'Bilat',
            'Employer': 'Ontario', 'Position': 'Director', 'Salary': '200000', 'Year': '2025'}]
        with tempfile.TemporaryDirectory() as directory:
            import csv
            output = Path(directory) / 'out.txt'
            self.assertTrue(run('page', 'api', output, 'yearly.png', 'titles.png'))
            with output.open(encoding='utf-8', newline='') as source:
                rows = list(csv.DictReader(source, delimiter='\t'))
            self.assertEqual([row['Year'] for row in rows], ['2025', '2024'])
            self.assertEqual(rows[0]['UUID'], 'new-id')
            self.assertEqual(rows[0]['Job Title'], 'Director')
            self.assertEqual(rows[1]['UUID'], 'old-id')
        fetch.assert_called_once_with('api', 'old-id', timeout=30, max_retries=2, backoff=1)
        csv_fetch.assert_called_once_with(csv_url, timeout=30, max_retries=2, backoff=1)

    @patch('sunshine_scraper.pipeline.discover_resource_links',
           return_value=['/resource/old', 'https://www.ontario.ca/files/new/data.csv'])
    @patch('sunshine_scraper.pipeline.fetch_all_records', return_value=[person()])
    @patch('sunshine_scraper.pipeline.fetch_csv_records', side_effect=ScraperError('broken download'))
    @patch('sunshine_scraper.pipeline.create_charts')
    def test_failed_current_download_reports_an_incomplete_run(self, charts, csv_fetch, fetch, discover):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'out.txt'
            with self.assertLogs('sunshine_scraper.pipeline', level='ERROR') as logs:
                self.assertFalse(run('page', 'api', output, 'yearly.png', 'titles.png'))
            self.assertEqual(len(output.read_text().splitlines()), 2)
            self.assertIn('Incomplete run', ' '.join(logs.output))

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
            create_charts([], {}, root / 'empty.png', root / 'titles.png')
            self.assertTrue((root / 'empty.png').exists())
            self.assertFalse((root / 'titles.png').exists())
            # This subdirectory is deliberately absent to force a real save error.
            with self.assertRaises(OSError):
                create_charts([], {}, root / 'missing' / 'chart.png', root / 'titles.png')
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
                            (RuntimeError('bug'), 1), (KeyboardInterrupt(), 130)]:
            with patch.object(entry, 'run', side_effect=error):
                self.assertEqual(entry.main(), code)


# Direct execution uses unittest's runner; discovery imports the test module.
if __name__ == '__main__':
    unittest.main()
