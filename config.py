"""User-editable settings. Relative output paths use the working directory."""
url = 'https://www.ontario.ca/page/public-sector-salary-disclosure'
api_url = 'https://data.ontario.ca/api/3/action/datastore_search'
output_path = 'output.txt' # Change to whatever you would like
yearly_chart_path = 'chart_yearly.png'
titles_chart_path = 'chart_titles.png'

# Timeout is in seconds; retries are additional attempts after the first.
request_timeout = 30
max_retries = 2
retry_backoff = 1
log_level = "INFO"  # Use "DEBUG" for per-page and per-row diagnostics.

#| DEBUG | Individual skipped-row reasons, repeated resource links, and page offsets |
#| INFO | Discovery count, per-resource valid/invalid/duplicate counts, yearly summaries, and saved TSV count |
#| WARNING | Retrying a request, invalid-row summaries, missing titles, no title-chart data, and user interruption |
#| ERROR | Failed resource, incomplete run, output/chart failures, or a run that must stop |
#| CRITICAL | Available in Python, but not needed for this command-line scraper