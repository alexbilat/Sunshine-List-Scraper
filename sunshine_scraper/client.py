"""Bounded HTTP retries and validation of Ontario CKAN responses."""
import logging
import math
import time
from urllib.parse import urlsplit

import requests
from bs4 import BeautifulSoup
from .errors import ScraperError

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


def request_page(url, *, params=None, timeout=30, max_retries=2, backoff=1):
    """Retry transient GET failures; max_retries excludes the first attempt."""
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0):
        raise ScraperError("Timeout must be a positive finite number")
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ScraperError("max_retries must be a nonnegative integer")
    if (isinstance(backoff, bool) or not isinstance(backoff, (int, float))
            or not math.isfinite(backoff) or backoff < 0):
        raise ScraperError("Retry backoff must be a nonnegative finite number")
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as error:
            reason = type(error).__name__
        except requests.RequestException as error:
            raise ScraperError(f"Request failed for {url}: {error}") from error
        else:
            if response.status_code == 200:
                return response
            reason = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUSES:
                raise ScraperError(f"{reason} from {url}; not retrying")
        if attempt == max_retries:
            raise ScraperError(f"{reason} from {url}; exhausted {attempt + 1} attempts")
        delay = backoff * (2 ** attempt)
        logger.warning("%s; retry %s/%s in %.1fs (%s)", reason, attempt + 1,
                       max_retries, delay, url)
        time.sleep(delay)
    raise ScraperError("No request attempts were made")


def discover_resource_links(url, **request_options):
    response = request_page(url, **request_options)
    soup = BeautifulSoup(response.content, 'html.parser')
    links = []
    seen = set()
    for link in soup.find_all('a', href=True):
        href = link['href']
        if 'public-sector-salary-disclosure' not in href.lower() or 'resource' not in href.lower():
            continue
        resource_id = urlsplit(href).path.rstrip('/').split('/')[-1]
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
    """Return a complete resource or raise; never return a failed partial resource."""
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise ScraperError("page_size must be a positive integer")
    records = []
    offset = 0
    while True:
        try:
            response = request_page(api_url, params={'resource_id': resource_id,
                'limit': page_size, 'offset': offset}, **request_options)
            try:
                data = response.json()
            except ValueError as error:
                raise ScraperError("Response is not valid JSON") from error
            if not isinstance(data, dict) or data.get('success') is not True:
                raise ScraperError("CKAN response does not report success=true")
            result = data.get('result')
            if not isinstance(result, dict) or not isinstance(result.get('records'), list):
                raise ScraperError("CKAN response is missing result.records as a list")
            batch = result['records']
            if len(batch) > page_size:
                raise ScraperError("CKAN returned more records than the requested page size")
            if len(batch) == page_size and records[-page_size:] == batch:
                raise ScraperError("CKAN repeated the previous full page; pagination stopped")
        except ScraperError as error:
            raise ScraperError(f"Resource {resource_id}, offset {offset}: {error}") from error
        records.extend(batch)
        logger.debug("Resource %s offset %s: fetched %s rows", resource_id, offset, len(batch))
        if len(batch) < page_size:
            return records
        offset += page_size
