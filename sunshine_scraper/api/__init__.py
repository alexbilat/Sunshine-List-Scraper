"""Read-only web API: HTTP routes that serve database reads as JSON.

The application object lives in sunshine_scraper.api.app. This package reuses
the storage layer's repository and connection code; it never scrapes or writes.
"""
