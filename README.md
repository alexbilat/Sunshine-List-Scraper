# Ontario Sunshine List Scraper

A Python script that pulls every public record from the [Ontario Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure) ("Sunshine List") - every public employee in Ontario who earned over $100,000 in a given year - stores it in a PostgreSQL database, and exports a clean, deduplicated dataset with summary charts.

Instead of scraping rendered HTML tables, the script finds the datasets linked on Ontario's disclosure page. Historical resources are read through Ontario's [CKAN open data API](https://data.ontario.ca/api/3/action/datastore_search); newer years are downloaded as English CSV files using Ontario's [official download list](https://www.ontario.ca/public-sector-salary-disclosure_artifacts/pssdfiles.json).

## What it does

1. **Finds the published datasets.** Collects historical CKAN resource links and resolves newer main-list/addendum pages to their English CSV downloads. New years are included when Ontario adds them to the disclosure page and download list; the latest year and file addresses are not hardcoded.
2. **Skips what hasn't changed.** Before downloading, it asks Ontario whether each dataset changed since the last successful load (HTTP `304 Not Modified` for CSVs, CKAN's modification timestamp for historical resources). Unchanged datasets cost one small request.
3. **Downloads the records.** Requests CKAN resources in batches of 100,000 until exhausted and reads complete CSV downloads for newer years. A missing advertised CSV or malformed download is reported as a failure instead of silently omitting that year.
4. **Cleans the data.**
   - Converts salaries to exact cents (strips `$` and `,`; rejects missing, malformed, negative, or nonfinite values). Published fractions of a cent are rounded half-up to the nearest cent, so `111259.878` becomes `111259.88`.
   - Matches column labels despite capitalization, extra spaces, or underscores, and recognizes aliases such as `Surname`/`Last Name`, `Position`/`Job Title`, `Salary Paid`/`Salary`, and `Calendar Year`/`Year`.
   - Strips non-breaking spaces and collapses irregular whitespace in names, titles, and employers.
   - Filters out non-person records that occasionally show up in the raw data.
5. **Stores it in PostgreSQL.** Each dataset is saved in its own transaction. A disclosure is identified by its contents (name, title, employer, year, salary; case-insensitive): one already stored is refreshed with the newest spelling, and anything new is added. Nothing is deleted, and every dataset a disclosure appeared in is remembered.
6. **Outputs the results from the database.**
   - A tab-separated `output.txt` file with every record, sorted by salary (highest first).
   - A console summary of average salary and number of people per year.
   - Two charts: headcount and average salary by year, and the 10 most common job titles.

![Example_Output](Example_output/chart_titles.png)
![Example_Output](Example_output/chart_yearly.png)



## Setup

You need a running PostgreSQL server (version 14 or newer) and a database owned
by a role that can create tables. Create them in `psql` as the `postgres`
superuser:

```sql
CREATE ROLE sunshine LOGIN PASSWORD 'choose-a-password';
CREATE DATABASE sunshine OWNER sunshine;
```

Then install, point the scraper at the database, create the tables, and run:

```powershell
python -m pip install -r requirements.txt
$env:SUNSHINE_DATABASE_URL = 'postgresql://sunshine:choose-a-password@localhost:5432/sunshine'
python -m sunshine_scraper.storage migrate
python Sunshine_List_Scaper.py
```

The database URL is read from the environment only; never put it in `config.py`
or commit it. `.env.example` shows the format; it is not loaded automatically.

This will:
- Print progress for each dataset as it's processed
- Store new and changed records in PostgreSQL
- Write all stored records to `output.txt`
- Print average salary and headcount per year to the console
- Save `chart_yearly.png` and `chart_titles.png` in the working directory

The first run loads everything (about 3.3 million disclosures). Later runs only
download datasets Ontario has changed. Set `full_refresh = True` in `config.py`
to reload everything, e.g. after changing validation rules.


## Choosing output paths

Edit the three output settings in `config.py` to keep each run's files in a
separate folder. Create that folder before running the scraper:

```python
output_path = 'results/output.txt'
yearly_chart_path = 'results/chart_yearly.png'
titles_chart_path = 'results/chart_titles.png'
```

Relative paths start from the directory where you run Python. Custom output
folders such as `results/` are not covered by the default output ignore rules;
add your folder to your local `.git/info/exclude` if you want to keep it out of Git.

## Reading the exported records

`output.txt` is a UTF-8, tab-separated file with a header row. In a spreadsheet
import dialog, choose UTF-8 encoding and a tab delimiter. Use a TSV-aware reader
to preserve quoted tabs or newlines inside fields:

```python
import csv

with open('output.txt', encoding='utf-8', newline='') as source:
    for record in csv.DictReader(source, delimiter='\t'):
        print(record['Name'], record['Salary'])
```

The columns are `Name`, `Salary`, `Job Title`, `Employer`, `Year`, and `UUID`.
`Salary` is expressed in dollars with exactly two decimals (e.g. `100000.00`).
`UUID` identifies the dataset where the disclosure was first seen; the database
keeps every dataset it appeared in.

## Project structure

The entry point is `Sunshine_List_Scaper.py`; edit URLs and output paths in `config.py`. Collection, processing, export, reporting, and coordination live in the `sunshine_scraper/` package. Start with [the application learning guide](learning/README.md) for the complete execution flow, a record-by-record walkthrough, Python explanations, architectural decisions, and the next database step.

## v0.3 — Error handling and logging

Requests have configurable timeouts and bounded retries. Invalid API responses and rows are handled explicitly; duplicate records are counted. Progress, warnings, and failures use Python logging. Set `log_level` in `config.py` to `DEBUG` for detailed diagnostics.

A run with failed datasets keeps every dataset that loaded, exports from the database, and exits with status 1 to identify incomplete coverage. A failed dataset is rolled back on its own. If the database is empty, existing outputs are preserved. TSV export uses a temporary file and replacement to protect the previous output on write failures. A missing `SUNSHINE_DATABASE_URL`, an unreachable server, or an out-of-date schema stops the run before any download.

Read [Python and error handling](learning/03-python-and-errors.md) for try/except, HTTP status codes, retries, logging levels, validation policies, and exit codes.

Run offline checks:

```bash
python -m unittest discover -s tests -v
```

## Data coverage fixes

Ontario moved newer years (currently 2021 onward) to disclosure pages whose links
do not contain a CKAN resource UUID. Discovery now resolves those pages through
Ontario's download list and reads the corresponding English main and addendum
CSVs. The output's `UUID` column uses the download's UUID directory for these files.

The row reader also recognizes the historical column labels that previously
caused the 2001, 2014, and 2020 main datasets, and several addenda, to be rejected.
Alternative title labels are preserved instead of appearing as blank job titles.
The existing row validity and duplicate rules still apply. These changes do not
apply addendum change/deletion actions; correction handling remains a separate issue.

## Learn the code

The [learning folder](learning/README.md) explains the app for users and contributors:

- [Full application flow and module responsibilities](learning/01-app-flow.md)
- [Follow one resource link and disclosure](learning/02-follow-one-record.md)
- [Python constructs, errors, logging, and tests](learning/03-python-and-errors.md)
- [PostgreSQL architecture and decisions](learning/04-postgresql-architecture.md)

Chapters 1–3 describe the earlier in-memory pipeline; chapter 4 describes how
the database replaced it.

`sunshine_scraper/database.py` is a separate SQLite query practice module. The
scraper does not use it.

## PostgreSQL storage

PostgreSQL is the source of truth. A run syncs Ontario's datasets into the
database, then generates `output.txt`, the summary, and the charts from it.

| Table | Holds |
| --- | --- |
| `salary_records` | One row per distinct disclosure, salary in exact cents |
| `source_resources` | Each discovered dataset and what its last load recorded (ETag, timestamps, content hash) |
| `disclosure_sources` | Which datasets each disclosure appeared in |
| `sync_runs` | One row per run: status and counts |
| `sync_run_resources` | What happened to each dataset in each run, including error messages |
| `schema_migrations` | Which migration files this database has received |

Database commands (all use `SUNSHINE_DATABASE_URL`):

```powershell
python -m sunshine_scraper.storage migrate            # apply new migration files
python -m sunshine_scraper.storage migrate --status   # list applied/pending files
python -m sunshine_scraper.storage check              # read-only connectivity check
python -m sunshine_scraper.storage top --year 2024 --limit 10
```

The scraper never changes the schema itself; it stops and asks you to run
`migrate` when files are pending. A database where `001` was applied by hand
with `psql` can be adopted with `migrate --baseline 001`. See
`migrations/README.md` for how to add a migration.

### Checking what a run did

```sql
SELECT id, started_at, finished_at, status, resources_loaded,
       resources_unchanged, resources_failed
FROM sync_runs ORDER BY id DESC LIMIT 5;

SELECT resource_id, status, rows_valid, rows_inserted, rows_refreshed, error_message
FROM sync_run_resources WHERE run_id = (SELECT max(id) FROM sync_runs);
```

A run that crashed stays `running` with no `finished_at`.

### Running it on a schedule

Only one sync runs at a time: a second run that starts while one is in progress
logs a warning and exits with status 0 without doing anything. A scheduler
(Windows Task Scheduler, cron) can therefore start
`python Sunshine_List_Scaper.py` every 15 minutes. Ontario usually changes
nothing between runs, so most runs only send one small request per dataset.

### Backups

```powershell
pg_dump -h localhost -U sunshine -d sunshine -Fc -f sunshine.dump
pg_restore -h localhost -U sunshine -d an_empty_database sunshine.dump
```

Keep dumps outside the repository.

### Tests

The ordinary offline test command needs no database. Real PostgreSQL tests are
opt-in through `SUNSHINE_TEST_DATABASE_URL`, which must point at a dedicated test
database; each test creates and drops its own schema there.
