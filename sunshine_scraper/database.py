"""Read-only SQLite query practice; not yet part of the scraper pipeline.

An existing salary_records table is required. This module does not create a
schema or insert data. Run explicitly with: python -m sunshine_scraper.database
"""
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)


def get_top_salaries(database_path, year=2024, limit=10):
    """Return (name, employer, salary_cents) tuples from an existing database."""
    # A file URI with mode=ro opens read-only and refuses to create a missing DB.
    # as_uri also encodes spaces and other special characters in the path.
    database_uri = Path(database_path).resolve().as_uri() + '?mode=ro'
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        # Bind values separately: SQLite handles quoting and treats them as data.
        result = connection.execute(
            """
            SELECT name, employer, salary_cents
            FROM salary_records
            WHERE year = ?
            ORDER BY salary_cents DESC
            LIMIT ?
            """,
            (year, limit),
        )
        return result.fetchall()
    finally:
        # Reading can fail too (for example, if the required table is missing).
        connection.close()


def main():
    """Query the practice file; return 1 if the file/table cannot be read."""
    logging.basicConfig(level=logging.INFO,
                        format='%(levelname)s %(name)s: %(message)s')
    try:
        # Relative to the terminal's working directory, like scraper output paths.
        rows = get_top_salaries('sunshine.db')
    except sqlite3.Error as error:
        logger.error("Database query failed: %s. This example requires an existing "
                     "sunshine.db and salary_records table; the scraper does not "
                     "create them yet.", error)
        return 1
    for row in rows:
        print(row)  # Interactive query results; salary is still in cents.
    return 0


# Importing this module only defines its functions; it performs no database I/O.
if __name__ == '__main__':
    raise SystemExit(main())
