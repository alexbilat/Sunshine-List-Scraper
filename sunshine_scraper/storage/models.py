"""Database-ready disclosures: exact money and repeatable content identity."""
from dataclasses import dataclass
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext
from hashlib import sha256
import json

from ..processing import get_record_field, normalize_field_name, normalize_text

MAX_BIGINT = 2**63 - 1


def salary_to_cents(value):
    """Parse source money without floating-point rounding or silent truncation."""
    # A float may already have lost information. Persist from the raw source row.
    if isinstance(value, float):
        raise ValueError("database salary must come from exact source text, not a float")
    text = normalize_text(str(value) if isinstance(value, Decimal) else value)
    text = text.replace('$', '').replace(',', '')
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise ValueError("invalid salary") from error
    if not amount.is_finite() or amount < 0:
        raise ValueError("salary must be finite and nonnegative")
    if amount > Decimal(MAX_BIGINT) / 100:
        raise ValueError("salary exceeds PostgreSQL BIGINT cents capacity")
    # Enough precision for all input digits; multiplying by 100 must be exact.
    with localcontext() as context:
        context.prec = max(28, len(amount.as_tuple().digits) + 2)
        context.traps[Inexact] = True
        try:
            cents = amount * 100
        except DecimalException as error:
            raise ValueError("salary cannot be represented as exact cents") from error
        if cents != cents.to_integral_value():
            raise ValueError("salary must have no fractional cents")
    return int(cents)


def format_cents(cents):
    """Return exact dollars with two decimals, e.g. 10000000 -> '100000.00'.

    Integer arithmetic avoids both float rounding and Decimal's exponent
    notation (Decimal(10000000) / 100 displays as '1E+5').
    """
    if type(cents) is not int or cents < 0:
        raise ValueError("cents must be a nonnegative integer")
    return f'{cents // 100}.{cents % 100:02d}'


@dataclass(frozen=True)
class Disclosure:
    """One observed disclosure, not a stable employee identity.

    Source identity is stored separately through the provenance relationship.
    Frozen values prevent accidental edits between hashing and insertion.
    """

    first_name: str
    last_name: str
    job_title: str
    employer: str
    year: int
    salary_cents: int

    def __post_init__(self):
        for field in ('first_name', 'last_name', 'job_title', 'employer'):
            value = getattr(self, field)
            if not isinstance(value, str) or value != normalize_text(value):
                raise ValueError(f"{field} must be normalized text")
            if field != 'job_title' and not value:
                raise ValueError(f"{field} is required")
        if type(self.year) is not int or not 0 <= self.year <= 9999:
            raise ValueError("year must represent a four-digit source year")
        if type(self.salary_cents) is not int or not 0 <= self.salary_cents <= MAX_BIGINT:
            raise ValueError("salary_cents must be a nonnegative PostgreSQL BIGINT")

    @classmethod
    def from_source_row(cls, row):
        """Adapt a raw CKAN/CSV row using the scraper's shared alias rules.

        The existing export uses floats and combines names. Read raw rows here
        so neither exact cents nor first/last-name boundaries are lost.
        """
        if not isinstance(row, dict):
            raise ValueError("row is not an object")
        fields = {normalize_field_name(key): value for key, value in row.items()}
        year = normalize_text(get_record_field(fields, 'year'))
        if len(year) != 4 or not year.isascii() or not year.isdigit():
            raise ValueError("missing or invalid four-digit year")
        return cls(
            first_name=normalize_text(get_record_field(fields, 'first_name')),
            last_name=normalize_text(get_record_field(fields, 'last_name')),
            job_title=normalize_text(get_record_field(fields, 'job_title')),
            employer=normalize_text(get_record_field(fields, 'employer')),
            year=int(year),
            salary_cents=salary_to_cents(get_record_field(fields, 'salary')),
        )

    @property
    def content_key(self):
        """SHA-256 fingerprint of disclosure contents, excluding its source.

        Lowercasing follows the existing within-run duplicate policy. A version
        tag and JSON array make the encoding explicit and unambiguous. This is
        a practical content fingerprint, not a guaranteed unique person ID.
        """
        values = ['disclosure-v1', self.first_name.lower(), self.last_name.lower(),
                  self.job_title.lower(), self.employer.lower(), self.year,
                  self.salary_cents]
        encoded = json.dumps(values, ensure_ascii=False, separators=(',', ':'))
        return sha256(encoded.encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class SalaryResult:
    """A small read result that a future API can turn into a response."""

    first_name: str
    last_name: str
    employer: str
    salary_cents: int

    @property
    def name(self):
        return f'{self.first_name} {self.last_name}'


@dataclass(frozen=True)
class YearSummary:
    """Aggregates for one year; average_cents is exact (Decimal) or None."""

    year: int
    people: int
    average_cents: object

    @property
    def average_dollars(self):
        """Average salary in dollars as a float, for display and charts only."""
        return float(self.average_cents) / 100 if self.average_cents is not None else 0.0


@dataclass(frozen=True)
class TitleCount:
    job_title: str
    appearances: int
