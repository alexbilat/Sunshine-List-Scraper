# Ontario Sunshine List Scraper

Downloads Ontario's [Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure)
(the "Sunshine List": every public sector employee paid $100,000 or more in a
year, from 1996 to today), stores it in PostgreSQL, and lets you explore it
through a website, a JSON API, a TSV export, and summary charts.

**Live site:** <https://alexbilat.github.io/Sunshine-List-Scraper/>

![Headcount and average salary by year](Example_output/chart_yearly.png)

## Features

- **Complete, automatic collection.** Finds every published dataset on
  Ontario's disclosure page: historical years through Ontario's CKAN open-data
  API, newer years as official CSV downloads. New years are picked up
  automatically; no years or file IDs are hardcoded.
- **Fast updates.** Later runs ask Ontario what changed and skip everything
  else, so a routine update takes about a minute.
- **Clean data.** Salaries are stored as exact cents; column-name variations,
  stray whitespace, and non-person rows are handled; duplicates are merged.
- **Website.** Browse the top salaries for any year, yearly headcount and
  average salary, and the most common job titles.
- **Free, always-up public site.** One command publishes the website as static
  files to GitHub Pages; it needs no server or database to stay online.
- **Read-only JSON API** for local use, with interactive docs, rate limiting,
  and query limits.
- **Exports.** `output.txt` (all ~3.3 million records, tab-separated) plus two charts.

## How it works

```
                         ┌───────────── your computer ─────────────┐
 Ontario open data ──►   scraper ──► PostgreSQL ──► local website + JSON API
 (CKAN API + CSVs)                       │          (while you run it)
                                         ├──► output.txt + charts
                                         └──► publish_site.py ──► GitHub Pages
                         └─────────────────────────────────────────┘   (public, always up)
```

- The **scraper** (`sunshine_list_scraper.py`) syncs Ontario's data into your
  local PostgreSQL database and exits.
- The **local web server** serves the website and the live JSON API from that
  database, only while you have it running.
- **`publish_site.py`** turns the database into a static copy of the website
  (pre-computed JSON files) and pushes it to GitHub Pages. The public site
  looks and works the same as the local one, but never contacts your computer,
  so it stays up when your PC is off. It changes only when you publish.

---

## Setup

You need:

| Requirement | Notes |
| --- | --- |
| Python 3.12+ | [python.org](https://www.python.org/downloads/) |
| PostgreSQL 14+ | [postgresql.org/download](https://www.postgresql.org/download/). The database needs about **2.5 GB** of disk space. |
| Git | To clone the repository. |

Commands below are for **Windows PowerShell**; macOS/Linux equivalents follow
each block where they differ. Run everything from the project folder.

### 1. Get the code and install dependencies

```powershell
git clone https://github.com/alexbilat/Sunshine-List-Scraper.git
cd Sunshine-List-Scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

```bash
# macOS / Linux
source .venv/bin/activate
```

> If PowerShell refuses to run `Activate.ps1`, run
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.
> Activate the virtual environment again in every new terminal.

### 2. Create the database

Open `psql` as the `postgres` superuser (on Windows: **SQL Shell (psql)** in
the Start menu) and run:

```sql
CREATE ROLE sunshine LOGIN PASSWORD 'choose-a-password';
CREATE DATABASE sunshine OWNER sunshine;
```

### 3. Tell the project where the database is

The connection URL is read **only** from the `SUNSHINE_DATABASE_URL`
environment variable, never from a file, so the password can't be committed by
accident. `.env.example` shows the format.

```powershell
# Save it for your Windows user (open a new terminal afterwards):
setx SUNSHINE_DATABASE_URL "postgresql://sunshine:choose-a-password@localhost:5432/sunshine"

# Or for the current terminal only:
$env:SUNSHINE_DATABASE_URL = 'postgresql://sunshine:choose-a-password@localhost:5432/sunshine'
```

```bash
# macOS / Linux (add to ~/.bashrc or ~/.zshrc to keep it)
export SUNSHINE_DATABASE_URL='postgresql://sunshine:choose-a-password@localhost:5432/sunshine'
```

### 4. Create the tables

```powershell
python -m sunshine_scraper.storage migrate
python -m sunshine_scraper.storage check     # confirms the connection works
```

### 5. Load the data

```powershell
python sunshine_list_scraper.py
```

The first run downloads and stores everything: about 3.3 million records,
which takes a while. When it finishes you have:

- the data in PostgreSQL,
- `output.txt` with every record,
- `chart_yearly.png` and `chart_titles.png`,
- a per-year summary in the console.

It exits with code `0` on success and `1` if any dataset failed (everything
that did load is kept, and the next run retries the rest).

### 6. Start the website

```powershell
uvicorn sunshine_scraper.api.app:app
```

Open **<http://127.0.0.1:8000/>**. Press `Ctrl+C` to stop the server. Add
`--reload` while editing code so the server restarts on every save.

### 7. Publish the public website

```powershell
python publish_site.py
```

This reads the database (it never changes it), builds the site into `site/`,
and pushes it to the `gh-pages` branch of your GitHub repository. GitHub Pages
shows the update within a minute or two at
`https://<your-user>.github.io/<repository>/`.

**One-time GitHub setup** (before or after the first publish): in the
repository on GitHub, open **Settings → Pages**, set **Source** to *Deploy from
a branch*, choose branch **`gh-pages`** and folder **`/ (root)`**, and save.
GitHub Pages is free for public repositories.

To preview without publishing:

```powershell
python publish_site.py --no-push
python -m http.server --directory site 8001     # then open http://127.0.0.1:8001/
```

## Updating the public site

Whenever you want the public site to show new data:

```powershell
python sunshine_list_scraper.py     # 1. fetch Ontario's latest data
python publish_site.py              # 2. publish it
```

If the database is empty or the build fails, nothing is pushed and the current
public site stays as it is. Each publish replaces the `gh-pages` branch with a
single fresh commit, so the repository doesn't grow with every update; don't
use that branch for anything else.

---

## Using the website

The public site and the local one have the same three tabs:

| Tab | What it shows |
| --- | --- |
| **Top salaries** | The highest salaries for a chosen year (top 10 to 100). |
| **Years overview** | People listed and average salary for every year, with a chart. |
| **Common job titles** | The most frequent job titles across all years. |

The header shows when the public site's data was published, or, locally,
whether the database is reachable.

## API

The live API runs only on your computer, while the local server is running
(step 6). All endpoints are `GET` and return JSON. Try them interactively at
<http://127.0.0.1:8000/docs>.

| Endpoint | Returns |
| --- | --- |
| `/api/health` | `{"status": "ok"}` when the database answers |
| `/api/years` | Headcount and average salary for each year |
| `/api/titles/top?limit=10` | Most common job titles (`limit` 1–100) |
| `/api/salaries/top?year=2024&limit=10` | Highest salaries in a year (`limit` 1–100) |

Money is sent as exact integer cents plus a display string, e.g.
`"salary_cents": 12345678, "salary": "123456.78"`; floats are never used.

| Status | Meaning |
| --- | --- |
| `422` | Invalid parameter; the body says which and why |
| `429` | Rate limit reached; wait for the number of seconds in `Retry-After` |
| `503` | Database unreachable or busy; try again later |

### Built-in protection

- **Read-only:** only `GET` routes exist, and every database transaction is
  `READ ONLY`.
- **Rate limit:** 60 API requests per minute per client address (bursts allowed).
- **Query limits:** at most 4 queries run at once (others wait briefly), and
  any query is cancelled after 5 seconds.
- **Browser security headers:** a strict Content-Security-Policy, `nosniff`,
  and anti-framing headers. The page renders all data as text, never as HTML.
- **No secrets in errors:** database failures return a generic message;
  details go only to the server log.

---

## Configuration

Edit `config.py` (the database URL is the only setting that lives elsewhere).

| Setting | Default | Purpose |
| --- | --- | --- |
| `output_path`, `yearly_chart_path`, `titles_chart_path` | project folder | Where exports go. The folder must already exist. |
| `full_refresh` | `False` | `True` reloads every dataset, e.g. after changing validation rules. |
| `log_level` | `INFO` | `DEBUG` for detailed scraper diagnostics. |
| `request_timeout`, `max_retries`, `retry_backoff` | 30 s, 2, 1 s | Download behaviour. |
| `api_rate_limit_requests`, `api_rate_limit_window` | 60, 60 s | API rate limit per client. |
| `api_statement_timeout_ms` | 5000 | Maximum time for one API query. |
| `api_max_concurrent_queries`, `api_query_wait_seconds` | 4, 10 s | Concurrent query cap and how long requests queue. |
| `site_dir`, `pages_branch` | `site`, `gh-pages` | Where the static site is built, and the branch it is published to. |

## Keeping the data up to date

Ontario publishes a new year each spring and occasionally corrects earlier
files. Running the scraper on a schedule keeps your local database current
(the public site still changes only when you run `publish_site.py`); runs
where nothing changed finish quickly, and only one sync can run at a time, so
overlapping runs are harmless.

- **Windows:** Task Scheduler → *Create Basic Task* → daily → program
  `C:\path\to\Sunshine-List-Scraper\.venv\Scripts\python.exe`, arguments
  `sunshine_list_scraper.py`, *Start in* the project folder. Set
  `SUNSHINE_DATABASE_URL` with `setx` so the task can see it.
- **macOS / Linux (cron):**
  ```cron
  0 6 * * * cd /path/to/Sunshine-List-Scraper && SUNSHINE_DATABASE_URL=... .venv/bin/python sunshine_list_scraper.py
  ```

## Output file format

`output.txt` is UTF-8, tab-separated, with a header row, sorted by salary
(highest first). Columns: `Name`, `Salary` (dollars, two decimals), `Job Title`,
`Employer`, `Year`, `UUID` (the dataset where the record was first seen).

```python
import csv

with open('output.txt', encoding='utf-8', newline='') as source:
    for record in csv.DictReader(source, delimiter='\t'):
        print(record['Name'], record['Salary'])
```

In a spreadsheet, import it as UTF-8 with a tab delimiter.

## Database

| Table | Holds |
| --- | --- |
| `salary_records` | One row per distinct disclosure; salary in exact cents |
| `source_resources` | Each dataset discovered, and its change-detection state |
| `disclosure_sources` | Which datasets each disclosure appeared in |
| `sync_runs`, `sync_run_resources` | What each scraper run did, per dataset, including errors |
| `schema_migrations` | Which migration files have been applied |

Records are never deleted. If Ontario changes a salary, the new value is
stored as a new record.

Useful commands (all use `SUNSHINE_DATABASE_URL`):

```powershell
python -m sunshine_scraper.storage check                # connectivity check
python -m sunshine_scraper.storage top --year 2024 --limit 10
python -m sunshine_scraper.storage migrate --status     # applied / pending migrations
python -m sunshine_scraper.storage migrate              # apply pending migrations
```

Check recent runs in `psql`:

```sql
SELECT id, started_at, status, resources_loaded, resources_unchanged, resources_failed
FROM sync_runs ORDER BY id DESC LIMIT 5;
```

Back up and restore (keep dumps outside the repository):

```powershell
pg_dump -h localhost -U sunshine -d sunshine -Fc -f sunshine.dump
pg_restore -h localhost -U sunshine -d an_empty_database sunshine.dump
```

Schema changes go in new numbered files in `migrations/`; see
[`migrations/README.md`](migrations/README.md).

## Tests

```powershell
python -m unittest discover -s tests -v
```

The suite runs offline and needs no database. To include the real-PostgreSQL
tests, set `SUNSHINE_TEST_DATABASE_URL` to a **separate, dedicated** database
(e.g. `sunshine_test`); those tests create and drop their own schemas in it.

## Project structure

```
sunshine_list_scraper.py     CLI entry point: run a sync, then export
publish_site.py              Build the static site and push it to GitHub Pages
config.py                    All settings except the database URL
migrations/                  Numbered SQL schema files
sunshine_scraper/
  client.py                  HTTP with retries; dataset discovery and downloads
  processing.py              Column-name aliases and text normalization
  sync.py                    Change detection, validation, one transaction per dataset
  pipeline.py                Sync, then export TSV, summary, and charts
  export.py, reporting.py    TSV writer; summary and charts
  errors.py                  ScraperError
  storage/                   Models, connection, migrations, writer, repository
  static_site.py             Static site builder and GitHub Pages publisher
  api/                       FastAPI app, response schemas, rate limiter
  web/                       Website (plain HTML, CSS, JavaScript; no build step)
tests/                       unittest suite
Example_output/              Sample charts
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `SUNSHINE_DATABASE_URL is required`, or the website says *Database unavailable* | The variable isn't set in that terminal. Set it (step 3) and restart. |
| Scraper says migrations are pending | `python -m sunshine_scraper.storage migrate` |
| `ModuleNotFoundError: config` | Run commands from the project folder. |
| Website shows *No data yet* | Load the data first (step 5). |
| Some datasets failed (exit code 1) | Usually a temporary network problem; run the scraper again. Details are in the log and in `sync_run_resources`. |
| Port 8000 already in use | `uvicorn sunshine_scraper.api.app:app --port 8080` |
| `publish_site.py`: `git push failed` | Check that you can push to GitHub from this folder (`git push` works) and that `origin` is your repository. |
| Public site shows a 404 | Turn on GitHub Pages for the `gh-pages` branch (step 7), then wait a minute. |
| Public site shows old data | Run `python publish_site.py` again; browsers may cache files for up to 10 minutes. |

## Data source

Data © King's Printer for Ontario, published under the
[Open Government Licence – Ontario](https://www.ontario.ca/page/open-government-licence-ontario).
This project is not affiliated with the Government of Ontario.
