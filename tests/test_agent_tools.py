"""Chat agent tools: argument checks offline, real queries against the test database."""
import unittest

from sunshine_scraper.agent import tools
from sunshine_scraper.storage.models import Disclosure

from test_postgres_integration import PostgresTestCase


class ToolDefinitionTests(unittest.TestCase):
    def test_every_definition_has_a_function(self):
        names = [tool['function']['name'] for tool in tools.TOOLS]
        self.assertEqual(sorted(names), sorted(tools.FUNCTIONS))

    def test_bad_arguments_raise_before_any_query(self):
        # None as the connection: a query attempt would raise AttributeError instead.
        with self.assertRaises(ValueError):
            tools.top_earners(None, year='2024')
        with self.assertRaises(ValueError):
            tools.top_earners(None, year=True)
        with self.assertRaises(ValueError):
            tools.search_by_name(None, last_name='   ')
        with self.assertRaises(ValueError):
            tools.find_employers(None, text=None)

    def test_like_pattern_escapes_wildcards(self):
        self.assertEqual(tools._like_pattern('100%_a\\b'), '%100\\%\\_a\\\\b%')


class ToolQueryTests(PostgresTestCase):
    def setUp(self):
        super().setUp()
        self.load('r1', [
            Disclosure('Alex', 'Example', 'Professor', 'University of Waterloo', 2024, 30000000),
            Disclosure('Sam', 'Example', 'Dean', 'University of Waterloo', 2024, 40000000),
            Disclosure('Alex', 'Example', 'Professor', 'University of Waterloo', 2023, 29000000),
            Disclosure('Jo', 'Other', 'Nurse', '100% Hospital', 2024, 50000000),
        ])

    def test_top_earners_filters_by_employer_and_clamps_n(self):
        rows = tools.top_earners(self.connection, 2024, employer='waterloo', n=1000)
        self.assertEqual([row['first_name'] for row in rows], ['Sam', 'Alex'])
        self.assertEqual(rows[0]['salary'], '$400000.00')

    def test_top_earners_treats_percent_literally(self):
        rows = tools.top_earners(self.connection, 2024, employer='100%')
        self.assertEqual([row['first_name'] for row in rows], ['Jo'])

    def test_search_by_name_groups_years(self):
        rows = tools.search_by_name(self.connection, 'EXAMPLE', 'alex')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]['first_year'], rows[0]['last_year']), (2023, 2024))

    def test_salary_history_newest_first(self):
        rows = tools.salary_history(self.connection, 'Alex', 'Example')
        self.assertEqual([row['year'] for row in rows], [2024, 2023])

    def test_find_employers_counts(self):
        rows = tools.find_employers(self.connection, 'waterloo')
        self.assertEqual(rows[0]['employer'], 'University of Waterloo')
        self.assertEqual(rows[0]['disclosures'], 3)


if __name__ == '__main__':
    unittest.main()
