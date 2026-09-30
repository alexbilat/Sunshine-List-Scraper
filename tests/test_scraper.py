"""Offline regression checks for the module split."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import matplotlib
matplotlib.use('Agg')
from sunshine_scraper.client import discover_resource_links, fetch_all_records
from sunshine_scraper.processing import process_records
from sunshine_scraper.pipeline import run


def person(**changes):
    row = {'First Name': ' Alex\xa0 ', 'Last Name': 'Bilat',
           'Job Title': 'Developer', 'Employer': 'Ontario',
           'Calendar Year': '2024', 'Salary Paid': '$123,456.00'}
    row.update(changes)
    return row


class ScraperTests(unittest.TestCase):
    def test_discovery_and_pagination(self):
        page = Mock(status_code=200, content=b'<a href="/public-sector-salary-disclosure/resource/abc">Data</a><a href="/other">Other</a>')
        with patch('sunshine_scraper.client.requests.get', return_value=page):
            self.assertEqual(discover_resource_links('page'), ['/public-sector-salary-disclosure/resource/abc'])
        first = Mock(status_code=200)
        first.json.return_value = {'result': {'records': [{}] * 100000}}
        last = Mock(status_code=200)
        last.json.return_value = {'result': {'records': [{'end': True}]}}
        with patch('sunshine_scraper.client.requests.get', side_effect=[first, last]) as get:
            self.assertEqual(len(fetch_all_records('api', 'abc')), 100001)
            self.assertEqual(get.call_args.kwargs['params']['offset'], 100000)

    def test_cleaning_and_cross_resource_duplicates(self):
        rows, years, seen = [], {}, set()
        self.assertEqual(process_records([person(), {'a': 1, 'b': 2, 'c': 3},
            person(**{'Calendar Year': 'unknown'})], 'first', rows, years, seen), (1, 1))
        self.assertEqual(process_records([person(**{'First Name': 'alex'})], 'second', rows, years, seen), (0, 0))
        self.assertEqual(rows[0]['Name'], 'Alex Bilat')
        self.assertEqual(rows[0]['UUID'], 'first')
        self.assertEqual(years, {'2024': [123456.0]})
        process_records([person(**{'Salary Paid': None, 'Salary': 'bad', 'Calendar Year': None, 'Year': '2023'})], 'third', rows, years, seen)
        self.assertEqual(years['2023'], [0.0])

    def test_pipeline_outputs_and_empty_titles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / name for name in ('output.txt', 'yearly.png', 'titles.png')]
            with patch('sunshine_scraper.pipeline.discover_resource_links', return_value=['/a', '/b']), patch('sunshine_scraper.pipeline.fetch_all_records', side_effect=[[person()], [person(), person(**{'Salary Paid': '200000', 'First Name': 'Other'})]]), contextlib.redirect_stdout(io.StringIO()) as console:
                run('page', 'api', *paths)
            lines = paths[0].read_text(encoding='utf-8').splitlines()
            self.assertEqual(lines[0], 'Name\tSalary\tJob Title\tEmployer\tYear\tUUID')
            self.assertEqual(len(lines), 3)
            self.assertTrue(lines[1].startswith('Other Bilat\t200000.0\t'))
            self.assertIn('Number of people: 2', console.getvalue())
            self.assertTrue(all(path.stat().st_size > 0 for path in paths))
            from sunshine_scraper.reporting import create_charts
            create_charts([], {}, root / 'empty.png', root / 'empty_titles.png')
            self.assertTrue((root / 'empty.png').exists())
            self.assertFalse((root / 'empty_titles.png').exists())


if __name__ == '__main__':
    unittest.main()
