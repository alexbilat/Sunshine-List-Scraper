"""Coordinate a run: sync PostgreSQL, then export files from it; report gaps.

PostgreSQL is the source of truth (decision D1). The TSV, yearly summary, and
charts are generated from the database, never from in-memory download state.
"""
import logging

from .errors import ScraperError
from .export import write_records
from .reporting import create_charts, print_yearly_summary
from .storage.connection import DatabaseSettings, open_connection
from .storage.migrations import ensure_schema_current
from .storage.repository import PostgresSalaryRepository
from .sync import run_sync

logger = logging.getLogger(__name__)


def run(url, api_url, output_path, yearly_chart_path, titles_chart_path,
        *, timeout=30, max_retries=2, backoff=1, full_refresh=False, settings=None):
    """Sync, then export the TSV, summary, and charts from the database.

    Return True when every dataset synced (or was confirmed unchanged) and the
    charts were written; False for a partial run. Raise ScraperError if the
    database holds nothing to export. The CLI converts the result to an exit
    code. settings defaults to SUNSHINE_DATABASE_URL from the environment.
    """
    # Fail before any download if the database is not configured or reachable.
    settings = settings or DatabaseSettings.from_environment()
    with open_connection(settings, autocommit=True) as connection:
        ensure_schema_current(connection)
        result = run_sync(connection, url, api_url, full_refresh=full_refresh,
                          timeout=timeout, max_retries=max_retries, backoff=backoff)
        if result.status == 'locked':
            # The running sync will export when it finishes; overlapping
            # scheduled runs are expected, not an error.
            return True
        charts_ok = export_from_database(connection, output_path, yearly_chart_path,
                                         titles_chart_path)
    if result.failed:
        logger.error("Incomplete run: %s/%s resources failed: %s", len(result.failed),
                     result.resources_total, ', '.join(result.failed))
    return result.status == 'succeeded' and charts_ok


def export_from_database(connection, output_path, yearly_chart_path, titles_chart_path):
    """Write all outputs from one consistent snapshot; return False on chart failure."""
    reader = PostgresSalaryRepository(connection)
    # REPEATABLE READ makes every query in this transaction see the same
    # committed data, so the TSV, summary, and charts always agree.
    with connection.transaction():
        connection.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
        total = reader.count_records()
        # Avoid replacing a previous good export with an empty result.
        if not total:
            raise ScraperError("Database has no records; existing outputs were left untouched")
        write_records(reader.iter_export_records(), output_path)
        logger.info("Wrote %s records to %s", total, output_path)
        yearly_summary = reader.yearly_summary()
        top_titles = reader.top_job_titles(10)
    print_yearly_summary(yearly_summary)
    # Once the TSV is saved, a chart failure should not discard it.
    try:
        create_charts(yearly_summary, top_titles, yearly_chart_path, titles_chart_path)
    except (OSError, ValueError) as error:
        logger.error("Chart generation failed; the TSV was saved: %s", error)
        return False
    return True
