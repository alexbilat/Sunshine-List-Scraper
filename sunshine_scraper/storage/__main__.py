"""Explicit read-only checks: python -m sunshine_scraper.storage --help."""
import argparse
from decimal import Decimal
import logging

from .connection import (DatabaseAccessError, DatabaseConfigurationError,
                         DatabaseSettings, open_connection)
from .repository import PostgresSalaryRepository

logger = logging.getLogger(__name__)


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only PostgreSQL foundation tools')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check', help='Check access to an existing PostgreSQL server')
    top = commands.add_parser('top', help='Query an already initialized and populated schema')
    top.add_argument('--year', type=int, required=True)
    top.add_argument('--limit', type=int, default=10)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
    try:
        settings = DatabaseSettings.from_environment()
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
    except (DatabaseConfigurationError, DatabaseAccessError, ValueError) as error:
        logger.error('%s', error)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
