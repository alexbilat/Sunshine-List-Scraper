"""Regression checks for irregular source rows and column headers.

Rows are validated by Disclosure.from_source_row, the only path into the
database. These cases were first written for the retired in-memory cleaner;
they must keep passing so validation never becomes weaker.
"""
import unittest

from sunshine_scraper.storage.models import Disclosure
from sunshine_scraper.sync import validate_rows


def person(**changes):
    """Build a fresh valid row, overriding selected fields for a specific scenario."""
    row = {'First Name': ' Alex\xa0 ', 'Last Name': 'Bilat',
           'Job Title': 'Developer', 'Employer': 'Ontario',
           'Calendar Year': '2024', 'Salary Paid': '$123,456.00'}
    # Tests pass **{...} when field names contain spaces.
    row.update(changes)
    return row


class ValidationTests(unittest.TestCase):
    def test_whitespace_before_bom_does_not_hide_required_column(self):
        disclosure = Disclosure.from_source_row({
            ' \t﻿First_Name ': 'Alex',
            'Last Name': 'Example',
            'Employer': 'Ontario',
            'Job Title': 'Developer',
            'Salary Paid': '120000',
            'Calendar Year': '2024',
        })
        self.assertEqual((disclosure.first_name, disclosure.last_name), ('Alex', 'Example'))
        self.assertEqual(disclosure.salary_cents, 12000000)

    def test_invalid_rows_are_counted_not_stored(self):
        """Bad rows are rejected one at a time; the valid row still passes."""
        # Cover wrong row types, missing identity/year fields, and unusable salaries.
        bad = [None, [], 'row', {}, person(**{'First Name': None}),
               person(**{'Employer': {}}), person(**{'Salary Paid': 'NaN'}),
               person(**{'Salary Paid': 'inf'}), person(**{'Salary Paid': '-1'}),
               person(**{'Salary Paid': None}), person(**{'Calendar Year': 'unknown'})]
        with self.assertLogs('sunshine_scraper.sync', level='WARNING'):
            disclosures, rejected = validate_rows([person(), *bad], 'a')
        self.assertEqual(rejected, len(bad))
        self.assertEqual(len(disclosures), 1)
        self.assertEqual(disclosures[0].first_name, 'Alex')
        self.assertEqual(disclosures[0].salary_cents, 12345600)

    def test_fallback_fields_and_optional_title(self):
        """Alternate year/salary fields work, and an absent job title remains optional."""
        disclosure = Disclosure.from_source_row(person(**{
            'Calendar Year': None, 'Year': 2023, 'Salary Paid': None,
            'Salary': '150000', 'Job Title': None}))
        self.assertEqual(disclosure.salary_cents, 15000000)
        self.assertEqual(disclosure.year, 2023)
        self.assertEqual(disclosure.job_title, '')

    def test_historical_column_names_keep_names_titles_and_years(self):
        """Regression examples for the main datasets previously rejected."""
        examples = [
            {'First Name': 'Alex', 'Surname': 'Bilat', 'Employer': 'Ontario',
             'Position': 'Developer', 'Salary Paid': '$123,456.00', 'Calendar Year': '2001'},
            {'First Name': 'Alex', 'Last name': 'Bilat', 'Employer': 'Ontario',
             'Job title': 'Developer', 'Salary Paid': '$123,456.00', 'Calendar year': '2014'},
            {'First name': 'Alex', 'Last name': 'Bilat', 'Employer': 'Ontario',
             'Job title': 'Developer', 'Salary': '123456', 'Year': '2020'},
            {' FIRST\xa0NAME ': 'Alex', '﻿LAST_NAME': 'Bilat', ' employer ': 'Ontario',
             'JOB_TITLE': 'Developer', 'SALARY_PAID': '123456', 'calendar_year': '2025'},
            # The 2023 main list's header is "JobTitle"; it once left ~300,000 titles blank.
            {'First Name': 'Alex', 'Last Name': 'Bilat', 'Employer': 'Ontario',
             'JobTitle': 'Developer', 'Salary': '123456', 'Year': '2023'},
        ]
        for example, expected_year in zip(examples, (2001, 2014, 2020, 2025, 2023)):
            with self.subTest(year=expected_year):
                disclosure = Disclosure.from_source_row(example)
                self.assertEqual((disclosure.first_name, disclosure.last_name), ('Alex', 'Bilat'))
                self.assertEqual(disclosure.job_title, 'Developer')
                self.assertEqual(disclosure.year, expected_year)
                self.assertEqual(disclosure.salary_cents, 12345600)

    def test_aliases_do_not_create_duplicate_disclosures(self):
        """The same disclosure under other labels has the same database key."""
        alternative = {'first name': 'Alex', 'surname': 'Bilat', 'employer': 'Ontario',
                       'position': 'Developer', 'salary': '123456', 'year': '2024'}
        self.assertEqual(Disclosure.from_source_row(person()).content_key,
                         Disclosure.from_source_row(alternative).content_key)

    def test_blank_preferred_columns_use_populated_aliases(self):
        disclosure = Disclosure.from_source_row(person(**{
            'Last Name': ' ', 'Surname': 'Bilat', 'Job Title': '', 'Position': 'Developer',
            'Calendar Year': '\xa0', 'Year': '2024', 'Salary Paid': '', 'Salary': '123456'}))
        self.assertEqual(disclosure.last_name, 'Bilat')
        self.assertEqual(disclosure.job_title, 'Developer')
        self.assertEqual(disclosure.year, 2024)
        self.assertEqual(disclosure.salary_cents, 12345600)

    def test_missing_titles_are_accepted_and_reported(self):
        with self.assertLogs('sunshine_scraper.sync', level='WARNING') as logs:
            disclosures, rejected = validate_rows([person(**{'Job Title': ''})], 'a')
        self.assertEqual((len(disclosures), rejected), (1, 0))
        self.assertIn('1 accepted rows have no job title', ' '.join(logs.output))


if __name__ == '__main__':
    unittest.main()
