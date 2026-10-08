"""Database tools: python -m sunshine_scraper.storage --help.

check and top are read-only. migrate is the only command that changes the
schema; the scraper itself never migrates.
"""
import argparse
from decimal import Decimal
import logging

from .connection import (DatabaseAccessError, DatabaseConfigurationError,
                         DatabaseSettings, open_connection)
from .migrations import (MigrationError, applied_migrations, baseline, load_migrations,
                         migrate, pending_migrations)
from .repository import PostgresSalaryRepository

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description='PostgreSQL tools for the Sunshine List scraper')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='Check access to an existing PostgreSQL server')
    top = commands.add_parser('top', help='Query an already initialized and populated schema')
    top.add_argument('--year', type=int, required=True)
    top.add_argument('--limit', type=int, default=10)
    migrate_parser = commands.add_parser('migrate', help='Apply pending schema migrations')
    migrate_options = migrate_parser.add_mutually_exclusive_group()
    migrate_options.add_argument('--status', action='store_true',
                                 help='List applied and pending migrations without changes')
    migrate_options.add_argument('--baseline', metavar='VERSION',
                                 help='Record migrations up to VERSION as applied (tables made by hand)')
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        settings = DatabaseSettings.from_environment()
        if arguments.command == 'migrate':
            return run_migrate(settings, arguments)
        with open_connection(settings) as connection:
            # These tools cannot modify the database even if called with a writer role.
            connection.execute('SET TRANSACTION READ ONLY')
            if arguments.command == 'check':
                connection.execute('SELECT 1').fetchone()
                logger.info('PostgreSQL connection succeeded; schema/data were not checked')
            else:
                rows = PostgresSalaryRepository(connection).get_top_salaries(
                    arguments.year, arguments.limit)
                for row in rows:
                    dollars = Decimal(row.salary_cents) / 100
                    print(f'{row.name}\t{row.employer}\t${dollars:,.2f}')
    except (DatabaseConfigurationError, DatabaseAccessError, MigrationError, ValueError) as error:
        logger.error('%s', error)
        return 1
    return 0


def run_migrate(settings, arguments):
    # Autocommit: the runner gives each migration file its own transaction.
    with open_connection(settings, autocommit=True) as connection:
        if arguments.status:
            applied = applied_migrations(connection)
            available = load_migrations()
            pending = {migration.version for migration in
                       pending_migrations(available, applied)}
            for migration in available:
                state = 'pending' if migration.version in pending else 'applied'
                print(f'{state}	{migration.filename}')
        elif arguments.baseline:
            for filename in baseline(connection, arguments.baseline):
                logger.info('Recorded %s as applied without running it', filename)
        else:
            applied = migrate(connection)
            for filename in applied:
                logger.info('Applied %s', filename)
            if not applied:
                logger.info('Schema is already up to date')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
