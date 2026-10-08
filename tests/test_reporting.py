"""Regression checks for chart inputs at the reporting boundary."""
from pathlib import Path
import tempfile
import unittest

from matplotlib import pyplot as plt

from sunshine_scraper.reporting import create_charts


class ReportingTests(unittest.TestCase):
    def test_empty_year_bucket_still_writes_charts(self):
        with tempfile.TemporaryDirectory() as directory:
            yearly = Path(directory) / 'yearly.png'
            titles = Path(directory) / 'titles.png'
            create_charts([{'Job Title': 'Developer'}],
                          {'2023': [], '2024': [120000]}, yearly, titles)
            self.assertGreater(yearly.stat().st_size, 0)
            self.assertGreater(titles.stat().st_size, 0)
            self.assertEqual(plt.get_fignums(), [])
