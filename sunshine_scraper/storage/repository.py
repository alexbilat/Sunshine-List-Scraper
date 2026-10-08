"""SQL reads behind an interface that a future backend can depend on."""
from typing import Iterator, Protocol

from .models import SalaryResult, TitleCount, YearSummary, format_cents


class SalaryReader(Protocol):
    """Describe the operations an API needs without coupling it to Psycopg."""

    def get_top_salaries(self, year: int, limit: int = 10) -> list[SalaryResult]:
        ...

    def yearly_summary(self) -> list[YearSummary]:
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
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
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
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
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

    def iter_export_records(self, batch_size: int = 10000) -> Iterator[dict]:
        """Yield TSV rows, highest salary first, without loading all into memory.

        A named (server-side) cursor keeps the result on the server and sends
        batch_size rows at a time. It requires an open transaction.
        UUID is the dataset where a disclosure was first seen, matching the
        file-based scraper, which kept the first dataset processed.
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
