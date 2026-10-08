"""SQL writes for the sync service; the caller owns every transaction.

Like the reader, this repository never commits, rolls back, or closes. The
sync service decides which writes belong together (one dataset's rows, its
links, and its run record) and wraps them in connection.transaction().
"""
from dataclasses import dataclass

# Session-level advisory lock that allows one sync at a time per database.
# A 15-minute schedule can start a new run before a slow one finishes.
SYNC_LOCK_ID = 7141100002


@dataclass(frozen=True)
class SourceState:
    """What the last successful load recorded about one dataset."""

    etag: str | None
    last_modified: str | None
    content_sha256: str | None


@dataclass(frozen=True)
class LoadCounts:
    inserted: int
    refreshed: int


@dataclass(frozen=True)
class ResourceResult:
    """One row of sync_run_resources; counts are None when not reached."""

    resource_id: str
    status: str
    started_at: object
    finished_at: object
    rows_fetched: int | None = None
    rows_valid: int | None = None
    rows_rejected: int | None = None
    rows_inserted: int | None = None
    rows_refreshed: int | None = None
    error_message: str | None = None


class PostgresDisclosureWriter:
    """Translate sync decisions into SQL using a caller-owned connection."""

    def __init__(self, connection):
        self.connection = connection

    def try_acquire_sync_lock(self):
        """Return False instead of waiting when another sync holds the lock.

        Session-level advisory locks survive commits on this connection, so
        the lock lasts for the whole run and disappears if the process dies.
        """
        row = self.connection.execute('SELECT pg_try_advisory_lock(%s)', (SYNC_LOCK_ID,)).fetchone()
        return bool(row[0])

    def release_sync_lock(self):
        self.connection.execute('SELECT pg_advisory_unlock(%s)', (SYNC_LOCK_ID,))

    def start_run(self, started_at):
        row = self.connection.execute(
            'INSERT INTO sync_runs (started_at) VALUES (%s) RETURNING id', (started_at,)).fetchone()
        return row[0]

    def finish_run(self, run_id, *, status, finished_at, total, loaded, unchanged, failed):
        self.connection.execute(
            """
            UPDATE sync_runs
            SET status = %s, finished_at = %s, resources_total = %s,
                resources_loaded = %s, resources_unchanged = %s, resources_failed = %s
            WHERE id = %s
            """,
            (status, finished_at, total, loaded, unchanged, failed, run_id))

    def register_source(self, resource_id, source_url, source_kind):
        """Record a discovered dataset so run records can reference it."""
        self.connection.execute(
            """
            INSERT INTO source_resources (resource_id, source_url, source_kind)
            VALUES (%s, %s, %s)
            ON CONFLICT (resource_id) DO UPDATE
            SET source_url = EXCLUDED.source_url, source_kind = EXCLUDED.source_kind
            """,
            (resource_id, source_url, source_kind))

    def get_source_state(self, resource_id):
        """Return validators from the last successful load, or None if never loaded."""
        row = self.connection.execute(
            """
            SELECT etag, last_modified, content_sha256
            FROM source_resources
            WHERE resource_id = %s AND last_successful_sync IS NOT NULL
            """,
            (resource_id,)).fetchone()
        return SourceState(*row) if row else None

    def load_disclosures(self, resource_id, disclosures):
        """Insert new disclosures, refresh identical ones, and link all to the source.

        Must run inside a transaction: the staging table disappears at commit.
        Call at most once per transaction.
        """
        self.connection.execute(
            """
            CREATE TEMP TABLE staging_disclosures (
                position BIGINT NOT NULL,
                content_key TEXT NOT NULL,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                job_title TEXT NOT NULL,
                employer TEXT NOT NULL,
                year INTEGER NOT NULL,
                salary_cents BIGINT NOT NULL
            ) ON COMMIT DROP
            """)
        # COPY streams rows in PostgreSQL's bulk format: far faster than one
        # INSERT per row for a few hundred thousand disclosures.
        with self.connection.cursor() as cursor:
            with cursor.copy(
                    'COPY staging_disclosures (position, content_key, first_name, last_name,'
                    ' job_title, employer, year, salary_cents) FROM STDIN') as copy:
                for position, disclosure in enumerate(disclosures):
                    copy.write_row((position, disclosure.content_key, disclosure.first_name,
                                    disclosure.last_name, disclosure.job_title,
                                    disclosure.employer, disclosure.year,
                                    disclosure.salary_cents))
        # DISTINCT ON keeps one row per key, here the LAST occurrence in the
        # file (newest). Without it, ON CONFLICT DO UPDATE would fail with
        # "cannot affect row a second time" when a file repeats a disclosure.
        # xmax = 0 is a PostgreSQL idiom: a freshly inserted row version has no
        # deleting/locking transaction, while an updated conflicting row does.
        inserted, refreshed = self.connection.execute(
            """
            WITH deduplicated AS (
                SELECT DISTINCT ON (content_key)
                    content_key, first_name, last_name, job_title, employer, year, salary_cents
                FROM staging_disclosures
                ORDER BY content_key, position DESC
            ), upserted AS (
                INSERT INTO salary_records
                    (content_key, first_name, last_name, job_title, employer, year, salary_cents)
                SELECT content_key, first_name, last_name, job_title, employer, year, salary_cents
                FROM deduplicated
                ON CONFLICT (content_key) DO UPDATE
                SET first_name = EXCLUDED.first_name,
                    last_name = EXCLUDED.last_name,
                    job_title = EXCLUDED.job_title,
                    employer = EXCLUDED.employer,
                    last_seen_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING (xmax = 0) AS was_inserted
            )
            SELECT count(*) FILTER (WHERE was_inserted),
                   count(*) FILTER (WHERE NOT was_inserted)
            FROM upserted
            """).fetchone()
        # Every dataset a disclosure appears in is kept, never only the first.
        self.connection.execute(
            """
            INSERT INTO disclosure_sources (disclosure_id, resource_id)
            SELECT DISTINCT records.id, %s
            FROM staging_disclosures AS staging
            JOIN salary_records AS records USING (content_key)
            ON CONFLICT (disclosure_id, resource_id) DO UPDATE
            SET last_seen_at = CURRENT_TIMESTAMP
            """,
            (resource_id,))
        return LoadCounts(inserted=inserted, refreshed=refreshed)

    def mark_source_loaded(self, resource_id, *, etag, last_modified, content_sha256, row_count):
        """Advance the source's validators only after its rows are written."""
        self.connection.execute(
            """
            UPDATE source_resources
            SET etag = %s, last_modified = %s, content_sha256 = %s,
                last_row_count = %s, last_successful_sync = CURRENT_TIMESTAMP
            WHERE resource_id = %s
            """,
            (etag, last_modified, content_sha256, row_count, resource_id))

    def mark_source_unchanged(self, resource_id, *, etag=None, last_modified=None):
        """Record a confirmed-current check; keep validators the source omitted."""
        self.connection.execute(
            """
            UPDATE source_resources
            SET etag = COALESCE(%s, etag), last_modified = COALESCE(%s, last_modified),
                last_successful_sync = CURRENT_TIMESTAMP
            WHERE resource_id = %s
            """,
            (etag, last_modified, resource_id))

    def record_resource_result(self, run_id, result):
        self.connection.execute(
            """
            INSERT INTO sync_run_resources
                (run_id, resource_id, status, rows_fetched, rows_valid, rows_rejected,
                 rows_inserted, rows_refreshed, error_message, started_at, finished_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (run_id, result.resource_id, result.status, result.rows_fetched,
             result.rows_valid, result.rows_rejected, result.rows_inserted,
             result.rows_refreshed, result.error_message, result.started_at,
             result.finished_at))
