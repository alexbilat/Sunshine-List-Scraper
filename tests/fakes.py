"""Test doubles shared by the API and static site tests.

Not named test_*.py, so unittest discovery imports it only when a test does.
"""
from decimal import Decimal

from sunshine_scraper.storage.models import SalaryResult, TitleCount, YearSummary

DEFAULT_YEARS = [YearSummary(2023, 0, None),  # nobody listed: no salaries file, no 422
                 YearSummary(2024, 2, Decimal('11172839.5000000000'))]
DEFAULT_SALARIES = [SalaryResult('Alex', 'Example', 'Example Hospital', 12345678),
                    SalaryResult('Sam', 'Sample', 'Example College', 10000000)]
DEFAULT_TITLES = [TitleCount('Professor', 3), TitleCount('Nurse', 2)]


class FakeSalaryReader:
    """Implements SalaryReader in memory and records what callers asked for.

    Each list can be replaced per test, e.g. FakeSalaryReader(years=[]) for an
    empty database. calls holds one tuple per method call, in order.
    """

    def __init__(self, years=None, salaries=None, titles=None):
        self.years = DEFAULT_YEARS if years is None else years
        self.salaries = DEFAULT_SALARIES if salaries is None else salaries
        self.titles = DEFAULT_TITLES if titles is None else titles
        self.calls = []

    def get_top_salaries(self, year, limit=10):
        self.calls.append(('get_top_salaries', year, limit))
        return self.salaries

    def yearly_summary(self):
        self.calls.append(('yearly_summary',))
        return self.years

    def top_job_titles(self, limit=10):
        self.calls.append(('top_job_titles', limit))
        return self.titles
