"""Opt-in real PostgreSQL checks; use a dedicated development/test database.

Set SUNSHINE_TEST_DATABASE_URL to enable. Each test owns a randomly named schema
and removes only that schema. These checks never download Sunshine List data.
"""
import os
from pathlib import Path
import unittest
from uuid import uuid4

from sunshine_scraper.storage.models import Disclosure
from sunshine_scraper.storage.repository import PostgresSalaryRepository


@unittest.skipUnless(os.environ.get('SUNSHINE_TEST_DATABASE_URL'),
                     'requires an explicit PostgreSQL test database')
class PostgresIntegrationTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        self.psycopg = psycopg
        self.connection = psycopg.connect(os.environ['SUNSHINE_TEST_DATABASE_URL'],
                                         autocommit=True, connect_timeout=10)
        self.addCleanup(self.connection.close)
        self.schema = sql.Identifier('sunshine_test_' + uuid4().hex)
        self.connection.execute(sql.SQL('CREATE SCHEMA {}').format(self.schema))
        self.addCleanup(self.drop_schema)
        self.connection.execute(sql.SQL('SET search_path TO {}').format(self.schema))
        migration = Path(__file__).resolve().parents[1] / 'migrations' / '001_disclosure_foundation.sql'
        self.connection.execute(migration.read_text(encoding='utf-8'))

    def drop_schema(self):
        from psycopg import sql
        # A failed explicit migration transaction must be rolled back first.
        self.connection.execute('ROLLBACK')
        self.connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(self.schema))

    def insert_disclosure(self, salary):
        disclosure = Disclosure('Alex', 'Example', 'Developer', 'Hospital', 2024, salary)
        return self.connection.execute(
            '''INSERT INTO salary_records
               (content_key, first_name, last_name, job_title, employer, year, salary_cents)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id''',
            (disclosure.content_key, disclosure.first_name, disclosure.last_name,
             disclosure.job_title, disclosure.employer, disclosure.year,
             disclosure.salary_cents)).fetchone()[0]

    def test_unique_content_provenance_and_read_query(self):
        identifier = self.insert_disclosure(12345678)
        self.insert_disclosure(20000000)
        with self.assertRaises(self.psycopg.errors.UniqueViolation):
            self.insert_disclosure(12345678)
        for resource in ('main', 'other'):
            self.connection.execute(
                'INSERT INTO source_resources (resource_id, source_url, source_kind) '
                'VALUES (%s, %s, %s)', (resource, 'https://example.test/' + resource, 'csv'))
            self.connection.execute(
                'INSERT INTO disclosure_sources (disclosure_id, resource_id) VALUES (%s, %s)',
                (identifier, resource))
        count = self.connection.execute('SELECT COUNT(*) FROM disclosure_sources').fetchone()[0]
        self.assertEqual(count, 2)
        rows = PostgresSalaryRepository(self.connection).get_top_salaries(2024, 1)
        self.assertEqual(rows[0].salary_cents, 20000000)
        self.assertEqual(PostgresSalaryRepository(self.connection).get_top_salaries(2023), [])

    def test_foreign_keys_and_money_constraints(self):
        with self.assertRaises(self.psycopg.errors.ForeignKeyViolation):
            self.connection.execute(
                "INSERT INTO disclosure_sources (disclosure_id, resource_id) VALUES (999, 'missing')")
        identifier = self.insert_disclosure(100)
        with self.assertRaises(self.psycopg.errors.CheckViolation):
            self.connection.execute('UPDATE salary_records SET salary_cents = -1 WHERE id = %s',
                                    (identifier,))


if __name__ == '__main__':
    unittest.main()
