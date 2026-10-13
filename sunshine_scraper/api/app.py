"""Read-only HTTP API over the Sunshine List database.

Run it with:  uvicorn sunshine_scraper.api.app:app --reload
Then open http://127.0.0.1:8000/ for the web page, or /docs to try every
endpoint directly.

The API only reads. The scraper (a separate process) is the only writer, so
every route is a GET and every database transaction is marked read-only.
"""
from contextlib import contextmanager
import logging
import math
from pathlib import Path
import threading
from typing import Annotated, Callable, ContextManager, Iterator

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# config.py sits at the project root, like for the CLI. uvicorn and the tests
# both run from that directory, so it is importable here too.
import config

from ..storage.connection import (DatabaseAccessError, DatabaseConfigurationError,
                                  DatabaseSettings, open_read_only_connection)
from ..storage.repository import MAX_LIMIT, PostgresSalaryRepository, SalaryReader
from .ratelimit import RateLimiter
from .schemas import Health, Salary, TitleStats, YearStats

logger = logging.getLogger(__name__)

# The frontend's HTML, JavaScript and CSS (sunshine_scraper/web/).
WEB_DIR = Path(__file__).resolve().parent.parent / 'web'

app = FastAPI(
    title='Ontario Sunshine List API',
    description='Read-only access to salary disclosures stored by the scraper.',
    version='1.0.0',
)

# Kept on app.state (not a hidden global) so tests can swap in a tiny limit
# or reset it between tests.
app.state.rate_limiter = RateLimiter(
    capacity=config.api_rate_limit_requests,
    refill_per_second=config.api_rate_limit_requests / config.api_rate_limit_window,
)


# --- Middleware ---------------------------------------------------------------
# Middleware wraps every request: it runs before routing (and so before
# validation or any database work) and can change or replace the response.
# The middleware registered *last* runs *first*, so security headers wrap
# everything, including the 429 responses produced by the rate limiter.

@app.middleware('http')
async def limit_request_rate(request: Request, call_next):
    """Refuse API requests from a client that is sending too many.

    Only /api/ paths count: loading the page and its script are cheap static
    files, and they should not use up the budget for real queries.

    The key is the connecting address. X-Forwarded-For is deliberately
    ignored, because any client can write that header and would get a fresh
    limit per made-up address. Behind a real reverse proxy, start uvicorn with
    --proxy-headers --forwarded-allow-ips=<proxy address>, and uvicorn will
    set request.client from the header only when that trusted proxy sent it.
    """
    if request.url.path.startswith('/api/'):
        client = request.client.host if request.client else 'unknown'
        wait = request.app.state.rate_limiter.check(client)
        if wait is not None:
            # Path only, never the query string: keeps logs small and free of
            # whatever a client typed.
            logger.warning('Rate limit exceeded for %s on %s', client, request.url.path)
            return JSONResponse(
                status_code=429,
                content={'detail': 'Too many requests'},
                # Whole seconds, rounded up, so a client that waits exactly
                # this long is never refused again for the same reason.
                headers={'Retry-After': str(max(1, math.ceil(wait)))},
            )
    return await call_next(request)


# A strict Content Security Policy: the browser may only run scripts and load
# styles from this server. Even if salary data somehow contained HTML or a
# <script> tag, the browser would refuse to run it. frame-ancestors stops other
# sites from embedding the page in a hidden frame (clickjacking).
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)


@app.middleware('http')
async def add_security_headers(request: Request, call_next):
    """Add browser safety headers to every response."""
    response = await call_next(request)
    # Don't let a browser guess a different content type (e.g. treat JSON as HTML).
    response.headers['X-Content-Type-Options'] = 'nosniff'
    # Don't tell other sites which page or query a visitor came from.
    response.headers['Referrer-Policy'] = 'no-referrer'
    # Older browsers understand this instead of frame-ancestors.
    response.headers['X-Frame-Options'] = 'DENY'
    # FastAPI's /docs page loads Swagger UI from a CDN with an inline script,
    # which the strict policy would block, so those pages are left without it.
    if not request.url.path.startswith(('/docs', '/redoc')):
        response.headers['Content-Security-Policy'] = CONTENT_SECURITY_POLICY
    return response


# --- Database access --------------------------------------------------------
# Each request opens its own short read-only transaction and closes it before
# the response is sent. Routes open it inside their body, not as a FastAPI
# dependency, on purpose: FastAPI runs dependencies *before* it validates
# query parameters, so a dependency would connect to PostgreSQL even for a
# request it is about to reject with 422.

# At most this many requests talk to PostgreSQL at the same time; the rest
# wait their turn. The rate limiter stops one client from sending too much,
# but many clients together could still start dozens of heavy queries at once.
# They would then all slow each other down past the statement timeout and
# *every* request would fail. Queuing keeps the database working at a pace
# it can sustain. A semaphore is a counter of free slots that threads take
# and give back; FastAPI runs these plain-def routes in threads.
#
# Known tradeoff: a waiting request holds one of AnyIO's worker threads (40 by
# default, shared with StaticFiles) for up to api_query_wait_seconds. A flood
# could therefore also slow static files. Acceptable for an API that only runs
# locally; a public deployment would want an async wait or a smaller timeout.
query_slots = threading.BoundedSemaphore(config.api_max_concurrent_queries)


@contextmanager
def read_only_connection() -> Iterator:
    """Open one connection whose transaction cannot write.

    open_read_only_connection marks the transaction read-only, closes the
    connection, and turns driver errors into DatabaseAccessError (without the
    URL or password).
    Settings are read per request so a missing SUNSHINE_DATABASE_URL becomes a
    503 response instead of stopping the server from starting.
    """
    settings = DatabaseSettings.from_environment()
    # Wait for a free query slot first (see query_slots). Giving up after a
    # bounded wait turns overload into a quick 503 rather than a pile-up of
    # requests that all time out together.
    if not query_slots.acquire(timeout=config.api_query_wait_seconds):
        raise DatabaseAccessError('All query slots busy')
    try:
        with open_read_only_connection(settings) as connection:
            # Cap how long any query in this transaction may run, so a slow query
            # can't hold a worker thread and a connection indefinitely. set_config
            # (unlike SET) accepts a parameter, and `true` makes it last only for
            # this transaction. A cancelled query raises a driver error, which
            # open_read_only_connection turns into DatabaseAccessError (503).
            connection.execute("SELECT set_config('statement_timeout', %s, true)",
                               (f'{config.api_statement_timeout_ms}ms',))
            yield connection
    finally:
        query_slots.release()


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
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT,
                             description=f'Number of rows (1-{MAX_LIMIT})')]


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


# --- Frontend -----------------------------------------------------------------
# Serve the web page from the same server as the API. Same origin means the
# page's fetch('/api/...') calls need no CORS setup, and no other website is
# granted permission to call the API from its visitors' browsers.
# This mount must come last: Starlette tries routes in order, and a mount at
# '/' matches every path, so earlier routes (/api/..., /docs) win first.
# html=True serves index.html for '/'.
app.mount('/', StaticFiles(directory=WEB_DIR, html=True), name='web')
