"""Bounded HTTP retries and validation of Ontario CKAN responses."""
import logging
import math
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from .errors import ScraperError

logger = logging.getLogger(__name__)
# Retry only failures that may clear up without changing the request.
# 429 means rate limiting; the selected 5xx codes indicate server/gateway errors.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def request_page(url, *, params=None, timeout=30, max_retries=2, backoff=1):
    """Return an HTTP 200 response, or raise ScraperError after a failure.

    timeout is a connection/read timeout in seconds, not a whole-run deadline.
    max_retries counts extra attempts: 2 retries means at most 3 requests.
    The * requires options to be named, e.g. request_page(url, timeout=30).
    """
    # bool is a subclass of int in Python; reject True/False as numeric settings.
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ScraperError("Timeout must be a positive finite number")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ScraperError("max_retries must be a nonnegative integer")
    if (isinstance(backoff, bool) or not isinstance(backoff, (int, float))
            or not math.isfinite(backoff) or backoff < 0):
        raise ScraperError("Retry backoff must be a nonnegative finite number")
    total_attempts = max_retries + 1
    for attempt in range(total_attempts):
        try:
            response = requests.get(url, params=params, timeout=timeout)
        # These failures can occur without receiving an HTTP response.
        except (requests.Timeout, requests.ConnectionError) as error:
            reason = type(error).__name__
        except requests.RequestException as error:
            raise ScraperError(f"Request failed for {url}: {error}") from error
        else:
            # This block runs only when requests.get did not raise an exception.
            if response.status_code == 200:
                return response
            reason = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUSES:
                raise ScraperError(f"{reason} from {url}; not retrying")
        # Both a temporary HTTP error and a connection failure reach here.
        # Never sleep after the last attempt: there is nothing left to retry.
        if attempt == max_retries:
            raise ScraperError(f"{reason} from {url}; exhausted {attempt + 1} attempts")
        # Exponential backoff: with backoff=1, waits are 1s, 2s, 4s, ...
        delay = backoff * (2 ** attempt)
        logger.warning("%s; retry %s/%s in %.1fs (%s)", reason, attempt + 1,
                       max_retries, delay, url)
        time.sleep(delay)
    # Defensive fallback; validated settings always allow at least one attempt.
    raise ScraperError("No request attempts were made")


def discover_resource_links(url, **request_options):
    """Find resource links once per ID while preserving source-page order.

    **request_options collects named options (such as timeout) into a dict.
    Passing **request_options forwards them as named arguments to request_page.
    """
    response = request_page(url, **request_options)
    soup = BeautifulSoup(response.content, 'html.parser')
    links = []
    seen = set()
    for link in soup.find_all('a', href=True):
        href = link['href']
        lowercase_href = href.lower()
        if 'public-sector-salary-disclosure' not in lowercase_href or 'resource' not in lowercase_href:
            continue
        # Ignore query strings and trailing slashes when identifying a resource.
        resource_path = urlsplit(href).path.rstrip('/')
        resource_id = resource_path.split('/')[-1]
        if resource_id in seen:
            logger.debug("Skipping repeated resource link: %s", resource_id)
            continue
        seen.add(resource_id)
        links.append(href)
    if not links:
        raise ScraperError("No disclosure resource links found; the source page may have changed")
    logger.info("Discovered %s resources", len(links))
    return links


def fetch_all_records(api_url, resource_id, *, page_size=100000, **request_options):
    """Return every page for one resource, or raise ScraperError.

    A later-page failure discards this function's partial results. The pipeline
    can then skip this dataset without mistaking partial coverage for success.
    """
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise ScraperError("page_size must be a positive integer")
    records = []
    offset = 0
    while True:
        try:
            # Offset is how many records to skip before starting the next page.
            query_parameters = {
                'resource_id': resource_id,
                'limit': page_size,
                'offset': offset,
            }
            response = request_page(api_url, params=query_parameters, **request_options)
            try:
                data = response.json()
            except ValueError as error:
                raise ScraperError("Response is not valid JSON") from error
            # HTTP 200 only confirms delivery; CKAN can still report a failure.
            if not isinstance(data, dict) or data.get('success') is not True:
                raise ScraperError("CKAN response does not report success=true")
            result = data.get('result')
            if not isinstance(result, dict) or not isinstance(result.get('records'), list):
                raise ScraperError("CKAN response is missing result.records as a list")
            batch = result['records']
            if len(batch) > page_size:
                raise ScraperError("CKAN returned more records than the requested page size")
            # Detect a server ignoring offset and repeatedly returning one page.
            previous_page = records[-page_size:]
            if len(batch) == page_size and previous_page == batch:
                raise ScraperError("CKAN repeated the previous full page; pagination stopped")
        except ScraperError as error:
            # Add location context; "from error" preserves the original cause.
            raise ScraperError(f"Resource {resource_id}, offset {offset}: {error}") from error
        records.extend(batch)
        logger.debug("Resource %s offset %s: fetched %s rows", resource_id, offset, len(batch))
        # A short (including empty) page means this dataset is exhausted.
        if len(batch) < page_size:
            return records
        offset += page_size
