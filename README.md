# Ontario Sunshine List

**Every public sector salary over $100,000 that Ontario has disclosed since 1996,
collected, cleaned, stored in PostgreSQL, and published as a searchable website.**

### 🔗 [View the live site →](https://alexbilat.github.io/Sunshine-List-Scraper/)

![The website Overview: 2025 headcount, the yearly chart, top salaries and job titles](assets/website.png)

Ontario's [Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure)
(the "Sunshine List") is published as 81 separate datasets spread across two
different systems, with column names that change from year to year. This
project turns all of it into one clean, queryable database and a fast website
anyone can use.

## By the numbers

| | |
| --- | --- |
| Records | **3,272,972** disclosures |
| Years covered | **1996 – 2025** (new years are picked up automatically) |
| Source datasets | **81**, from Ontario's CKAN open-data API and official CSV downloads |
| People listed | **4,512** in 1996 → **404,916** in 2025 |
| Average listed salary | **$121,484.94** in 1996 → **$134,229.51** in 2025 |
| Most common job title | Registered Nurse (124,626 listings across all years) |
| Routine update | about **1 minute**: only changed datasets are downloaded |

![Headcount and average salary by year](assets/chart_yearly.png)

---

## How it works

```
                 ┌──────────────────────── maintainer's computer ────────────────────────┐
                 │                                                                         │
 Ontario         │   1. Scraper            2. PostgreSQL           3. Local web server    │
 open data  ─────┼─► discover, check  ───► source of truth  ─────► website + JSON API     │
 (CKAN + CSV)    │   for changes,          3.3M records            (FastAPI)              │
                 │   validate, load              │                                         │
                 │                               ├──► output.txt + charts                 │
                 │                               │                                         │
                 │                        4. publish_site.py                               │
                 └───────────────────────────────┼─────────────────────────────────────────┘
                                                 ▼
                                    GitHub Pages: static public site
                                    (free, always up, no server)
```

1. **Collect.** The scraper reads Ontario's disclosure page to find every
   dataset. Older years come from the CKAN open-data API (paged 100,000 rows at
   a time); newer years are resolved through Ontario's download manifest to
   their official CSV files. No years or file IDs are hardcoded, so a new year
   appears as soon as Ontario publishes it.
2. **Skip what hasn't changed.** Before downloading, it asks whether each
   dataset changed since the last successful load: HTTP `ETag` / `304 Not
   Modified` for CSVs, CKAN's modification timestamp, and a content hash.
   An unchanged dataset costs one small request.
3. **Clean and store.** Each row is normalized (around a dozen column-name
   variants such as `Surname`/`Last Name` or `Salary Paid`/`Salary`, stray
   whitespace, non-person rows) and its salary is converted to exact integer
   cents. Rows are bulk-loaded with PostgreSQL `COPY` and merged into the main
   table by content, one transaction per dataset, so a failed download rolls
   back alone and the rest of the run continues.
4. **Serve.** A read-only FastAPI app serves the website and a JSON API from
   the database.
5. **Publish.** `publish_site.py` pre-computes every answer the website can
   show (yearly totals, top 100 job titles, top 100 salaries per year) as JSON
   files, about 550 KB in total, and pushes them with the page to GitHub
   Pages. The public site works exactly like the local one but needs no server
   or database, so it is free to host and stays up permanently. A small
   `meta.json` records when it was built, and the page header shows
   "Data updated <date>" instead of the live database status. The site has Overview, Top salaries, Years, Job titles, and Search tabs, and
   Search works there too: everyone is pre-split into small files by the first two
   letters of the surname, and the page downloads only the one it needs.

## Engineering highlights

- **Exact money.** Salaries are integer cents end to end, from parsing
  (`$1,234.565` rounds half-up to `123457`) to SQL to JSON to the browser.
  Floats are never used.
- **Incremental, crash-safe sync.** Conditional requests skip unchanged data;
  an advisory lock prevents overlapping runs; every run and every dataset
  outcome is recorded in `sync_runs` / `sync_run_resources`.
- **Nothing is ever deleted.** Records are identified by their content; a
  changed salary becomes a new record, and every dataset a record appeared in
  is remembered.
- **Versioned schema.** Numbered SQL migrations with checksums; the scraper
  refuses to run against an out-of-date schema instead of guessing.
- **Hardened API.** GET-only routes, `READ ONLY` transactions, per-client
  token-bucket rate limiting (`429` + `Retry-After`), a cap on concurrent
  queries (requests wait up to `api_query_wait_seconds` for a free slot, then
  get `503`), a per-query timeout, and error messages that never leak
  connection details.
- **Safe frontend.** No build step and no third-party scripts; a strict
  Content-Security-Policy, and all data rendered with `textContent`, never as
  HTML. GitHub Pages can't send custom headers, so the public site carries the
  policy in a `<meta>` tag and goes without `frame-ancestors`,
  `X-Frame-Options` and `nosniff`; it shows public data with no logins or
  forms, so the missing clickjacking protection costs little.
- **Tested offline.** About 140 unit tests run without a network or database;
  real-PostgreSQL integration tests are opt-in.

## Tech stack

| Layer | Tools |
| --- | --- |
| Collection | Python 3.12, `requests`, Beautiful Soup |
| Storage | PostgreSQL 14+, `psycopg` 3 (`COPY`, server-side cursors, advisory locks) |
| API | FastAPI, Pydantic, Uvicorn |
| Website | Plain HTML, CSS, and JavaScript (inline SVG chart) |
| Reports | matplotlib |
| Hosting | GitHub Pages (static) |

---

## Run it yourself

### What you need

- **Python 3.12** or newer
- **PostgreSQL 14** or newer, with about **2.5 GB** of free disk space
- **Git**
- An internet connection (the first run downloads every dataset Ontario has published)

### 1. Install

```bash
git clone https://github.com/alexbilat/Sunshine-List-Scraper.git
cd Sunshine-List-Scraper
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

### 2. Create a database

In `psql`, as the `postgres` superuser:

```sql
CREATE ROLE sunshine LOGIN PASSWORD 'choose-a-password';
CREATE DATABASE sunshine OWNER sunshine;
```

### 3. Point the project at it

The connection string is read **only** from an environment variable, so a
password can never end up in the code (see `.env.example`).

```powershell
# Windows (saved for your user; open a new terminal afterwards)
setx SUNSHINE_DATABASE_URL "postgresql://sunshine:choose-a-password@localhost:5432/sunshine"
```

```bash
# macOS / Linux (add to ~/.bashrc or ~/.zshrc to keep it)
export SUNSHINE_DATABASE_URL='postgresql://sunshine:choose-a-password@localhost:5432/sunshine'
```

### 4. Create the tables and load the data

```bash
python -m sunshine_scraper.storage migrate
python sunshine_list_scraper.py
```

The first run downloads all ~3.3 million records, so give it some time. It
writes `output.txt` (every record, tab-separated) and two charts, and prints a
per-year summary.

### 5. Open the website

```bash
uvicorn sunshine_scraper.api.app:app
```

Visit <http://127.0.0.1:8000/> for the website or <http://127.0.0.1:8000/docs>
for interactive API documentation.

### 6. Publish your own public copy (optional)

If you forked the repository:

```bash
python publish_site.py
```

This builds the static site from your database and pushes it to a `gh-pages`
branch. GitHub Pages serves it at `https://<your-user>.github.io/<repository>/`
(if it doesn't start automatically, enable it under **Settings → Pages →
Deploy from a branch → `gh-pages`**). Use `--no-push` to build a local preview
in `site/` instead.

### Everyday commands

| Task | Command |
| --- | --- |
| Get Ontario's latest data | `python sunshine_list_scraper.py` |
| Publish the public site | `python publish_site.py` |
| Run the local website and API | `uvicorn sunshine_scraper.api.app:app` |
| Top salaries from the terminal | `python -m sunshine_scraper.storage top --year 2025 --limit 10` |
| Check the database connection | `python -m sunshine_scraper.storage check` |
| Show pending schema changes | `python -m sunshine_scraper.storage migrate --status` |
| Run the tests | `python -m unittest discover -s tests -v` |

To keep data fresh on Windows, schedule `daily_update.cmd` to run daily in Task
Scheduler. It runs the scraper, then publishes the site only if the scraper
succeeded, and logs to `logs\update-YYYY-MM-DD.log` (about a month is kept).
On other systems, schedule the first two commands with `cron`. Runs where
nothing changed finish in about a minute.

---

## API

Available while the local server is running. All endpoints are `GET` and return JSON.

| Endpoint | Returns |
| --- | --- |
| `/api/health` | `{"status": "ok"}` when the database answers |
| `/api/years` | Headcount and average salary for each year |
| `/api/titles/top?limit=10` | Most common job titles (`limit` 1–100) |
| `/api/salaries/top?year=2025&limit=10` | Highest salaries in a year (`limit` 1–100) |
| `/api/people?first_name=Jane&last_name=Doe` | Every disclosure for one exact name; case and accents ignored |

```json
GET /api/salaries/top?year=2025&limit=1

[{"name": "Kenneth Hartwick", "first_name": "Kenneth", "last_name": "Hartwick",
  "employer": "Ontario Power Generation", "salary_cents": 190740869, "salary": "1907408.69"}]
```

Errors: `422` for invalid parameters (the body says which), `429` when the rate
limit is reached (wait `Retry-After` seconds), `503` when the database is
unavailable.

## Configuration

Everything except the database URL lives in [`config.py`](config.py): output
paths, download timeouts and retries, `full_refresh` (reload every dataset),
log level, API limits (60 requests/minute per client, 4 concurrent queries,
5-second query timeout), and the static-site folder and branch.

## Project structure

```
sunshine_list_scraper.py   Scraper entry point: sync the database, then export
publish_site.py            Build the static site and push it to GitHub Pages
daily_update.cmd           Windows daily job: scrape, then publish if it succeeded
config.py                  Settings (everything except the database URL)
migrations/                Numbered, checksummed SQL schema files
sunshine_scraper/
├── client.py              HTTP with retries; dataset discovery and downloads
├── processing.py          Column-name aliases and text normalization
├── sync.py                Change detection, validation, one transaction per dataset
├── pipeline.py            Sync, then export TSV, summary, and charts
├── export.py              Atomic TSV writer
├── reporting.py           Console summary and matplotlib charts
├── static_site.py         Static site builder and GitHub Pages publisher
├── storage/               Models, connection, migrations, bulk writer, queries
├── api/                   FastAPI app, response schemas, rate limiter
└── web/                   The website (HTML, CSS, JavaScript)
tests/                     Unit and integration tests
assets/                    Images used in this README
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The suite runs offline and needs no database. To include the real-PostgreSQL
integration tests, set `SUNSHINE_TEST_DATABASE_URL` to a **separate, empty**
database; those tests create and drop their own schemas in it.

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `SUNSHINE_DATABASE_URL is required` / website says *Database unavailable* | Set the variable (step 3) in the terminal you're using, then restart. |
| Scraper says migrations are pending | `python -m sunshine_scraper.storage migrate` |
| `ModuleNotFoundError: config` | Run commands from the project folder. |
| Some datasets failed (exit code 1) | Usually a temporary network problem. Run the scraper again; it retries only what's missing. |
| `publish_site.py` reports `git push failed` | Make sure `git push` works from the project folder. |

## Licence

The code is released under the [MIT License](LICENSE).

Salary data © King's Printer for Ontario, published under the
[Open Government Licence – Ontario](https://www.ontario.ca/page/open-government-licence-ontario).
This project is independent and not affiliated with the Government of Ontario.
