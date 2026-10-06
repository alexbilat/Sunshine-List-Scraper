"""Check the query practice's boundaries without running a scrape.

Temporary SQLite files exercise the actual database behaviour. None of these
checks downloads records or writes a database into the project directory.
"""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sunshine_scraper.database import get_top_salaries


class DatabaseQueryTests(unittest.TestCase):
    """Protect safe imports, missing-file handling, query results, and cleanup."""

    def test_import_does_not_connect_or_print(self):
        # Load a fresh module object so the test really executes top-level code.
        module_path = Path(__file__).resolve().parents[1] / 'sunshine_scraper' / 'database.py'
        spec = importlib.util.spec_from_file_location('database_import_check', module_path)
        module = importlib.util.module_from_spec(spec)
        with patch('sqlite3.connect') as connect, patch('builtins.print') as output:
            spec.loader.exec_module(module)
        connect.assert_not_called()
        output.assert_not_called()

    def test_missing_database_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / 'missing.db'
            with self.assertRaises(sqlite3.OperationalError):
                get_top_salaries(database_path)
            self.assertFalse(database_path.exists())

    def test_filters_sorts_limits_and_preserves_data(self):
        with tempfile.TemporaryDirectory() as directory:
            # The space also exercises URI path encoding on Windows.
            database_path = Path(directory) / 'sample salaries.db'
            connection = sqlite3.connect(database_path)
            try:
                with connection:
                    connection.execute('CREATE TABLE salary_records '
                                       '(name TEXT, employer TEXT, salary_cents INTEGER, year INTEGER)')
                    connection.executemany('INSERT INTO salary_records VALUES (?, ?, ?, ?)', [
                        ('Lower', 'A', 12000000, 2024),
                        ('Higher', 'B', 18000000, 2024),
                        ('Other year', 'C', 25000000, 2023),
                    ])
            finally:
                connection.close()
            previous_contents = database_path.read_bytes()
            self.assertEqual(get_top_salaries(database_path, year=2024, limit=1),
                             [('Higher', 'B', 18000000)])
            self.assertEqual(get_top_salaries(database_path, year=2022), [])
            self.assertEqual(database_path.read_bytes(), previous_contents)

    def test_query_failure_closes_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = Path(directory) / 'empty.db'
            sqlite3.connect(database_path).close()
            # Retain the actual read-only connection to verify it was closed.
            connection = sqlite3.connect(database_path.resolve().as_uri() + '?mode=ro', uri=True)
            try:
                with patch('sunshine_scraper.database.sqlite3.connect', return_value=connection):
                    with self.assertRaises(sqlite3.OperationalError):
                        get_top_salaries(database_path)
                with self.assertRaises(sqlite3.ProgrammingError):
                    connection.execute('SELECT 1')
            finally:
                connection.close()


if __name__ == '__main__':
    unittest.main()
