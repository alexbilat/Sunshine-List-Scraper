# 7. The web API: how it works and what was built

This chapter explains the read-only HTTP API in `sunshine_scraper/api/`. It covers
the ideas behind web APIs, then walks through every file, endpoint, and design
decision, and how the tests prove it works. Read chapters 4–6 first if the
database layer is unfamiliar.

**Contents**

1. [What was built](#1-what-was-built)
2. [How a web API works](#2-how-a-web-api-works)
3. [Two programs, one database](#3-two-programs-one-database)
4. [Run it and try it](#4-run-it-and-try-it)
5. [Endpoint reference](#5-endpoint-reference)
6. [Follow one request through the code](#6-follow-one-request-through-the-code)
7. [Design decisions](#7-design-decisions)
8. [How the tests work](#8-how-the-tests-work)
9. [What comes next](#9-what-comes-next)
10. [Check yourself](#10-check-yourself)

---

## 1. What was built

A small web server that answers questions about the salary data with JSON. It
reuses the existing storage layer (`PostgresSalaryRepository`, `open_connection`,
`format_cents`) and adds no new SQL.

| File | Role |
| --- | --- |
| `sunshine_scraper/api/__init__.py` | Marks the package; explains what it is for. |
| `sunshine_scraper/api/app.py` | The FastAPI application: database access, routes, error handling. |
| `sunshine_scraper/api/schemas.py` | Response models: the exact JSON shape each endpoint returns. |
| `tests/test_api.py` | 11 offline tests for routes, validation, JSON, and errors. |
| `sunshine_scraper/storage/repository.py` | The `SalaryReader` interface gained `top_job_titles`, which the API uses. |
| `requirements.txt` | Added `fastapi`, `uvicorn[standard]`, and `httpx2` (tests). |

Four endpoints, all `GET`:

| Endpoint | Answers | Backed by |
| --- | --- | --- |
| `/api/health` | Is the server up, and does PostgreSQL answer? | `SELECT 1` |
| `/api/years` | Headcount and average salary per year | `yearly_summary()` |
| `/api/titles/top?limit=10` | Most common job titles | `top_job_titles(limit)` |
| `/api/salaries/top?year=2024&limit=10` | Highest salaries in one year | `get_top_salaries(year, limit)` |

The first three data endpoints carry the same information as your charts and the
`top` CLI command. A frontend can now draw them from JSON instead of PNG files.

---

## 2. How a web API works

### An API is a contract

An **API** (Application Programming Interface) is an agreed way for one program to
ask another for something. You already use one: `repository.get_top_salaries(2024, 10)`
is a contract. Callers know the method name, the arguments, and what comes back.
They don't know or care about the SQL inside.

A **web API** is the same contract across a network. A browser, phone app, or
script can't call your Python methods. It sends a text message over **HTTP**
instead, and your server sends a text message back.

### The request

When a browser visits `http://127.0.0.1:8000/api/salaries/top?year=2024&limit=2`,
it sends text like this:

```http
GET /api/salaries/top?year=2024&limit=2 HTTP/1.1
Host: 127.0.0.1:8000
Accept: application/json
```

| Part | Here | Meaning |
| --- | --- | --- |
| **Method** | `GET` | What to do. `GET` reads. `POST` creates, `PUT`/`PATCH` change, `DELETE` removes. |
| **Path** | `/api/salaries/top` | *Which* resource. In REST style, paths are nouns. |
| **Query string** | `?year=2024&limit=2` | Options: filters, sizes, sorting. Always text; the server converts it. |
| **Headers** | `Accept: application/json` | Metadata: formats, caching, authentication. |
| **Body** | none | Data sent *to* the server. `GET` requests don't have one. |

You've seen this from the other side: `client.py` sends requests to Ontario's
servers and handles their headers (ETag, 304 Not Modified). Now your program is
the server.

### The response

```http
HTTP/1.1 200 OK
content-type: application/json

[{"name":"Alex Example","first_name":"Alex","last_name":"Example",
  "employer":"Example Hospital","salary_cents":12345678,"salary":"123456.78"}, ...]
```

The **status code** is a three-digit summary of the outcome. The first digit is
the category:

| Code | Meaning | When this API returns it |
| --- | --- | --- |
| `200 OK` | Success | Data returned |
| `405 Method Not Allowed` | That method isn't supported here | e.g. `POST /api/years` |
| `422 Unprocessable Content` | The caller's input is invalid | `limit=500`, `year=latest`, `year` missing |
| `500 Internal Server Error` | A bug on the server | Something unexpected raised |
| `503 Service Unavailable` | A dependency is down; try later | PostgreSQL unreachable, URL not set, schema missing |

`4xx` means "you, the client, did something wrong". `5xx` means "I, the server,
couldn't do it". That split matters to clients: retrying a 4xx gives the same
result, while retrying a 503 later may succeed.

The **body** is **JSON**, text made of objects `{}`, arrays `[]`, strings, numbers,
`true`/`false`, and `null`. Python dicts, lists, `str`, `int`, `bool`, and `None`
map onto it almost one to one, which is why JSON is the default for web APIs.

### Three properties worth remembering

- **Stateless.** Every request carries everything needed to answer it. The
  server doesn't remember your last request, so each request opens its own
  database transaction.
- **The contract is what matters.** A frontend depends only on URLs and JSON
  shapes. You could rewrite the server in another language, or swap the
  frontend for a phone app, and the other side wouldn't notice.
- **It's a security boundary.** The API decides what the outside world can see
  and do. It validates every input and never reveals internal details (like the
  database URL) in its responses.

### Why REST + JSON, and why FastAPI

REST-style JSON over HTTP is the most common kind of web API, and you can test
it with nothing but a browser. Alternatives such as GraphQL, gRPC, and WebSockets
solve problems this project doesn't have yet.

**FastAPI** fits this codebase:

- It reads Python **type hints**. A parameter declared `year: int` is converted
  from text and validated for you, and a bad value becomes a 422 automatically.
- It generates **interactive documentation** at `/docs` from the same type hints.
- Its **dependency injection** (section 7.2) lets tests swap the database for a fake.

The server program that actually listens on the network port is **uvicorn**.
FastAPI is the framework (routing, validation, JSON); uvicorn is the engine that
speaks HTTP and hands each request to FastAPI.

---

## 3. Two programs, one database

```
 [Scraper CLI]  --writes-->  PostgreSQL  <--reads--  [API server]  <--HTTP/JSON-->  [Browser / curl / frontend]
 runs, syncs, exits                                  runs continuously
```

The scraper and the API are separate processes. The scraper still runs on demand
or on a schedule, syncs Ontario's data, and exits. The API runs continuously and
only reads. They never talk to each other directly. PostgreSQL is the shared
source of truth, which is the payoff of decision D1 (chapter 4).

This also means the API always serves whatever the last completed sync
committed. A sync in progress is invisible to it until each dataset's
transaction commits.

---

## 4. Run it and try it

Install the new packages, set the database URL as you do for the scraper, and
start the server:

```powershell
python -m pip install -r requirements.txt
$env:SUNSHINE_DATABASE_URL = 'postgresql://sunshine:...@localhost/sunshine'
uvicorn sunshine_scraper.api.app:app --reload
```

- `sunshine_scraper.api.app:app` means "the variable `app` in module
  `sunshine_scraper.api.app`".
- `--reload` restarts the server whenever you save a `.py` file. Use it only
  for development.
- The server listens on `http://127.0.0.1:8000`, so only your own computer can
  reach it. Press Ctrl+C to stop it.

Then try it, in this order:

1. **Browser address bar:** open `http://127.0.0.1:8000/api/years`. A GET request
   is just a URL; the browser shows the raw JSON.
2. **Interactive docs:** open `http://127.0.0.1:8000/docs`. Expand an endpoint,
   click **Try it out**, enter parameters, and click **Execute**. The page shows the
   exact URL it called, the status code, and the response body. Try `limit=500`
   to see a 422.
3. **PowerShell:** `Invoke-RestMethod` parses the JSON into objects:
   ```powershell
   Invoke-RestMethod 'http://127.0.0.1:8000/api/salaries/top?year=2024&limit=5' | Format-Table
   ```
4. **The machine-readable contract:** `http://127.0.0.1:8000/openapi.json` is the
   OpenAPI description that `/docs` is drawn from. Tools can generate client
   code from it.

The terminal running uvicorn logs one line per request, with the status code.

---

## 5. Endpoint reference

The values below are made up; your numbers come from your database.

### `GET /api/health`

```json
{"status": "ok"}
```

Confirms the server runs *and* PostgreSQL answers. It does not check the schema
or data. It returns 503 when the database can't be reached.

### `GET /api/years`

Every year, oldest first, ready for the yearly chart:

```json
[
  {"year": 2023, "people": 300000, "average_salary_cents": 13654321, "average_salary": "136543.21"},
  {"year": 2024, "people": 301000, "average_salary_cents": 13811111, "average_salary": "138111.11"}
]
```

`average_salary_cents` and `average_salary` are `null` if a year has no salaries.

### `GET /api/titles/top?limit=10`

| Parameter | Type | Default | Allowed |
| --- | --- | --- | --- |
| `limit` | integer | 10 | 1–100 |

```json
[{"job_title": "Teacher", "appearances": 412345}, {"job_title": "Professor", "appearances": 98765}]
```

The most common nonempty job titles across all years, most frequent first.

### `GET /api/salaries/top?year=2024&limit=10`

| Parameter | Type | Default | Allowed |
| --- | --- | --- | --- |
| `year` | integer | **required** | 0–9999 |
| `limit` | integer | 10 | 1–100 |

```json
[{"name": "Alex Example", "first_name": "Alex", "last_name": "Example",
  "employer": "Example Hospital", "salary_cents": 12345678, "salary": "123456.78"}]
```

A year with no data returns an empty list `[]` with status 200. "No results" is
a valid answer, not an error.

### Error bodies

A validation error (422) names the parameter and the rule it broke:

```json
{"detail": [{"type": "less_than_equal", "loc": ["query", "limit"],
             "msg": "Input should be less than or equal to 100", "input": "500", "ctx": {"le": 100}}]}
```

A database problem (503) is deliberately vague:

```json
{"detail": "Database unavailable"}
```

---

## 6. Follow one request through the code

Here is what happens for `GET /api/salaries/top?year=2024&limit=2`, in order.

**1. uvicorn receives the bytes.** It parses the HTTP text and hands FastAPI a
structured request.

**2. FastAPI finds the route.** It matches the method and path against the
decorators in `app.py`:

```python
@app.get('/api/salaries/top', response_model=list[Salary])
def top_salaries(open_reader: OpenReader, year: Year, limit: Limit = 10) -> list[Salary]:
```

**3. FastAPI validates the input.** `Year` and `Limit` are type aliases defined
once and reused:

```python
Year = Annotated[int, Query(ge=0, le=9999, description='Disclosure year, e.g. 2024')]
Limit = Annotated[int, Query(ge=1, le=100, description='Number of rows (1-100)')]
```

`Annotated[int, Query(...)]` means "an `int`, read from the query string, with
these rules". `ge`/`le` are "greater or equal" and "less or equal". The text
`"2024"` becomes the integer `2024`. If anything fails, FastAPI answers 422 right
here and the function never runs.

**4. FastAPI resolves the dependency.** `open_reader: OpenReader` is
`Annotated[..., Depends(get_open_reader)]`, so FastAPI calls `get_open_reader()`.
That returns the function `open_reader`, which is passed into the route.
Nothing has touched the database yet.

**5. The route opens a read-only transaction:**

```python
with open_reader() as reader:
    results = reader.get_top_salaries(year, limit)
return [Salary.from_result(result) for result in results]
```

`open_reader()` enters `read_only_connection()`, which enters the existing
`open_connection(DatabaseSettings.from_environment())`:

- `DatabaseSettings.from_environment()` reads `SUNSHINE_DATABASE_URL`. If it's
  missing, it raises `DatabaseConfigurationError`.
- `open_connection` connects with Psycopg. Any driver error inside the block
  becomes `DatabaseAccessError`, with no URL or password in the message.
- The first statement is `SET TRANSACTION READ ONLY`.
- The reader is a `PostgresSalaryRepository`, the same class the CLI uses.

**6. The repository runs its SQL.** It uses its existing parameterized query
(`WHERE year = %s ... LIMIT %s`) and returns `SalaryResult` dataclasses.

**7. The `with` block ends.** Psycopg commits the (empty) read-only transaction
and closes the connection, *before* any JSON is built.

**8. Rows become response models.** `Salary.from_result` copies the fields and
adds the display string `format_cents(12345678)` → `"123456.78"`.

**9. FastAPI serializes and validates the output.** `response_model=list[Salary]`
makes FastAPI check the result against the model, keep only its fields, and
convert it to JSON.

**10. uvicorn sends** `200 OK` with the JSON body and logs the request line.

If step 5 or 6 raises `DatabaseAccessError` or `DatabaseConfigurationError`, the
error skips steps 7–9. FastAPI looks for a matching **exception handler** and
finds `database_unavailable`, which logs the real reason on the server and
returns 503 with a generic body.

---

## 7. Design decisions

### 7.1 Read-only, twice

The API is the public face of the data, and it should never be able to change it.

1. **Only `GET` routes exist.** FastAPI answers any other method with 405.
2. **Every transaction is `SET TRANSACTION READ ONLY`.** Even if a future
   route had a bug that ran `UPDATE`, PostgreSQL would refuse it. The
   `check`/`top` CLI commands use the same line for the same reason.

A third layer, a PostgreSQL role with only `SELECT` privileges, is listed
under section 9.

### 7.2 Dependency injection, and why the database opens inside the route

FastAPI's `Depends` lets a route *declare* what it needs, and FastAPI supplies
it. The value is that a test can replace the supplier:

```python
app.dependency_overrides[get_open_reader] = lambda: self.open_fake_reader
```

Every route now gets an in-memory fake instead of PostgreSQL, without changing
route code.

The obvious design is a dependency that opens the connection itself and
`yield`s it. That was the first version, and a live test exposed a flaw:

```
GET /api/salaries/top?year=2024&limit=500   ->   503 Database unavailable
```

The caller's input was wrong, so the answer should have been 422. **FastAPI
resolves dependencies before it validates query parameters.** The dependency
connected to PostgreSQL first, and only then would `limit` have been checked.
With the database down, a bad request was blamed on the database. With the
database up, every malformed request would open a connection for nothing.

The fix: the dependency hands over a *function* (`open_reader`) instead of an
open connection, and each route calls it inside its body, which only runs
after validation passes. This has two side benefits:

- Errors raised during queries are ordinary exceptions in the route body. They
  don't depend on how a FastAPI version tears down `yield` dependencies.
- The connection is closed before JSON is built, so it's held for the
  shortest possible time.

The test `test_invalid_input_never_opens_a_connection` keeps this from
regressing.

### 7.3 Routes depend on an interface, not on Postgres

Routes are typed against `SalaryReader`, the `Protocol` in `repository.py`. A
Protocol lists the methods an object must have without requiring it to inherit
from anything. `PostgresSalaryRepository` and the test's `FakeSalaryReader` both
qualify. `top_job_titles` was added to the Protocol because the API needs it.

### 7.4 `def`, not `async def`

FastAPI accepts both. `async def` routes run on a single event loop and must
never block. Psycopg's normal calls *do* block while waiting for PostgreSQL.
FastAPI runs plain `def` routes in a pool of worker threads instead, so a slow
query occupies one thread while the server keeps accepting other requests.
Plain `def` is correct here and simpler. Async Psycopg would be a later
optimization, not a need.

### 7.5 Response models separate from storage dataclasses

`schemas.py` defines Pydantic models (`YearStats`, `TitleStats`, `Salary`,
`Health`) rather than returning `YearSummary` and friends directly.

- **The JSON contract is explicit.** You can read one file and know exactly
  what clients receive. Adding a column to `salary_records` cannot leak a new
  field by accident.
- **Names can differ.** Storage says `average_cents` (a raw Decimal); the API
  says `average_salary_cents` (a rounded integer). Each layer uses the name that
  is clearest for its audience.
- **Documentation is free.** `/docs` shows every field and type from these
  classes.

Each model has a small `from_...` classmethod that converts one storage object.
Routes stay one-liners.

### 7.6 Money: integer cents plus a display string, never floats

The project stores money as exact integer cents (chapter 4). The API keeps that
promise:

- `salary_cents: 12345678` is exact. JavaScript can represent integers exactly
  up to 9,007,199,254,740,991, far beyond any salary in cents.
- `salary: "123456.78"` is a string made by `format_cents`, ready to display
  with no client-side rounding.
- A float such as `123456.78` is never sent. Many JSON readers parse numbers as
  binary floats, which can't represent most cent values exactly.

Averages need one extra step. PostgreSQL's `avg()` returns a long exact Decimal
such as `11172839.5000000000`. `round_to_cents` in `schemas.py` rounds it
half-up to whole cents (`11172840`), the same rounding rule used when salaries
are loaded. It uses `to_integral_value`, which isn't affected by the current
Decimal precision setting. That echoes the recent fix that isolated salary
parsing from caller Decimal settings.

### 7.7 Errors: 422, 503, and deliberately no handler for `ValueError`

- **422** comes from FastAPI's validation, before any of our code runs.
- **503** comes from `database_unavailable`, registered for both
  `DatabaseAccessError` and `DatabaseConfigurationError`. The response body is
  fixed text. The specific reason ("SUNSHINE_DATABASE_URL is required", "PostgreSQL
  operation failed...") goes only to the server log, which is where an
  operator looks and a stranger can't. Tests confirm the password never
  appears in either.
- **No `ValueError` handler.** The repository raises `ValueError` for bad
  `year`/`limit`, but `Query(ge=..., le=...)` already blocks those values. A
  `ValueError` reaching the top is therefore a bug in *our* code. Turning it
  into a 4xx would blame the client and hide the bug. Letting it become a 500
  is the honest answer.

### 7.8 Settings are read per request

`DatabaseSettings.from_environment()` runs on each request, not once at import.
The server starts even without `SUNSHINE_DATABASE_URL`, so `/docs` still works,
and data requests return a clear 503. Reading one environment variable costs
almost nothing. Keeping import free of I/O also matches the rest of the
project ("Importing this package does not connect").

---

## 8. How the tests work

`tests/test_api.py` runs offline with the normal command:

```powershell
python -m unittest discover -s tests -v
```

**`TestClient`** sends real HTTP requests to the app in memory, without a server
or network. You write `self.client.get('/api/years', params={...})` and get back
a response with `.status_code` and `.json()`. It needs the `httpx2` package,
which is why that's in `requirements.txt`. (Older FastAPI versions used
`httpx`; Starlette 1.7 now warns and asks for `httpx2`.)

There are two groups of tests:

**`DataRouteTests`: routes with a fake reader.** `FakeSalaryReader` returns
fixed data and records every call it receives. The dependency override makes
routes use it. These tests prove:

| Test | Proves |
| --- | --- |
| `test_years_send_exact_cents_and_display_strings` | Averages round half-up; `None` averages become `null`; the JSON shape is exact. |
| `test_top_titles_default_and_custom_limit` | `limit` defaults to 10 and is passed through. |
| `test_top_salaries_for_a_year` | `year`/`limit` reach the reader; the salary is formatted. |
| `test_invalid_input_is_rejected_before_reaching_the_reader` | Missing, non-integer, and out-of-range input gives 422, and the reader is never called. |
| `test_only_reads_are_allowed` | `POST` gives 405. |
| `test_reader_database_error_becomes_503` | The 503 handler and its generic body. |

**`ConnectionTests`: the real connection code against a patched driver.**
`patch('psycopg.connect')` replaces the driver with a `MagicMock`, so the real
`read_only_connection` and `open_connection` run without a server. The fake URL
contains the password `hunter2` so the tests can check it never leaks.

| Test | Proves |
| --- | --- |
| `test_health_marks_the_transaction_read_only_before_querying` | `SET TRANSACTION READ ONLY` is the first statement. |
| `test_missing_database_url_is_503` | A missing setting gives 503, not a crash. |
| `test_unreachable_server_is_503_without_secrets` | A failed connect gives 503; the password is not in the body or logs. |
| `test_invalid_input_never_opens_a_connection` | The regression test for section 7.2. |
| `test_query_failure_inside_a_route_is_503_without_secrets` | A failure *after* connecting is still translated safely. |

What these tests don't cover: real SQL against a real database. That's
already covered for the repository by `test_postgres_integration.py`, and the
API adds no SQL of its own. To check the full stack, run the server against your
database and use `/docs` (section 4).

---

## 9. What comes next

- **Step 2: a frontend.** Done: `sunshine_scraper/web/`, served by this same
  app, together with rate limiting and other protection. See
  [chapter 8](08-frontend-and-safety.md).
- **Search and pagination.** `GET /api/salaries?year=&employer=&q=&page=` needs a
  new repository method with `LIMIT`/`OFFSET` or keyset pagination. A paged
  response is usually wrapped in an object (`{"items": [...], "next": ...}`)
  rather than a bare list.
- **A connection pool** (`psycopg_pool`) reuses open connections instead of
  connecting per request. The `open_reader` function is the only place that
  would change.
- **A read-only PostgreSQL role** for the API: the third layer of section 7.1.
- **Caching headers.** Data changes only when a sync runs, so the API could
  send `ETag`s. That's the server side of what `client.py` already does as a
  client.
- **Before exposing it beyond your own computer:** run it without `--reload`,
  behind a reverse proxy with HTTPS (chapter 8, section 9).

---

## 10. Check yourself

1. In `GET /api/titles/top?limit=5`, name the method, path, and query string.
2. Why does `limit=500` return 422 and not 503, even when PostgreSQL is down?
3. What would break if `top_salaries` were written with `async def` but kept
   using the same blocking repository?
4. Why does the API send `salary_cents` *and* `salary`, but never a float?
5. Add a temporary `print(year, type(year))` to `top_salaries`, call it from
   `/docs`, and explain why the type is `int` although URLs are text. Then remove
   the `print`, since the project uses `logging`.
6. Write a test asserting `/api/salaries/top?year=1800` returns `200` with `[]`
   when the fake reader has no rows for that year. What change to
   `FakeSalaryReader` does it need?
