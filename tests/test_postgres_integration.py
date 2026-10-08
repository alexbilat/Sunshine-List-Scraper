"""Opt-in real PostgreSQL checks; use a dedicated development/test database.

Set SUNSHINE_TEST_DATABASE_URL to enable. Each test owns a randomly named schema
and removes only that schema. These checks never download Sunshine List data.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from sunshine_scraper.client import CsvDownload
from sunshine_scraper.storage.migrations import (MigrationError, baseline,
                                                 ensure_schema_current, load_migrations,
                                                 migrate)
from sunshine_scraper.storage.models import Disclosure
from sunshine_scraper.storage.repository import PostgresSalaryRepository
from sunshine_scraper.storage.writer import PostgresDisclosureWriter, SYNC_LOCK_ID
from sunshine_scraper.sync import run_sync

MIGRATIONS = Path(__file__).resolve().parents[1] / 'migrations'


def disclosure(first='Alex', salary_cents=12345678, year=2024, title='Developer'):
    return Disclosure(first, 'Example', title, 'Hospital', year, salary_cents)


@unittest.skipUnless(os.environ.get('SUNSHINE_TEST_DATABASE_URL'),
                     'requires an explicit PostgreSQL test database')
class PostgresTestCase(unittest.TestCase):
    """Connect in autocommit mode inside a fresh, migrated, private schema."""

    migrate_schema = True

    def setUp(self):
        import psycopg
        self.psycopg = psycopg
        self.connection = self.connect()
        self.schema = self.create_schema(self.connection)
        if self.migrate_schema:
            migrate(self.connection)
        self.writer = PostgresDisclosureWriter(self.connection)
        self.reader = PostgresSalaryRepository(self.connection)

    def connect(self):
        connection = self.psycopg.connect(os.environ['SUNSHINE_TEST_DATABASE_URL'],
                                          autocommit=True, connect_timeout=10)
        self.addCleanup(connection.close)
        return connection

    def create_schema(self, connection):
        from psycopg import sql
        schema = sql.Identifier('sunshine_test_' + uuid4().hex)
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(schema))
        self.addCleanup(self.drop_schema, schema)
        connection.execute(sql.SQL('SET search_path TO {}').format(schema))
        return schema

    def drop_schema(self, schema):
        from psycopg import sql
        # Harmless when idle; ends a transaction a failed test may have left open.
        self.connection.execute('ROLLBACK')
        self.connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(schema))

    def count(self, table):
        from psycopg import sql
        return self.connection.execute(
            sql.SQL('SELECT count(*) FROM {}').format(sql.Identifier(table))).fetchone()[0]

    def load(self, resource_id, disclosures):
        """Load one dataset the way the sync does: inside one transaction."""
        self.writer.register_source(resource_id, f'https://example.test/{resource_id}', 'csv')
        with self.connection.transaction():
            return self.writer.load_disclosures(resource_id, disclosures)


class MigrationTests(PostgresTestCase):
    def test_migrate_is_recorded_and_idempotent(self):
        self.assertEqual(migrate(self.connection), [])
        self.assertEqual(self.count('schema_migrations'), len(load_migrations()))
        ensure_schema_current(self.connection)

    def test_failing_migration_leaves_no_trace(self):
        with tempfile.TemporaryDirectory() as directory:
            for path in MIGRATIONS.glob('*.sql'):
                shutil.copy(path, directory)
            Path(directory, '999_broken.sql').write_text(
                'CREATE TABLE half_done (id INTEGER);\nSELECT 1 / 0;\n', encoding='utf-8')
            with self.assertRaises(self.psycopg.errors.DivisionByZero):
                migrate(self.connection, directory)
            self.assertIsNone(self.connection.execute(
                "SELECT to_regclass('half_done')").fetchone()[0])
            self.assertIsNone(self.connection.execute(
                "SELECT version FROM schema_migrations WHERE version = '999'").fetchone())
            with self.assertRaises(MigrationError):
                ensure_schema_current(self.connection, directory)


class BaselineTests(PostgresTestCase):
    migrate_schema = False

    def test_hand_applied_schema_can_be_baselined_then_migrated(self):
        with self.assertRaises(MigrationError):
            baseline(self.connection, '001')  # Nothing exists yet: refuse.
        first = load_migrations()[0]
        self.connection.execute(first.sql)  # As if applied with psql (own BEGIN/COMMIT).
        self.assertEqual(baseline(self.connection, '001'), [first.filename])
        applied = migrate(self.connection)
        self.assertEqual(applied, [m.filename for m in load_migrations()[1:]])


class ConstraintTests(PostgresTestCase):
    def test_foreign_keys_and_money_constraints(self):
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            self.connection.execute(
                "INSERT INTO disclosure_sources (disclosure_id, resource_id) VALUES (999, 'missing')")
        self.load('a', [disclosure(salary_cents=100)])
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.connection.execute('UPDATE salary_records SET salary_cents = -1')


class WriterTests(PostgresTestCase):
    def test_reloading_the_same_dataset_refreshes_instead_of_duplicating(self):
        rows = [disclosure(), disclosure('Sam')]
        first = self.load('a', rows)
        self.assertEqual((first.inserted, first.refreshed), (2, 0))
        second = self.load('a', rows)
        self.assertEqual((second.inserted, second.refreshed), (0, 2))
        self.assertEqual(self.count('salary_records'), 2)
        self.assertEqual(self.count('disclosure_sources'), 2)
        updated = self.connection.execute(
            'SELECT count(*) FROM salary_records WHERE updated_at IS NOT NULL').fetchone()[0]
        self.assertEqual(updated, 2)

    def test_same_contents_take_the_newest_display_spelling(self):
        self.load('a', [disclosure('alex')])
        self.load('b', [disclosure('Alex')])
        self.assertEqual(self.connection.execute(
            'SELECT first_name FROM salary_records').fetchall(), [('Alex',)])

    def test_a_changed_salary_is_a_new_entry_and_the_old_one_stays(self):
        self.load('a', [disclosure(salary_cents=100)])
        self.load('b', [disclosure(salary_cents=200)])
        self.assertEqual(self.count('salary_records'), 2)

    def test_duplicates_inside_one_file_are_merged(self):
        counts = self.load('a', [disclosure('alex'), disclosure('ALEX')])
        self.assertEqual((counts.inserted, counts.refreshed), (1, 0))
        self.assertEqual(self.connection.execute(
            'SELECT first_name FROM salary_records').fetchone()[0], 'ALEX')

    def test_one_disclosure_keeps_every_source(self):
        self.load('main', [disclosure()])
        self.load('addendum', [disclosure()])
        self.assertEqual(self.count('salary_records'), 1)
        self.assertEqual(self.count('disclosure_sources'), 2)

    def test_failure_rolls_back_the_whole_dataset(self):
        self.writer.register_source('a', 'https://example.test/a', 'csv')
        with self.assertRaises(RuntimeError):
            with self.connection.transaction():
                self.writer.load_disclosures('a', [disclosure()])
                raise RuntimeError('simulated crash after writing')
        self.assertEqual(self.count('salary_records'), 0)
        self.assertEqual(self.count('disclosure_sources'), 0)


class ReadTests(PostgresTestCase):
    def test_export_order_format_uuid_and_aggregates(self):
        self.load('first', [disclosure('Alex', 10000000, 2023, title='')])
        self.load('second', [disclosure('Alex', 10000000, 2023, title=''),
                             disclosure('Sam', 20000005, 2024)])
        with self.connection.transaction():
            rows = list(self.reader.iter_export_records(batch_size=1))
        self.assertEqual([row['Salary'] for row in rows], ['200000.05', '100000.00'])
        self.assertEqual(rows[0]['Name'], 'Sam Example')
        # UUID is the dataset where the disclosure was first seen.
        self.assertEqual(rows[1]['UUID'], 'first')
        summary = {item.year: item for item in self.reader.yearly_summary()}
        self.assertEqual((summary[2024].people, summary[2024].average_cents), (1, 20000005))
        titles = self.reader.top_job_titles(10)
        self.assertEqual([(t.job_title, t.appearances) for t in titles], [('Developer', 1)])
        self.assertEqual(self.reader.get_top_salaries(2024, 1)[0].salary_cents, 20000005)


class SyncTests(PostgresTestCase):
    def run_sync_with(self, csv_download):
        link = 'https://www.ontario.ca/artifacts/2025/Compendium/csv-id/data.csv'
        with patch('sunshine_scraper.sync.discover_resource_links', return_value=[link]), \
                patch('sunshine_scraper.sync.fetch_csv_download', return_value=csv_download):
            return run_sync(self.connection, 'page', 'api')

    def test_sync_loads_then_skips_an_unchanged_source(self):
        row = {'First Name': 'Alex', 'Last Name': 'Example', 'Employer': 'Hospital',
               'Job Title': 'Developer', 'Salary': '$1,000.00', 'Year': '2025'}
        first = self.run_sync_with(CsvDownload([row], '"e1"', 'Mon', 'a' * 64))
        self.assertEqual((first.status, first.loaded), ('succeeded', ['csv-id']))
        second = self.run_sync_with(None)  # The server answers 304 Not Modified.
        self.assertEqual(second.unchanged, ['csv-id'])
        runs = self.connection.execute(
            'SELECT status, resources_loaded, resources_unchanged FROM sync_runs ORDER BY id').fetchall()
        self.assertEqual(runs, [('succeeded', 1, 0), ('succeeded', 0, 1)])
        self.assertEqual(self.connection.execute(
            'SELECT etag FROM source_resources').fetchone()[0], '"e1"')

    def test_overlapping_sync_returns_immediately(self):
        """While another session holds the lock, a sync returns at once."""
        other = self.connect()
        other.execute('SELECT pg_advisory_lock(%s)', (SYNC_LOCK_ID,))
        try:
            with self.assertLogs('sunshine_scraper.sync', level='WARNING'):
                result = self.run_sync_with(None)
            self.assertEqual(result.status, 'locked')
        finally:
            other.execute('SELECT pg_advisory_unlock(%s)', (SYNC_LOCK_ID,))
        self.assertEqual(self.count('sync_runs'), 0)


if __name__ == '__main__':
    unittest.main()
