# 8. The web page and API protection

This chapter covers the browser frontend in `sunshine_scraper/web/` and the
protections added in front of the API: rate limiting, a cap on concurrent
queries, a query timeout, and browser security headers. Read chapter 7 first.

**Contents**

1. [What was built](#1-what-was-built)
2. [Run it](#2-run-it)
3. [How the page talks to the API](#3-how-the-page-talks-to-the-api)
4. [Keeping external data harmless](#4-keeping-external-data-harmless)
5. [Rate limiting with a token bucket](#5-rate-limiting-with-a-token-bucket)
6. [Too many clients at once: query slots and the timeout](#6-too-many-clients-at-once-query-slots-and-the-timeout)
7. [Security headers](#7-security-headers)
8. [How the tests work](#8-how-the-tests-work)
9. [Before putting it on the internet](#9-before-putting-it-on-the-internet)
10. [Check yourself](#10-check-yourself)

---

## 1. What was built

| File | Role |
| --- | --- |
| `sunshine_scraper/web/index.html` | The page: three tabs, forms, empty tables. No inline code. |
| `sunshine_scraper/web/app.js` | Calls the API, fills tables, draws the yearly chart, shows errors. |
| `sunshine_scraper/web/styles.css` | Layout, phone-width support, light and dark colours. |
| `sunshine_scraper/api/ratelimit.py` | `RateLimiter`: the token bucket (section 5). |
| `sunshine_scraper/api/app.py` | Middleware for rate limits and headers, query slots, statement timeout, and the static-file mount. |
| `config.py` | `api_rate_limit_*`, `api_statement_timeout_ms`, `api_max_concurrent_queries`, `api_query_wait_seconds`. |
| `tests/test_api_security.py` | Offline tests for all of the above. |

The page uses **only the existing endpoints**; nothing new was added to the
API's data contract:

| Tab | Calls |
| --- | --- |
| Top salaries | `/api/years` (fills the year list), then `/api/salaries/top?year=&limit=` |
| Years overview | `/api/years` (table + bar chart) |
| Common job titles | `/api/titles/top?limit=` |
| Header dot | `/api/health` |

---

## 2. Run it

```powershell
$env:SUNSHINE_DATABASE_URL = 'postgresql://sunshine:...@localhost/sunshine'
uvicorn sunshine_scraper.api.app:app --reload
```

Open `http://127.0.0.1:8000/`. The newest year's top 10 salaries load
straight away; pick another year or size and press **Show salaries** (or
Enter). `/docs` still works for trying the raw API.

---

## 3. How the page talks to the API

**Same server, same origin.** `app.py` ends with:

```python
app.mount('/', StaticFiles(directory=WEB_DIR, html=True), name='web')
```

The browser loads the page from `http://127.0.0.1:8000/` and the page calls
`fetch('/api/years')`, which goes to the same address. Browsers block a page
from reading responses from *other* origins unless that server opts in with
CORS headers. Because everything is one origin, no CORS setup is needed, and
no other website gets permission to call the API through its visitors'
browsers.

The mount must be the **last** thing registered. Starlette tries routes in
order, and a mount at `/` matches every path; registered earlier, it would
swallow `/api/...` and `/docs`.

**No build step.** Plain HTML, CSS and JavaScript run directly in the browser.
There is no Node.js, bundler or framework to install, which suits a Python
project. The price is a little more manual DOM code in `app.js`.

**One request at a time per button.** `whileBusy` disables a button until its
request finishes, so double clicks don't send duplicates. `/api/years` is
fetched once and shared by two tabs (`loadYears` keeps the promise), and each
tab loads its data only when first opened.

**Errors become sentences.** `describeError` turns status codes from chapter 7
into messages: 429 shows how long to wait (from the `Retry-After` header), 503
says the database is unavailable, 422 lists FastAPI's validation messages.

**Money stays exact.** `formatCents` splits integer cents into dollars and
cents with integer arithmetic (`Math.floor(cents / 100)` and `cents % 100`),
then formats the dollars with `Intl.NumberFormat`, giving `$2,010,895.76`.

---

## 4. Keeping external data harmless

Names, employers and job titles come from Ontario's files, through the
database, into the page. The page must treat them as *text*, never as HTML.

If code did `cell.innerHTML = salary.employer` and an employer were
`<img src=x onerror="steal()">`, the browser would create that image and run
the script. This attack is called **cross-site scripting (XSS)**. `app.js`
never uses `innerHTML`; every value goes through `textContent` or
`createElement`, which the browser displays literally. The chart is built with
`createElementNS` for the same reason.

A test (`test_frontend_never_parses_data_as_html`) fails if `.innerHTML`,
`.outerHTML`, `insertAdjacentHTML` or `document.write` ever appears in
`app.js`. The Content-Security-Policy (section 7) is a second layer.

---

## 5. Rate limiting with a token bucket

Without a limit, a single script in a loop could keep the server and database
busy and everyone else would wait.

**The token bucket.** Each client has a bucket of up to `capacity` tokens
(60). A request spends one token. Tokens flow back at
`capacity / window` per second (60 / 60 = 1 per second). So:

- A visitor can do a quick burst (opening the page and clicking around) without
  ever noticing the limit.
- Over a long period, no client exceeds 60 requests per minute.
- A refused client learns exactly when the next token arrives: the `429`
  response carries `Retry-After: <seconds>`.

The bucket doesn't need a timer. When a request arrives, `_refill` computes
how many tokens dripped in since the last request
(`elapsed * refill_per_second`, capped at `capacity`). A refused request does
not spend a token, so hammering doesn't push the wait further out.

**Which client?** The key is `request.client.host`, the address that actually
connected. The middleware deliberately ignores `X-Forwarded-For`: any client
can send that header, and trusting it would give an attacker a fresh bucket
for every made-up address (a test checks this). Behind a real reverse proxy,
every request would come *from the proxy*, so start uvicorn with
`--proxy-headers --forwarded-allow-ips=<proxy IP>`; uvicorn then uses the
header only when that trusted proxy sent it.

**Bounded memory.** One bucket per address could grow without end if requests
came from many addresses. `max_clients` (10,000) caps it: buckets that have
fully refilled carry no information and are dropped first; if none have, the
one idle longest goes.

**Only `/api/` counts.** The page, script and stylesheet are cheap static
files; loading them should not use up the budget for real queries.

**Thread safety.** Several requests can arrive at once. A `threading.Lock`
makes "read tokens, subtract one, save" one indivisible step, so two requests
can't both spend the last token.

**Per process.** Buckets live in memory. With `uvicorn --workers 4`, each
worker has its own buckets and the effective limit is four times higher. A
shared store such as Redis is the usual next step if that ever matters.

---

## 6. Too many clients at once: query slots and the timeout

The rate limit stops *one* client from sending too much. It does not stop
twenty clients, each well under their limit, from arriving together.

This was found by testing against the real database: 20 simultaneous
`/api/titles/top` requests (a `GROUP BY` over every record, about one second
alone) slowed each other down so much that many passed the 5-second statement
timeout and *all* of those failed with 503.

Two settings now work together:

1. **Statement timeout** (`api_statement_timeout_ms = 5000`). Right after
   `SET TRANSACTION READ ONLY`, each transaction runs
   `SELECT set_config('statement_timeout', %s, true)`. PostgreSQL cancels any
   query that runs longer, so no request can hold a thread and a connection
   indefinitely. `set_config` is used instead of `SET` because it takes a
   query parameter (the project's "all SQL values via parameters" rule), and
   `true` limits it to this transaction.
2. **Query slots** (`api_max_concurrent_queries = 4`). `query_slots` is a
   `threading.BoundedSemaphore`, a counter of free slots. A request takes a slot
   before connecting and gives it back in a `finally` block, even when the
   query fails. Requests beyond four wait, up to `api_query_wait_seconds`,
   then get 503.

With slots, the same 20-request burst succeeded 40 out of 40 times: requests
queue briefly instead of all slowing down together. A few queries finishing
quickly serves more people than many queries finishing late or not at all.

The slot is taken *after* reading settings, so a missing
`SUNSHINE_DATABASE_URL` still fails fast without waiting for a slot.

---

## 7. Security headers

`add_security_headers` adds these to every response, including 429s:

| Header | Effect |
| --- | --- |
| `Content-Security-Policy` | The browser may only load scripts, styles and data from this server. Inline `<script>` and `style=` are refused, so even injected HTML couldn't run code. `frame-ancestors 'none'` forbids embedding the page in another site. |
| `X-Content-Type-Options: nosniff` | The browser must trust the declared content type, not guess (e.g. never treat JSON as HTML). |
| `X-Frame-Options: DENY` | The older form of `frame-ancestors`, for older browsers. |
| `Referrer-Policy: no-referrer` | Links out of the page don't reveal which page or query the visitor came from. |

`/docs` and `/redoc` are exempt from the CSP: FastAPI's Swagger UI loads from a
CDN and uses an inline script, which the policy would block.

The strict policy is why the page has no inline code, why the chart is drawn
without a CDN library, and why a test checks `index.html` for `<script>` and
`style=`: anything inline would silently stop working in the browser.

---

## 8. How the tests work

`tests/test_api_security.py` runs offline with the normal command.

| Group | Proves |
| --- | --- |
| `RateLimiterTests` | Burst up to capacity, then refusal with the right wait; refused requests don't spend tokens; refill over time but never above capacity; separate clients; memory cap eviction order. A `FakeClock` replaces `time.monotonic`, so nothing sleeps. |
| `RateLimitMiddlewareTests` | With a 2-request limit swapped onto `app.state`, the third `/api/years` gets 429 + `Retry-After` and never reaches the reader; the log omits the query string; 429s still carry security headers; static files don't count; a forged `X-Forwarded-For` doesn't help. |
| `QuerySlotTests` | With the only slot taken, a request gets 503 without connecting; a failing query still returns its slot. |
| `FrontendTests` | `/` serves the page with CSP and `nosniff`; `app.js` and `styles.css` are served; no `innerHTML`; no inline code; `/api` and `/docs` still work; unknown paths 404; `POST /` is 405. |

`tests/test_api.py` calls `app.state.rate_limiter.reset()` in `setUp` so the
shared limiter can't leak state between tests, and its connection test now
expects the `set_config` call between `SET TRANSACTION READ ONLY` and the query.

The JavaScript itself has no automated tests; check it in a browser (section 2).

---

## 9. Before putting it on the internet

Everything above protects a server running on your own computer. To expose it:

- Run without `--reload`, behind a reverse proxy (Caddy, nginx) that provides
  **HTTPS**, and use `--proxy-headers --forwarded-allow-ips` (section 5).
- Add `--no-server-header` so responses don't advertise the server software.
- Give the API its own PostgreSQL role with `SELECT` only (chapter 7, section 9).
- Consider caching the yearly and title results: they only change when a sync
  runs, and they are the most expensive queries.

---

## 10. Check yourself

1. With `capacity=60` and a window of 60 seconds, a client sends 60 requests at
   once. How long until the 61st is accepted? How many can it send in the next
   minute?
2. Why would trusting `X-Forwarded-For` defeat the rate limit?
3. What would happen to `/api/years` if the `app.mount('/')` line moved above
   the route definitions?
4. Why does the query slot get released in `finally` rather than after
   `yield`?
5. Change one `textContent` in `app.js` to `innerHTML` and run the tests. Which
   test fails, and what attack is it guarding against? Undo the change.
