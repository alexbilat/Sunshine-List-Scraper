# Scraper architecture and reorganization

## Purpose

This change separates the existing scraper by responsibility. It remains a single Python program that collects data in memory, writes a TSV file, and produces charts. A database, API, and frontend are future work.

## Files and responsibilities

| File | Responsibility |
| --- | --- |
| `Sunshine_List_Scaper.py` | Small command-line entry point: reads configuration, sets console encoding, starts the run, and reports selected errors. The original filename is retained so existing commands still work. |
| `config.py` | Settings only: source URL, CKAN endpoint, TSV path, and chart paths. Libraries now belong to the modules that actually use them. |
| `sunshine_scraper/client.py` | Network access: discovers resource links and fetches every page of a resource using the existing 100,000-record limit and offset logic. |
| `sunshine_scraper/processing.py` | Text normalization, salary conversion, year-field reconciliation, filtering, and deduplication. Accepts records without knowing how they were downloaded. |
| `sunshine_scraper/export.py` | Writes the existing six-column tab-separated output using a context manager to close the file reliably. |
| `sunshine_scraper/reporting.py` | Prints yearly averages and counts, and creates the two existing matplotlib charts. |
| `sunshine_scraper/pipeline.py` | Coordinates the stages and owns state for one complete run. |
| `sunshine_scraper/__init__.py` | Marks the directory as a Python package. |
| `tests/test_scraper.py` | Offline regression checks with mocked HTTP responses and temporary output files. |
| `.gitignore` | Excludes the local virtual environment and Python bytecode from version control. |

## How the pieces fit

The entry point passes settings to `pipeline.run()`. The pipeline discovers links, fetches each resource, and passes its raw records to processing. It then sorts accepted records by descending salary, exports them, prints yearly statistics, and creates charts.

The pipeline owns three collections: accepted records, salaries grouped by year, and a set of deduplication keys. They are created fresh on every run. Processing updates these collections and returns valid and invalid counts for progress messages. Keeping the deduplication set across resources preserves the original cross-UUID behavior. The UUID of the first accepted occurrence is retained.

This deliberately uses ordinary functions and dictionaries rather than adding classes or a framework. The program does not yet need multiple storage backends or an application server. Module boundaries provide useful separation without introducing those abstractions prematurely.

## Preserved behavior

Resource discovery order, pagination, normalized fields, salary fallbacks, missing-year skips, case-insensitive deduplication, descending salary ordering, output columns, chart styling, and yearly summaries are preserved. The invalid-record count still counts only three-field company records; duplicates and missing years do not increment it. Relative output paths still resolve from the current working directory.

## Small intentional improvements

- Imports no longer start a scrape or write files; execution is behind `main()` and the standard main guard.
- Configuration no longer supplies unrelated dependencies through a wildcard import.
- The output file closes even if writing raises an exception.
- Chart paths are configurable alongside the TSV path.
- An empty job-title collection skips the title chart instead of crashing while unpacking an empty list. The yearly chart and TSV still run. No new title chart is written in that case; an older file at the same path is not removed.
- Console encoding is changed only when the output stream supports reconfiguration.
- A failed discovery request or missing output directory produces a nonzero command-line exit status.
- Unused HTML processing and the unused temporary salary collection are removed.

## Current limitations and future extension

This is an architectural refactor, not a reliability or data-model redesign. All accepted records and yearly salary lists remain in memory. Requests still have no timeout or retry policy, and a non-200 CKAN response still logs an error and returns the records fetched so far. The three-field company heuristic and malformed-salary-to-zero rule remain unchanged. The TSV writer still uses the original direct tab-separated formatting rather than adding escaping rules.

When database work begins, the export boundary is a natural place for persistence, although large datasets will eventually need streaming instead of the current in-memory collection. An API could read that stored data independently of scraping. A frontend can then consume the API. Those changes should be designed when their requirements are known; none is implemented here.

## Running and checking

Install with `pip install -r requirements.txt`, edit `config.py`, then run `python Sunshine_List_Scaper.py` from the repository root. No new third-party dependencies were added.

Offline checks cover pagination, data normalization and deduplication, output formatting, pipeline coordination, and chart generation using synthetic records. A full production scrape is not needed to verify this split and was not run.

Run the checks with `python -m unittest discover -s tests -v`. The local `.venv` was created for verification and is ignored by Git.
