# Ontario Sunshine List Scraper

A Python script that pulls every public record from the [Ontario Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure) ("Sunshine List") - every public employee in Ontario who earned over $100,000 in a given year - and turns it into a clean, deduplicated dataset with summary charts.

Instead of scraping rendered HTML tables, the script crawls the disclosure page for resource links, then queries Ontario's [CKAN open data API](https://data.ontario.ca/api/3/action/datastore_search) directly using each dataset's UUID.

## What it does

1. **Finds every dataset.** Scrapes the Sunshine List page with BeautifulSoup to collect the resource links for each year's dataset, then extracts each dataset's UUID from its URL.
2. **Pulls every record.** Ontario's CKAN API caps a single request at 100,000 records. The script works around this with offset-based pagination, requesting in batches of 100,000 until a dataset is exhausted.
3. **Cleans the data.**
   - Normalizes salary fields (strips `$` and `,`, handles missing or malformed values).
   - Reconciles inconsistent column names across dataset years (`Calendar Year` vs `Year` vs `calendar_year`, etc.).
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

## Learn the code before adding a database

The [learning folder](learning/README.md) explains the app for users and contributors:

- [Full application flow and module responsibilities](learning/01-app-flow.md)
- [Follow one resource link and disclosure](learning/02-follow-one-record.md)
- [Python constructs, errors, logging, and tests](learning/03-python-and-errors.md)
- [SQLite recommendation and database implementation plan](learning/04-database-next-step.md)
- [Original refactor decisions and this update's changes](learning/05-architecture-and-changes.md)

`sunshine_scraper/database.py` is a standalone read-only query practice module, not
yet connected to the scraper. It requires an existing database/table. Running the
scraper still writes TSV and charts; it does not create or populate `sunshine.db`.
See the database chapter before running the practice query or adding persistence.
