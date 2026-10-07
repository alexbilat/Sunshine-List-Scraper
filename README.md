# Ontario Sunshine List Scraper

A Python script that pulls every public record from the [Ontario Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure) ("Sunshine List") - every public employee in Ontario who earned over $100,000 in a given year - and turns it into a clean, deduplicated dataset with summary charts.

Instead of scraping rendered HTML tables, the script finds the datasets linked on Ontario's disclosure page. Historical resources are read through Ontario's [CKAN open data API](https://data.ontario.ca/api/3/action/datastore_search); newer years are downloaded as English CSV files using Ontario's [official download list](https://www.ontario.ca/public-sector-salary-disclosure_artifacts/pssdfiles.json).

## What it does

1. **Finds the published datasets.** Collects historical CKAN resource links and resolves newer main-list/addendum pages to their English CSV downloads. New years are included when Ontario adds them to the disclosure page and download list; the latest year and file addresses are not hardcoded.
2. **Downloads the records.** Requests CKAN resources in batches of 100,000 until exhausted and reads complete CSV downloads for newer years. A missing advertised CSV or malformed download is reported as a failure instead of silently omitting that year.
3. **Cleans the data.**
   - Normalizes salary fields (strips `$` and `,`, handles missing or malformed values).
   - Matches column labels despite capitalization, extra spaces, or underscores, and recognizes aliases such as `Surname`/`Last Name`, `Position`/`Job Title`, `Salary Paid`/`Salary`, and `Calendar Year`/`Year`.
   - Strips non-breaking spaces and collapses irregular whitespace in names, titles, and employers.
   - Filters out non-person records that occasionally show up in the raw data.
4. **Deduplicates across datasets.** Some records appear more than once across different UUIDs. The script builds a composite key (name, title, employer, year, salary) to catch and skip duplicates.
5. **Outputs the results.**
   - A tab-separated `output.txt` file with every record, sorted by salary (highest first).
   - A console summary of average salary and number of people per year.
   - Two charts: headcount and average salary by year, and the 10 most common job titles.

![Example_Output](Example_output/chart_titles.png)
![Example_Output](Example_output/chart_yearly.png)



## Setup

```bash
pip install -r requirements.txt
python Sunshine_List_Scaper.py
```

This will:
- Print progress for each dataset as it's processed
- Write all records to `output.txt`
- Print average salary and headcount per year to the console
- Save `chart_yearly.png` and `chart_titles.png` in the working directory


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
`Salary` is expressed in dollars; `UUID` identifies the source resource.

## Project structure

The entry point is `Sunshine_List_Scaper.py`; edit URLs and output paths in `config.py`. Collection, processing, export, reporting, and coordination live in the `sunshine_scraper/` package. Start with [the application learning guide](learning/README.md) for the complete execution flow, a record-by-record walkthrough, Python explanations, architectural decisions, and the next database step.

## v0.3 — Error handling and logging

Requests have configurable timeouts and bounded retries. Invalid API responses and rows are handled explicitly; duplicate records are counted. Progress, warnings, and failures use Python logging. Set `log_level` in `config.py` to `DEBUG` for detailed diagnostics.

A run with failed datasets exports usable results and exits with status 1 to identify incomplete coverage. A run with no usable records preserves existing outputs. TSV export uses a temporary file and replacement to protect the previous output on write failures.

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

## Learn the code before adding a database

The [learning folder](learning/README.md) explains the app for users and contributors:

- [Full application flow and module responsibilities](learning/01-app-flow.md)
- [Follow one resource link and disclosure](learning/02-follow-one-record.md)
- [Python constructs, errors, logging, and tests](learning/03-python-and-errors.md)
- [PostgreSQL foundation and architecture review](learning/04-postgresql-architecture.md)

`sunshine_scraper/database.py` is a standalone read-only query practice module, not
yet connected to the scraper. It requires an existing database/table. Running the
scraper still writes TSV and charts; it does not create or populate `sunshine.db`.
See the database chapter before running the practice query or adding persistence.

## PostgreSQL foundation

The new `sunshine_scraper/storage/` package provides an exact-money disclosure
model, environment-based connection settings, and a parameterized read repository.
`migrations/001_disclosure_foundation.sql` proposes three tables for disclosure
contents, source resources, and their many-to-many provenance relationships.

This is preparation for persistence: the normal scraper still exports files and
does not call the database. The foundation does not yet ingest rows, apply
corrections, schedule refreshes, or serve an API. Start with the
[architecture review](learning/04-postgresql-architecture.md) for the design,
limitations, optional setup, and decisions to make together.

PostgreSQL support is optional (`requirements-postgres.txt`). Once a server and
`SUNSHINE_DATABASE_URL` are configured, `python -m sunshine_scraper.storage check`
checks connectivity. `python -m sunshine_scraper.storage top --year 2024 --limit 10`
reads an already initialized/populated schema. Neither command creates tables or
downloads data. Credentials belong in the environment; `.env` is ignored and
`.env.example` is a reference, not an automatically loaded configuration file.

The ordinary offline test command also checks the new model and repository.
Real PostgreSQL tests are opt-in through `SUNSHINE_TEST_DATABASE_URL` pointing at
a dedicated test database; otherwise they are skipped.
