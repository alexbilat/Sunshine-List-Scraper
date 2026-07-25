# Ontario Sunshine List Scraper

A Python script that pulls every public record from the [Ontario Public Sector Salary Disclosure](https://www.ontario.ca/page/public-sector-salary-disclosure) ("Sunshine List") - every public employee in Ontario who earned over $100,000 in a given year — and turns it into a clean, deduplicated dataset with summary charts.

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

## Setup

```bash
pip install requests beautifulsoup4 matplotlib
```

This will:
- Print progress for each dataset as it's processed
- Write all records to `output.txt`
- Print average salary and headcount per year to the console
- Save `chart_yearly.png` and `chart_titles.png` in the working directory

