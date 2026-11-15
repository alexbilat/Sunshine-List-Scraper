"""Database functions the chat model may call, plus their JSON-schema definitions.

Each tool is a plain function whose first argument is an open (read-only)
connection; the agent loop opens one per call. The remaining arguments come
from the model, so they are checked here like any other untrusted input: a
bad value raises ValueError, and the loop sends that message back to the
model so it can correct itself.

Results are small lists of dicts. Every query has a row cap, because whatever
a tool returns is sent back to the model as text: a huge dump would cost
tokens, slow the answer, and hide the useful rows.
"""
from ..storage.models import format_cents
from ..storage.repository import PostgresSalaryRepository

# Row caps per tool. Small enough to keep the model's context short, large
# enough to answer "top N" and "who is this person" questions.
MAX_PEOPLE = 20
MAX_HISTORY = 50
MAX_EARNERS = 25
MAX_EMPLOYERS = 20


def _text(value, name):
    """Return a stripped, nonempty string or raise ValueError naming the argument."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    if len(value) > 200:
        raise ValueError(f'{name} is too long')
    return value.strip()


def _year(value):
    """Return a valid year (or None when the model left it out)."""
    if value is None:
        return None
    # bool is a subclass of int in Python, so exclude it explicitly.
    if type(value) is not int or not 0 <= value <= 9999:
        raise ValueError('year must be an integer such as 2024')
    return value


def _like_pattern(text):
    """Turn user text into an ILIKE pattern that matches it anywhere.

    % and _ are wildcards in LIKE, and backslash is its escape character, so
    escape all three: "100%" then means the literal text, not "100 then anything".
    """
    escaped = text.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return f'%{escaped}%'


def _dollars(cents):
    """Money for the model: exact dollars as text, e.g. '$123456.78'."""
    return '$' + format_cents(cents)


def search_by_name(connection, last_name, first_name=None):
    """People with this last name (and first name, if given), one row per name + employer.

    Uses fold_name (migration 003), so case and accents are ignored, and the
    whole name must match. Lets the model find out who someone is (and how
    their name is spelled) before asking for a full salary history.
    """
    last_name = _text(last_name, 'last_name')
    first_name = None if first_name is None else _text(first_name, 'first_name')
    rows = connection.execute(
        """
        SELECT min(first_name), min(last_name), employer,
               min(year), max(year), count(*)
        FROM salary_records
        WHERE fold_name(last_name) = fold_name(%s)
          AND (%s::text IS NULL OR fold_name(first_name) = fold_name(%s))
        GROUP BY fold_name(last_name), fold_name(first_name), employer
        ORDER BY max(year) DESC, min(first_name), employer
        LIMIT %s
        """,
        (last_name, first_name, first_name, MAX_PEOPLE),
    ).fetchall()
    return [{'first_name': first, 'last_name': last, 'employer': employer,
             'first_year': first_year, 'last_year': last_year, 'disclosures': count}
            for first, last, employer, first_year, last_year, count in rows]


def salary_history(connection, first_name, last_name):
    """Every disclosure for one exact full name, newest year first.

    Reuses the same query as the web page's Search tab, so the chat and the
    page always agree on who "the same person" is.
    """
    rows = PostgresSalaryRepository(connection).person_history(
        _text(first_name, 'first_name'), _text(last_name, 'last_name'))
    return [{'first_name': row.first_name, 'last_name': row.last_name,
             'job_title': row.job_title, 'employer': row.employer,
             'year': row.year, 'salary': _dollars(row.salary_cents)}
            for row in rows[:MAX_HISTORY]]


def top_earners(connection, year, employer=None, n=5):
    """The n highest salaries in one year, optionally only at matching employers."""
    year = _year(year)
    if year is None:
        raise ValueError('year is required')
    if type(n) is not int:
        raise ValueError('n must be an integer')
    # Clamp instead of failing: "top 100" still gets a useful (capped) answer.
    n = max(1, min(n, MAX_EARNERS))
    pattern = None if employer is None else _like_pattern(_text(employer, 'employer'))
    rows = connection.execute(
        """
        SELECT first_name, last_name, job_title, employer, salary_cents
        FROM salary_records
        WHERE year = %s
          AND (%s::text IS NULL OR employer ILIKE %s)
        ORDER BY salary_cents DESC, id
        LIMIT %s
        """,
        (year, pattern, pattern, n),
    ).fetchall()
    return [{'first_name': first, 'last_name': last, 'job_title': title,
             'employer': employer_name, 'salary': _dollars(cents)}
            for first, last, title, employer_name, cents in rows]


def find_employers(connection, text, year=None):
    """Employer names containing this text, with how many disclosures each has.

    Ontario's employer names are long and inconsistent ("University of
    Waterloo" vs "The University Of Waterloo"), so the model looks them up
    here before filtering top_earners by employer.
    """
    pattern = _like_pattern(_text(text, 'text'))
    year = _year(year)
    # shortcut: ILIKE '%...%' cannot use an index, so this scans the table
    # (fine at a few million rows under the API's statement timeout); add a
    # pg_trgm index if it ever gets slow.
    rows = connection.execute(
        """
        SELECT employer, count(*), min(year), max(year)
        FROM salary_records
        WHERE employer ILIKE %s
          AND (%s::int IS NULL OR year = %s)
        GROUP BY employer
        ORDER BY count(*) DESC, employer
        LIMIT %s
        """,
        (pattern, year, year, MAX_EMPLOYERS),
    ).fetchall()
    return [{'employer': employer, 'disclosures': count,
             'first_year': first_year, 'last_year': last_year}
            for employer, count, first_year, last_year in rows]


# The menu the model sees. Each entry names a function, says in plain words
# when to use it, and describes its arguments as JSON Schema. The model never
# runs anything itself: it only replies "please call X with these arguments",
# and agent.py runs the matching Python function.
TOOLS = [
    {
        'type': 'function',
        'function': {
            'name': 'search_by_name',
            'description': 'Find people by exact last name (and optionally first name). '
                           'Returns each matching name with employer and the years it appears. '
                           'Use it to check spelling or tell people with the same name apart.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'last_name': {'type': 'string', 'description': 'Full last name, e.g. "Smith"'},
                    'first_name': {'type': 'string', 'description': 'Full first name (optional)'},
                },
                'required': ['last_name'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'salary_history',
            'description': 'Every disclosed salary for one exact full name, newest year first, '
                           'with job title and employer. Use for "how has X\'s salary changed".',
            'parameters': {
                'type': 'object',
                'properties': {
                    'first_name': {'type': 'string'},
                    'last_name': {'type': 'string'},
                },
                'required': ['first_name', 'last_name'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'top_earners',
            'description': f'The highest salaries in one year, highest first (at most {MAX_EARNERS}). '
                           'Optionally only employers whose name contains the given text; '
                           'use find_employers first to get the exact employer name.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'year': {'type': 'integer', 'description': 'Disclosure year, e.g. 2024'},
                    'employer': {'type': 'string', 'description': 'Text the employer name contains'},
                    'n': {'type': 'integer', 'description': 'How many people (default 5)'},
                },
                'required': ['year'],
            },
        },
    },
    {
        'type': 'function',
        'function': {
            'name': 'find_employers',
            'description': 'Employer names containing some text, with disclosure counts and '
                           'the years they appear. Use it to turn "Waterloo" into exact names.',
            'parameters': {
                'type': 'object',
                'properties': {
                    'text': {'type': 'string', 'description': 'Part of the employer name'},
                    'year': {'type': 'integer', 'description': 'Only this year (optional)'},
                },
                'required': ['text'],
            },
        },
    },
]

# Name -> function, so the loop can look up whatever name the model asked for.
FUNCTIONS = {
    'search_by_name': search_by_name,
    'salary_history': salary_history,
    'top_earners': top_earners,
    'find_employers': find_employers,
}
