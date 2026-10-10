"""Discover Ontario's CKAN resources and newer CSV downloads; validate requests."""
import csv
from dataclasses import dataclass
from hashlib import sha256
import io
import json
import logging
import math
import re
import time
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from .errors import ScraperError
from .processing import FIELD_ALIASES, normalize_field_name

logger = logging.getLogger(__name__)
# Retry only failures that may clear up without changing the request.
# 429 means rate limiting; the selected 5xx codes indicate server/gateway errors.
RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
DOWNLOAD_MANIFEST_PATH = '/public-sector-salary-disclosure_artifacts/pssdfiles.json'
MODERN_DISCLOSURE_PATH = re.compile(
    r'^/public-sector-salary-disclosure/(\d{4})/'
    r'(all-sectors-and-seconded-employees|addendum)/?$'
)


def resource_id_from_link(link):
    """Identify a CKAN resource page or the UUID directory of a CSV download."""
    parts = urlsplit(link).path.rstrip('/').split('/')
    if parts[-1].lower().endswith('.csv'):
        return parts[-2]
    return parts[-1]


def request_page(url, *, params=None, headers=None, not_modified_ok=False,
                 timeout=30, max_retries=2, backoff=1):
    """Return an HTTP 200 response, or raise ScraperError after a failure.

    timeout is a connection/read timeout in seconds, not a whole-run deadline.
    max_retries counts extra attempts: 2 retries means at most 3 requests.
    The * requires options to be named, e.g. request_page(url, timeout=30).
    not_modified_ok=True also accepts HTTP 304, the reply to a conditional
    request (If-None-Match/If-Modified-Since) whose resource is unchanged.
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
            response = requests.get(url, params=params, headers=headers, timeout=timeout)
        # These failures can occur without receiving an HTTP response.
        except (requests.Timeout, requests.ConnectionError) as error:
            reason = type(error).__name__
        except requests.RequestException as error:
            raise ScraperError(f"Request failed for {url}: {error}") from error
        else:
            # This block runs only when requests.get did not raise an exception.
            if response.status_code == 200 or (not_modified_ok and response.status_code == 304):
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
    """Find historical CKAN links and current English disclosure CSV downloads.

    The landing page links newer years to Ontario pages, not CKAN resources.
    Resolve their main/addendum downloads through Ontario's official manifest.
    Only advertised years are selected; no latest year or file UUID is hardcoded.
    """
    response = request_page(url, **request_options)
    soup = BeautifulSoup(response.content, 'html.parser')
    links = []
    seen = set()
    modern_sources = []
    for link in soup.find_all('a', href=True):
        href = urljoin(url, link['href'])
        modern_match = MODERN_DISCLOSURE_PATH.fullmatch(urlsplit(href).path)
        if modern_match:
            year, page_kind = modern_match.groups()
            kind = 'Compendium' if page_kind == 'all-sectors-and-seconded-employees' else 'Addendum'
            source = (year, kind)
            if source not in modern_sources:
                modern_sources.append(source)
            continue
        lowercase_href = href.lower()
        if 'public-sector-salary-disclosure' not in lowercase_href or 'resource' not in lowercase_href:
            continue
        # Ignore query strings and trailing slashes when identifying a resource.
        resource_id = resource_id_from_link(href)
        if resource_id in seen:
            logger.debug("Skipping repeated resource link: %s", resource_id)
            continue
        seen.add(resource_id)
        links.append(href)
    if modern_sources:
        manifest_url = urljoin(url, DOWNLOAD_MANIFEST_PATH)
        response = request_page(manifest_url, **request_options)
        try:
            manifest = response.json()
        except ValueError as error:
            raise ScraperError("Ontario download manifest is not valid JSON") from error
        if not isinstance(manifest, dict):
            raise ScraperError("Ontario download manifest must be an object")
        for year, kind in modern_sources:
            try:
                download_path = manifest[year][kind]['en']['csv']
            except (KeyError, TypeError) as error:
                raise ScraperError(f"Ontario download manifest is missing the English {year} {kind} CSV") from error
            if not isinstance(download_path, str) or not download_path.strip():
                raise ScraperError(f"Ontario download manifest has an invalid {year} {kind} CSV link")
            download_url = urljoin(manifest_url, download_path)
            parsed_url = urlsplit(download_url)
            if parsed_url.scheme not in ('http', 'https') or not parsed_url.path.lower().endswith('.csv'):
                raise ScraperError(f"Ontario download manifest has an invalid {year} {kind} CSV link")
            resource_id = resource_id_from_link(download_url)
            if resource_id not in seen:
                seen.add(resource_id)
                links.append(download_url)
    if not links:
        raise ScraperError("No disclosure resource links found; the source page may have changed")
    logger.info("Discovered %s resources", len(links))
    return links


def fetch_csv_records(url, **request_options):
    """Read a complete English disclosure CSV, including quoted commas and BOMs.

    As with CKAN collection, a broken download raises instead of returning a
    partial dataset. Individual missing values are handled by row processing.
    """
    response = request_page(url, **request_options)
    return parse_csv_records(response.content, url)


@dataclass(frozen=True)
class CsvDownload:
    """A parsed CSV plus what is needed to recognize it again next time."""

    records: list
    etag: str | None
    last_modified: str | None
    content_sha256: str


def fetch_csv_download(url, *, etag=None, last_modified=None, **request_options):
    """Download a CSV unless the server confirms our stored copy is current.

    Returns None for HTTP 304 Not Modified: the server compared our stored
    ETag/Last-Modified with its file and sent no body. Ontario's download
    server supports this, so an unchanged year costs one tiny request.
    """
    headers = {}
    if etag:
        headers['If-None-Match'] = etag
    if last_modified:
        headers['If-Modified-Since'] = last_modified
    response = request_page(url, headers=headers or None, not_modified_ok=bool(headers),
                            **request_options)
    if response.status_code == 304:
        # A fresh load needs a body; no stored validator means nothing to skip.
        if not headers:
            raise ScraperError(f"CSV {url} returned HTTP 304 without stored validators")
        return None
    return CsvDownload(records=parse_csv_records(response.content, url),
                       etag=response.headers.get('ETag'),
                       last_modified=response.headers.get('Last-Modified'),
                       content_sha256=sha256(response.content).hexdigest())


def parse_csv_records(content, url):
    """Turn downloaded CSV bytes into row dictionaries, or raise ScraperError."""
    try:
        text = content.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        normalized_columns = [normalize_field_name(name) for name in (reader.fieldnames or [])]
        columns = set(normalized_columns)
        # DictReader overwrites repeated headers; normalization can also make
        # differently spelled headers collide during disclosure processing.
        if len(columns) != len(normalized_columns):
            raise ScraperError(f"CSV {url} has duplicate disclosure column headers")
        required_fields = ('first_name', 'last_name', 'employer', 'year', 'salary')
        missing = [name for name in required_fields
                   if not columns.intersection(FIELD_ALIASES[name])]
        if missing:
            raise ScraperError(f"CSV {url} is missing disclosure columns: {', '.join(missing)}")
        records = []
        for row in reader:
            if None in row:
                raise ScraperError(f"CSV {url}, line {reader.line_num}: more values than column headers")
            # Empty cells are valid input for row validation, but absent cells
            # indicate a broken CSV row. Never accept a truncated dataset.
            if any(value is None for value in row.values()):
                raise ScraperError(f"CSV {url}, line {reader.line_num}: fewer values than column headers")
            records.append(row)
        logger.debug("CSV %s: fetched %s rows", url, len(records))
        return records
    except (UnicodeError, csv.Error, ValueError) as error:
        raise ScraperError(f"CSV {url} could not be read: {error}") from error


def fetch_ckan_resource_version(api_url, resource_id, **request_options):
    """Return CKAN's modification timestamp for one resource.

    The datastore API sends no ETag, but CKAN's resource_show metadata has
    last_modified (when the data file changed). metadata_modified is the
    fallback; it also changes on metadata-only edits, which merely causes a
    harmless reload. The action lives beside datastore_search in the API.
    """
    show_url = urljoin(api_url, 'resource_show')
    response = request_page(show_url, params={'id': resource_id}, **request_options)
    try:
        data = response.json()
    except ValueError as error:
        raise ScraperError(f"Resource {resource_id}: metadata is not valid JSON") from error
    if not isinstance(data, dict) or data.get('success') is not True:
        raise ScraperError(f"Resource {resource_id}: metadata response does not report success=true")
    result = data.get('result')
    if not isinstance(result, dict):
        raise ScraperError(f"Resource {resource_id}: metadata response has no result object")
    version = result.get('last_modified') or result.get('metadata_modified')
    if not isinstance(version, str) or not version.strip():
        return None
    return version


def records_sha256(records):
    """Fingerprint CKAN rows: same rows in the same order give the same hash."""
    encoded = json.dumps(records, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return sha256(encoded.encode('utf-8')).hexdigest()


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
