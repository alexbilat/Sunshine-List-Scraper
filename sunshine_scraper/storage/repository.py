"""SQL reads behind an interface that a future backend can depend on."""
from typing import Protocol

from .models import SalaryResult


class SalaryReader(Protocol):
    """Describe the operation an API needs without coupling it to Psycopg."""

    def get_top_salaries(self, year: int, limit: int = 10) -> list[SalaryResult]:
        ...


class PostgresSalaryRepository:
    """Use a caller-owned connection; never create schema or commit internally.

    Passing in the connection lets a future sync service group several SQL
    operations into one transaction. Writes are deliberately not implemented
    until duplicate, correction, and publication rules have been reviewed.
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
