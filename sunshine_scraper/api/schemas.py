"""Response shapes: the JSON contract the API promises to its clients.

These models are deliberately separate from the storage dataclasses. Storage
rows can gain or rename columns without breaking a frontend, because each
model chooses exactly which fields leave the server and what they are called.
FastAPI also reads these classes to document every response at /docs.
"""
from decimal import ROUND_HALF_UP, Decimal

from pydantic import BaseModel

from ..storage.models import PersonRow, SalaryResult, TitleCount, YearSummary, format_cents


class Health(BaseModel):
    status: str


class YearStats(BaseModel):
    """Headcount and average salary for one year (feeds the yearly chart)."""

    year: int
    people: int
    # Money is sent twice: integer cents for exact math in a client, and a
    # ready-made dollar string for display. Floats are never sent because
    # JSON numbers are often read as floats, which cannot hold every cent.
    average_salary_cents: int | None
    average_salary: str | None

    @classmethod
    def from_summary(cls, summary: YearSummary) -> 'YearStats':
        cents = round_to_cents(summary.average_cents)
        return cls(year=summary.year, people=summary.people,
                   average_salary_cents=cents,
                   average_salary=None if cents is None else format_cents(cents))


class TitleStats(BaseModel):
    """How often one job title appears across all years (feeds the title chart)."""

    job_title: str
    appearances: int

    @classmethod
    def from_count(cls, count: TitleCount) -> 'TitleStats':
        return cls(job_title=count.job_title, appearances=count.appearances)


class Salary(BaseModel):
    """One disclosure in a top-salaries table."""

    name: str
    first_name: str
    last_name: str
    employer: str
    salary_cents: int
    salary: str

    @classmethod
    def from_result(cls, result: SalaryResult) -> 'Salary':
        return cls(name=result.name, first_name=result.first_name,
                   last_name=result.last_name, employer=result.employer,
                   salary_cents=result.salary_cents,
                   salary=format_cents(result.salary_cents))


class PersonSalary(BaseModel):
    """One disclosure in a person's history (name search)."""

    name: str
    first_name: str
    last_name: str
    job_title: str
    employer: str
    year: int
    salary_cents: int
    salary: str

    @classmethod
    def from_row(cls, row: PersonRow) -> 'PersonSalary':
        return cls(name=row.name, first_name=row.first_name, last_name=row.last_name,
                   job_title=row.job_title, employer=row.employer, year=row.year,
                   salary_cents=row.salary_cents, salary=format_cents(row.salary_cents))


def round_to_cents(average_cents: Decimal | None) -> int | None:
    """Round PostgreSQL's exact average (a Decimal of cents) to whole cents.

    avg() returns a long Decimal such as 12345678.5000000000. Rounding half-up
    matches how source salaries are stored. to_integral_value ignores the
    current Decimal precision setting, so the result never depends on it.
    """
    if average_cents is None:
        return None
    return int(Decimal(average_cents).to_integral_value(rounding=ROUND_HALF_UP))
