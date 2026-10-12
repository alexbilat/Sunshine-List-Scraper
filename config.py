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

# False skips datasets Ontario reports as unchanged since the last successful
# load (HTTP 304 or an unchanged CKAN timestamp). True reloads every dataset,
# e.g. after changing validation rules. The database URL is NOT set here: put
# it in the SUNSHINE_DATABASE_URL environment variable (see .env.example).
full_refresh = False

# Web API protection (sunshine_scraper/api). Each client address may send up
# to api_rate_limit_requests requests per api_rate_limit_window seconds; extra
# requests get HTTP 429 with a Retry-After header. A short burst is allowed,
# but the long-run rate cannot exceed the limit. Limits are per server process.
api_rate_limit_requests = 60
api_rate_limit_window = 60

# Milliseconds a single API query may run before PostgreSQL cancels it and the
# client gets 503. Keeps one slow query from holding a worker indefinitely.
api_statement_timeout_ms = 5000

# How many API requests may query PostgreSQL at once; others queue for up to
# api_query_wait_seconds, then get 503. Many simultaneous heavy queries slow
# each other down until they all hit the timeout above, so a small number
# that finishes quickly serves more people than a large number that doesn't.
api_max_concurrent_queries = 4
api_query_wait_seconds = 10

# Public static website (publish_site.py). The site is built into site_dir
# (replaced on each build) and pushed to pages_branch, which GitHub Pages
# serves. That branch is overwritten on every publish; use it for nothing else.
site_dir = 'site'
pages_branch = 'gh-pages'

# INFO shows progress plus warnings/errors. DEBUG adds page/row diagnostics.
# WARNING hides ordinary progress; ERROR shows only failures.
# CRITICAL is available in Python but is not used by this scraper.
log_level = 'INFO'
