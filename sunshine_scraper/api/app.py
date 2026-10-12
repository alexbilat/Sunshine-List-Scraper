"""Read-only HTTP API over the Sunshine List database.

Run it with:  uvicorn sunshine_scraper.api.app:app --reload
Then open http://127.0.0.1:8000/docs to try every endpoint in the browser.

The API only reads. The scraper (a separate process) is the only writer, so
every route is a GET and every database transaction is marked read-only.
"""
from contextlib import contextmanager
import logging
from typing import Annotated, Callable, ContextManager, Iterator

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from ..storage.connection import (DatabaseAccessError, DatabaseConfigurationError,
                                  DatabaseSettings, open_connection)
from ..storage.repository import PostgresSalaryRepository, SalaryReader
from .schemas import Health, Salary, TitleStats, YearStats

logger = logging.getLogger(__name__)

app = FastAPI(
    title='Ontario Sunshine List API',
    description='Read-only access to salary disclosures stored by the scraper.',
    version='1.0.0',
)


# --- Database access --------------------------------------------------------
# Each request opens its own short read-only transaction and closes it before
# the response is sent. Routes open it inside their body, not as a FastAPI
# dependency, on purpose: FastAPI runs dependencies *before* it validates
# query parameters, so a dependency would connect to PostgreSQL even for a
# request it is about to reject with 422.

@contextmanager
def read_only_connection() -> Iterator:
    """Open one connection whose transaction cannot write.

    open_connection commits or rolls back, closes the connection, and turns
    driver errors into DatabaseAccessError (without the URL or password).
    Settings are read per request so a missing SUNSHINE_DATABASE_URL becomes a
    503 response instead of stopping the server from starting.
    """
    with open_connection(DatabaseSettings.from_environment()) as connection:
        # Defense in depth: even if the database role may write, this
        # transaction cannot. PostgreSQL rejects any INSERT/UPDATE/DELETE.
        connection.execute('SET TRANSACTION READ ONLY')
        yield connection


@contextmanager
def open_reader() -> Iterator[SalaryReader]:
    """Open a SalaryReader backed by a read-only PostgreSQL transaction."""
    with read_only_connection() as connection:
        yield PostgresSalaryRepository(connection)


def get_open_reader() -> Callable[[], ContextManager[SalaryReader]]:
    """Dependency: hand routes the function that opens a reader.

    A dependency is a function FastAPI calls before a route runs, passing its
    result in as an argument. Routes receive open_reader this way rather than
    importing it, so tests swap in an in-memory fake with
    app.dependency_overrides and never need PostgreSQL.
    """
    return open_reader


OpenReader = Annotated[Callable[[], ContextManager[SalaryReader]], Depends(get_open_reader)]
# Query(...) validates input before the route body runs: a bad value never
# reaches SQL and the caller gets a 422 naming the parameter that was wrong.
# The bounds mirror the checks in PostgresSalaryRepository and appear in /docs.
Year = Annotated[int, Query(ge=0, le=9999, description='Disclosure year, e.g. 2024')]
Limit = Annotated[int, Query(ge=1, le=100, description='Number of rows (1-100)')]


# --- Errors -----------------------------------------------------------------

@app.exception_handler(DatabaseAccessError)
@app.exception_handler(DatabaseConfigurationError)
def database_unavailable(request: Request, error: Exception) -> JSONResponse:
    """Report database trouble as 503 Service Unavailable.

    503 tells a client the request was fine but a dependency is down, so
    retrying later may work. The detail is fixed: server settings are no
    business of the client, and the specific reason goes to the server log.
    """
    logger.error('%s %s failed: %s', request.method, request.url.path, error)
    return JSONResponse(status_code=503, content={'detail': 'Database unavailable'})


# --- Routes -----------------------------------------------------------------
# response_model tells FastAPI the exact JSON shape: it filters the output to
# those fields and documents them. Paths are nouns; GET says "read this".
#
# Routes are plain `def` (not `async def`) because Psycopg's calls block.
# FastAPI runs plain functions in a worker thread, so one slow query does not
# stop the server from accepting other requests meanwhile.
#
# Each route fetches rows inside `with`, then builds the response after the
# block, so the connection is already closed while JSON is being produced.

@app.get('/api/health', response_model=Health)
def health() -> Health:
    """Confirm the server is running and PostgreSQL answers a trivial query."""
    with read_only_connection() as connection:
        connection.execute('SELECT 1').fetchone()
    return Health(status='ok')


@app.get('/api/years', response_model=list[YearStats])
def years(open_reader: OpenReader) -> list[YearStats]:
    """Headcount and average salary for every year, oldest first."""
    with open_reader() as reader:
        summaries = reader.yearly_summary()
    return [YearStats.from_summary(summary) for summary in summaries]


@app.get('/api/titles/top', response_model=list[TitleStats])
def top_titles(open_reader: OpenReader, limit: Limit = 10) -> list[TitleStats]:
    """The most frequent nonempty job titles across all years."""
    with open_reader() as reader:
        counts = reader.top_job_titles(limit)
    return [TitleStats.from_count(count) for count in counts]


@app.get('/api/salaries/top', response_model=list[Salary])
def top_salaries(open_reader: OpenReader, year: Year, limit: Limit = 10) -> list[Salary]:
    """The highest salaries disclosed for one year, highest first."""
    with open_reader() as reader:
        results = reader.get_top_salaries(year, limit)
    return [Salary.from_result(result) for result in results]
