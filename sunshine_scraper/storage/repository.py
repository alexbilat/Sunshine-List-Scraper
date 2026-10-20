"""SQL reads behind the SalaryReader interface that the API and static site use."""
from typing import Iterator, Protocol

from .models import PersonRow, SalaryResult, TitleCount, YearSummary, format_cents

# The most rows one ranked list may return. The API validates against it, the
# static site stores exactly this many, and the page's "Top N" options must
# not exceed it, so they all read it from here instead of repeating 100.
MAX_LIMIT = 100


class SalaryReader(Protocol):
    """Describe the operations an API needs without coupling it to Psycopg."""

    def get_top_salaries(self, year: int, limit: int = 10) -> list[SalaryResult]:
        ...

    def yearly_summary(self) -> list[YearSummary]:
        ...

    def top_job_titles(self, limit: int = 10) -> list[TitleCount]:
        ...

    def person_history(self, first_name: str, last_name: str) -> list[PersonRow]:
        ...

    def iter_people(self, batch_size: int = 10000) -> Iterator[tuple[str, str, PersonRow]]:
        ...


class PostgresSalaryRepository:
    """Use a caller-owned connection; never create schema or commit internally.

    Passing in the connection lets a caller group several reads into one
    transaction, so an export, its summary, and its charts see the same data.
    """

    def __init__(self, connection):
        self.connection = connection

    def get_top_salaries(self, year: int, limit: int = 10) -> list[SalaryResult]:
        if type(year) is not int or not 0 <= year <= 9999:
            raise ValueError("year must be an integer between 0 and 9999")
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
        # Bind input values separately; the SQL structure is fixed.
        rows = self.connection.execute(
            """
            SELECT first_name, last_name, employer, salary_cents
            FROM salary_records
            WHERE year = %s
            ORDER BY salary_cents DESC, id ASC
            LIMIT %s
            """,
            (year, limit),
        ).fetchall()
        return [SalaryResult(*row) for row in rows]

    def count_records(self) -> int:
        return self.connection.execute('SELECT count(*) FROM salary_records').fetchone()[0]

    def yearly_summary(self) -> list[YearSummary]:
        """People and average salary per year, oldest first, computed by the server."""
        rows = self.connection.execute(
            """
            SELECT year, count(*), avg(salary_cents)
            FROM salary_records
            GROUP BY year
            ORDER BY year
            """).fetchall()
        return [YearSummary(*row) for row in rows]

    def top_job_titles(self, limit: int = 10) -> list[TitleCount]:
        if type(limit) is not int or not 1 <= limit <= MAX_LIMIT:
            raise ValueError(f"limit must be an integer between 1 and {MAX_LIMIT}")
        rows = self.connection.execute(
            """
            SELECT job_title, count(*) AS appearances
            FROM salary_records
            WHERE job_title <> ''
            GROUP BY job_title
            ORDER BY appearances DESC, job_title
            LIMIT %s
            """,
            (limit,)).fetchall()
        return [TitleCount(*row) for row in rows]

    def person_history(self, first_name: str, last_name: str) -> list[PersonRow]:
        """Every disclosure for one exact full name, newest year first.

        Matching uses fold_name (migration 003): case and accents are ignored,
        but the whole name must match, so "Smi" finds no "Smith".
        """
        first_name, last_name = first_name.strip(), last_name.strip()
        if not first_name or not last_name:
            raise ValueError('first_name and last_name must not be blank')
        rows = self.connection.execute(
            """
            SELECT first_name, last_name, job_title, employer, year, salary_cents
            FROM salary_records
            WHERE fold_name(last_name) = fold_name(%s)
              AND fold_name(first_name) = fold_name(%s)
            ORDER BY year DESC, salary_cents DESC, id
            """,
            (last_name, first_name),
        ).fetchall()
        return [PersonRow(*row) for row in rows]

    def iter_people(self, batch_size: int = 10000) -> Iterator[tuple[str, str, PersonRow]]:
        """Yield (folded last, folded first, row) sorted by those keys, for the static site.

        The database does the folding so Python never re-implements it. Sorted
        output lets the caller write one file per key group in constant memory.
        Server-side cursor, so it needs an open transaction.

        Sorted by the static site's shard key first (see shard_key in
        static_site.py): sorting by name alone can interleave "o'brien" and
        "obrien" between other "o..." names, and a shard must arrive in one run.
        """
        with self.connection.cursor(name='iter_people') as cursor:
            cursor.itersize = batch_size
            cursor.execute(
                """
                SELECT fold_name(last_name) AS last_key, fold_name(first_name) AS first_key,
                       first_name, last_name, job_title, employer, year, salary_cents
                FROM salary_records
                ORDER BY left(regexp_replace(fold_name(last_name), '[^a-z]', '', 'g'), 2),
                         last_key, first_key, year DESC, salary_cents DESC, id
                """)
            for last_key, first_key, *fields in cursor:
                yield last_key, first_key, PersonRow(*fields)

    def iter_export_records(self, batch_size: int = 10000) -> Iterator[dict]:
        """Yield TSV rows, highest salary first, without loading all into memory.

        A named (server-side) cursor keeps the result on the server and sends
        batch_size rows at a time. It requires an open transaction.
        UUID is the dataset where a disclosure was first seen, so a row keeps
        the same UUID however many later datasets repeat it.
        """
        with self.connection.cursor(name='export_records') as cursor:
            cursor.itersize = batch_size
            cursor.execute(
                """
                SELECT records.first_name, records.last_name, records.salary_cents,
                       records.job_title, records.employer, records.year, first_source.resource_id
                FROM salary_records AS records
                LEFT JOIN (
                    SELECT DISTINCT ON (disclosure_id) disclosure_id, resource_id
                    FROM disclosure_sources
                    ORDER BY disclosure_id, first_seen_at, resource_id
                ) AS first_source ON first_source.disclosure_id = records.id
                ORDER BY records.salary_cents DESC, records.id
                """)
            for first_name, last_name, cents, title, employer, year, resource_id in cursor:
                yield {
                    'Name': f'{first_name} {last_name}',
                    'Salary': format_cents(cents),
                    'Job Title': title,
                    'Employer': employer,
                    'Year': year,
                    'UUID': resource_id or '',
                }
