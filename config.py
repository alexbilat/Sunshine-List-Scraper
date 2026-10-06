"""Settings you can edit without changing the scraper's implementation.

Relative output paths are resolved from the directory where you run Python.
"""
# Discovery reads Ontario's webpage and download list. Historical records use
# CKAN; newer years use Ontario's official English CSV downloads.
url = 'https://www.ontario.ca/page/public-sector-salary-disclosure'
api_url = 'https://data.ontario.ca/api/3/action/datastore_search'

# Choose filenames or paths to existing directories; directories are not created.
output_path = 'output.txt'
yearly_chart_path = 'chart_yearly.png'
titles_chart_path = 'chart_titles.png'

# Seconds allowed for connection/read waiting, not a deadline for the entire run.
request_timeout = 30

# Extra attempts after the first: 2 retries gives up to 3 attempts per request.
max_retries = 2

# Starting retry delay in seconds. A value of 1 gives waits of 1s, then 2s.
retry_backoff = 1

# INFO shows progress plus warnings/errors. DEBUG adds page/row diagnostics.
# WARNING hides ordinary progress; ERROR shows only failures.
# CRITICAL is available in Python but is not used by this scraper.
log_level = 'INFO'
