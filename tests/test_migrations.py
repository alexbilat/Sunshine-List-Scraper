"""Offline checks for the migration runner's file and bookkeeping rules.

No server is needed: these test the pure comparison logic. Applying files to a
real database is covered by tests/test_postgres_integration.py.
"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from sunshine_scraper.storage.migrations import (Migration, MigrationError,
                                                 ensure_schema_current, load_migrations,
                                                 pending_migrations)


def write_files(directory, names):
    for name in names:
        (Path(directory) / name).write_text('SELECT 1;\n', encoding='utf-8')


class MigrationFileTests(unittest.TestCase):
    def test_repository_migrations_load_in_version_order(self):
        migrations = load_migrations()
        self.assertEqual([migration.version for migration in migrations][:2], ['001', '002'])
        for migration in migrations:
            self.assertRegex(migration.checksum, '^[0-9a-f]{64}$')
        self.assertEqual(set(migrations[0].created_tables),
                         {'source_resources', 'salary_records', 'disclosure_sources'})

    def test_bad_names_and_duplicate_versions_are_rejected(self):
        for names in (['1_short.sql'], ['001_Upper.sql'],
                      ['001_first.sql', '001_second.sql']):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as directory:
                write_files(directory, names)
                with self.assertRaises(MigrationError):
                    load_migrations(directory)

    def test_line_endings_do_not_change_the_checksum(self):
        unix = Migration('001', '001_a.sql', 'CREATE TABLE a (id int);\n')
        windows = Migration('001', '001_a.sql', 'CREATE TABLE a (id int);\r\n')
        self.assertEqual(unix.checksum, windows.checksum)

    def test_runner_supplies_the_transaction(self):
        """Hand-applied files may say BEGIN/COMMIT; the runner removes only those lines."""
        migration = Migration('001', '001_a.sql',
                              'BEGIN;\nCREATE TABLE a (id int);\nCOMMIT;\n')
        self.assertNotIn('BEGIN', migration.executable_sql)
        self.assertNotIn('COMMIT', migration.executable_sql)
        self.assertIn('CREATE TABLE a', migration.executable_sql)


class PendingTests(unittest.TestCase):
    def setUp(self):
        self.first = Migration('001', '001_a.sql', 'SELECT 1;')
        self.second = Migration('002', '002_b.sql', 'SELECT 2;')

    def test_only_unapplied_files_are_pending(self):
        available = [self.first, self.second]
        self.assertEqual(pending_migrations(available, {}), available)
        self.assertEqual(pending_migrations(available, {'001': self.first.checksum}),
                         [self.second])
        self.assertEqual(pending_migrations(available, {'001': self.first.checksum,
                                                        '002': self.second.checksum}), [])

    def test_edited_unknown_or_out_of_order_files_stop_the_runner(self):
        available = [self.first, self.second]
        for applied in ({'001': 'f' * 64},
                        {'001': self.first.checksum, '003': 'a' * 64},
                        {'002': self.second.checksum}):
            with self.subTest(applied=applied):
                with self.assertRaises(MigrationError):
                    pending_migrations(available, applied)

    def test_scraper_check_names_the_command_to_run(self):
        with patch('sunshine_scraper.storage.migrations.applied_migrations', return_value={}):
            with self.assertRaisesRegex(MigrationError, 'storage migrate'):
                ensure_schema_current(Mock())


class CommandTests(unittest.TestCase):
    def test_migrate_without_settings_fails_before_connecting(self):
        from sunshine_scraper.storage.__main__ import main
        with patch.dict('os.environ', {}, clear=True):
            with patch('sunshine_scraper.storage.__main__.open_connection') as connect:
                with self.assertLogs('sunshine_scraper.storage.__main__', level='ERROR'):
                    self.assertEqual(main(['migrate']), 1)
                connect.assert_not_called()


if __name__ == '__main__':
    unittest.main()
