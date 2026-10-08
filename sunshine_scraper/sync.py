"""Load Ontario's published datasets into PostgreSQL, one dataset at a time.

Order for each dataset: check whether it changed, download, validate, then
write in one short transaction. Network work happens before the transaction
opens, so no database locks are held while waiting for Ontario's servers.
A failed dataset rolls back alone; earlier datasets stay committed (D4).
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from urllib.parse import urlsplit

from .client import (discover_resource_links, fetch_all_records, fetch_ckan_resource_version,
                     fetch_csv_download, records_sha256, resource_id_from_link)
from .errors import ScraperError
from .storage.models import Disclosure
from .storage.writer import PostgresDisclosureWriter, ResourceResult

logger = logging.getLogger(__name__)
# Run records keep a short reason, not an unbounded driver message.
MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class SyncResult:
    """Summary of one run; status 'locked' means another sync was running."""

    status: str
    run_id: int | None = None
    resources_total: int = 0
    loaded: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    failed: list = field(default_factory=list)


class UnchangedResource(Exception):
    """Internal signal: the source confirmed the stored copy is current."""

    def __init__(self, etag=None, last_modified=None):
        super().__init__('unchanged')
        self.etag = etag
        self.last_modified = last_modified


def run_sync(connection, url, api_url, *, full_refresh=False, timeout=30,
             max_retries=2, backoff=1):
    """Synchronize every discovered dataset; return a SyncResult.

    connection must use autocommit (see open_connection): this function opens
    its own short transactions. full_refresh=True ignores stored validators
    and reloads every dataset, e.g. after changing validation rules.
    """
    import psycopg  # A required dependency; imported lazily like the rest of storage.

    request_options = {'timeout': timeout, 'max_retries': max_retries, 'backoff': backoff}
    writer = PostgresDisclosureWriter(connection)
    if not writer.try_acquire_sync_lock():
        logger.warning("Another sync is already running; this run did nothing")
        return SyncResult(status='locked')
    try:
        run_id = writer.start_run(now())
        loaded, unchanged, failed = [], [], []
        try:
            links = discover_resource_links(url, **request_options)
        except ScraperError:
            writer.finish_run(run_id, status='failed', finished_at=now(), total=0,
                              loaded=0, unchanged=0, failed=0)
            raise
        for link in links:
            resource_id = resource_id_from_link(link)
            kind = 'csv' if urlsplit(link).path.lower().endswith('.csv') else 'ckan'
            writer.register_source(resource_id, link, kind)
            started_at = now()
            try:
                result = sync_resource(writer, connection, run_id, link, resource_id, kind,
                                       api_url, started_at, full_refresh, request_options)
            except (ScraperError, psycopg.Error) as error:
                # The load transaction has already rolled back. Record the
                # failure separately so the evidence survives that rollback.
                message = describe_error(error)
                logger.error("Skipping failed dataset %s: %s", resource_id, message)
                with connection.transaction():
                    writer.record_resource_result(run_id, ResourceResult(
                        resource_id, 'failed', started_at, now(), error_message=message))
                failed.append(resource_id)
                continue
            if result.status == 'unchanged':
                unchanged.append(resource_id)
            else:
                loaded.append(resource_id)
        if not failed:
            status = 'succeeded'
        elif loaded or unchanged:
            status = 'partial'
        else:
            status = 'failed'
        writer.finish_run(run_id, status=status, finished_at=now(), total=len(links),
                          loaded=len(loaded), unchanged=len(unchanged), failed=len(failed))
        logger.info("Sync run %s %s: %s loaded, %s unchanged, %s failed", run_id, status,
                    len(loaded), len(unchanged), len(failed))
        return SyncResult(status, run_id, len(links), loaded, unchanged, failed)
    finally:
        try:
            writer.release_sync_lock()
        except psycopg.Error:
            # A broken connection cannot unlock, but PostgreSQL releases a
            # session's advisory locks when it disconnects. Don't hide the
            # error that broke the connection behind this one.
            logger.debug("Could not release the sync lock explicitly", exc_info=True)


def sync_resource(writer, connection, run_id, link, resource_id, kind, api_url, started_at,
                  full_refresh, request_options):
    """Check, download, validate, and write one dataset; return its ResourceResult.

    The run record is written in the same transaction as the dataset's rows,
    so the two can never disagree about whether the load happened.
    """
    state = None if full_refresh else writer.get_source_state(resource_id)
    try:
        if kind == 'csv':
            records, etag, last_modified, content_hash = fetch_csv(link, state, request_options)
        else:
            records, etag, last_modified, content_hash = fetch_ckan(
                api_url, resource_id, state, request_options)
    except UnchangedResource as signal:
        result = ResourceResult(resource_id, 'unchanged', started_at, now())
        with connection.transaction():
            writer.mark_source_unchanged(resource_id, etag=signal.etag,
                                         last_modified=signal.last_modified)
            writer.record_resource_result(run_id, result)
        logger.info("Resource %s: unchanged since the last successful load", resource_id)
        return result

    if not records:
        # Recording an empty download as success would hide a broken source.
        raise ScraperError(f"Resource {resource_id}: the dataset has no rows")
    disclosures, rejected = validate_rows(records, resource_id)
    if not disclosures:
        # Ontario publishes "Organizations with no salaries to disclose" lists
        # beside the salary lists: employer names only, so every row is
        # rejected. Recording them as loaded lets later runs skip them.
        logger.warning("Resource %s: no disclosures among %s rows (e.g. an organizations-only "
                       "list); recorded as loaded", resource_id, len(records))
    with connection.transaction():
        counts = writer.load_disclosures(resource_id, disclosures)
        writer.mark_source_loaded(resource_id, etag=etag, last_modified=last_modified,
                                  content_sha256=content_hash, row_count=len(records))
        result = ResourceResult(resource_id, 'loaded', started_at, now(),
                                rows_fetched=len(records), rows_valid=len(disclosures),
                                rows_rejected=rejected, rows_inserted=counts.inserted,
                                rows_refreshed=counts.refreshed)
        writer.record_resource_result(run_id, result)
    logger.info("Resource %s: %s valid, %s invalid; %s new, %s already stored",
                resource_id, len(disclosures), rejected, counts.inserted, counts.refreshed)
    return result


def fetch_csv(link, state, request_options):
    """Download with a conditional request; fall back to comparing content hashes."""
    download = fetch_csv_download(
        link, etag=state.etag if state else None,
        last_modified=state.last_modified if state else None, **request_options)
    if download is None:
        raise UnchangedResource()
    if state and download.content_sha256 == state.content_sha256:
        # The server lacked or ignored validators, but the bytes are identical.
        raise UnchangedResource(download.etag, download.last_modified)
    return download.records, download.etag, download.last_modified, download.content_sha256


def fetch_ckan(api_url, resource_id, state, request_options):
    """Compare CKAN's modification timestamp before paging through all rows."""
    try:
        version = fetch_ckan_resource_version(api_url, resource_id, **request_options)
    except ScraperError as error:
        # The check is an optimization; a full download is still correct.
        logger.warning("Resource %s: change check failed (%s); downloading", resource_id, error)
        version = None
    if state and version and version == state.last_modified:
        raise UnchangedResource()
    records = fetch_all_records(api_url, resource_id, **request_options)
    content_hash = records_sha256(records)
    if state and content_hash == state.content_sha256:
        raise UnchangedResource(last_modified=version)
    return records, None, version, content_hash


def validate_rows(records, resource_id):
    """Return (valid disclosures, rejected count); log one summary per dataset.

    Duplicates are not decided here: the database's unique content_key does
    that across every dataset and every run.
    """
    disclosures = []
    reasons = Counter()
    missing_titles = 0
    for row_index, row in enumerate(records):
        try:
            disclosure = Disclosure.from_source_row(row)
        except (ValueError, TypeError, OverflowError) as error:
            reasons[str(error)] += 1
            logger.debug("Resource %s row %s skipped: %s", resource_id, row_index, error)
            continue
        disclosures.append(disclosure)
        if not disclosure.job_title:
            missing_titles += 1
    rejected = sum(reasons.values())
    if rejected:
        logger.warning("Resource %s skipped invalid rows: %s", resource_id, dict(reasons))
    if missing_titles:
        logger.warning("Resource %s: %s accepted rows have no job title", resource_id, missing_titles)
    return disclosures, rejected


def describe_error(error):
    """A short, single-line reason. Connection details never reach here: those
    failures happen before sync starts and are reported by open_connection."""
    text = ' '.join(str(error).split()) or type(error).__name__
    return text[:MAX_ERROR_LENGTH]


def now():
    return datetime.now(timezone.utc)
