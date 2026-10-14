"""Regression checks for chart inputs at the reporting boundary."""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import matplotlib
matplotlib.use('Agg')
from matplotlib import pyplot as plt

from sunshine_scraper.reporting import create_charts, print_yearly_summary
from sunshine_scraper.storage.models import TitleCount, YearSummary


class ReportingTests(unittest.TestCase):
    def test_layout_failure_closes_each_chart_figure(self):
        from matplotlib.figure import Figure

        # Fail both the first chart's layout and the second chart's layout.
        # File saving is patched because the failure happens before saving.
        for layouts in ([ValueError('layout failed')],
                        [None, ValueError('layout failed')]):
            with self.subTest(chart=len(layouts)), \
                    patch.object(Figure, 'tight_layout', side_effect=layouts), \
                    patch.object(Figure, 'savefig'):
                try:
                    with self.assertRaisesRegex(ValueError, 'layout failed'):
                        create_charts([YearSummary(2024, 1, Decimal('12000000'))],
                                      [TitleCount('Developer', 1)], 'yearly.png', 'titles.png')
                    self.assertEqual(plt.get_fignums(), [])
                finally:
                    plt.close('all')

    def test_year_without_average_still_writes_charts(self):
        """A missing average (no salaries) is drawn as zero instead of failing."""
        with tempfile.TemporaryDirectory() as directory:
            yearly = Path(directory) / 'yearly.png'
            titles = Path(directory) / 'titles.png'
            create_charts([YearSummary(2023, 0, None), YearSummary(2024, 1, Decimal('12000000'))],
                          [TitleCount('Developer', 1)], yearly, titles)
            self.assertGreater(yearly.stat().st_size, 0)
            self.assertGreater(titles.stat().st_size, 0)
            self.assertEqual(plt.get_fignums(), [])

    def test_title_chart_heading_counts_the_titles_drawn(self):
        from matplotlib.axes import Axes

        with patch.object(Axes, 'set_title') as set_title, \
                patch('matplotlib.figure.Figure.savefig'):
            create_charts([YearSummary(2024, 1, Decimal('12000000'))],
                          [TitleCount('Developer', 2), TitleCount('Nurse', 1)],
                          'yearly.png', 'titles.png')
        set_title.assert_called_with('Top 2 Most Common Job Titles on the Sunshine List')
        self.assertEqual(plt.get_fignums(), [])

    def test_summary_is_logged_newest_first_in_dollars(self):
        summary = [YearSummary(2023, 2, Decimal('12345678.5000')),
                   YearSummary(2024, 1, Decimal('10000000'))]
        with self.assertLogs('sunshine_scraper.reporting', level='INFO') as logs:
            print_yearly_summary(summary)
        self.assertIn('2024: Average: 100000.00 Number of people: 1', logs.output[0])
        self.assertIn('2023: Average: 123456.79 Number of people: 2', logs.output[1])


if __name__ == '__main__':
    unittest.main()
