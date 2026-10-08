"""Regression checks for irregular source column headers."""
import unittest

from sunshine_scraper.processing import clean_record


class ProcessingTests(unittest.TestCase):
    def test_whitespace_before_bom_does_not_hide_required_column(self):
        record, _ = clean_record({
            ' \t\ufeffFirst_Name ': 'Alex',
            'Last Name': 'Example',
            'Employer': 'Ontario',
            'Job Title': 'Developer',
            'Salary Paid': '120000',
            'Calendar Year': '2024',
        }, 'source')
        self.assertEqual(record['Name'], 'Alex Example')
        self.assertEqual(record['Salary'], 120000)
