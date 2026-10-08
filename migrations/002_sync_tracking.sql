-- Sync bookkeeping for repeated refreshes. Apply with:
--   python -m sunshine_scraper.storage migrate
-- The runner wraps this file in a transaction together with its
-- schema_migrations row, so this file has no BEGIN/COMMIT of its own.

-- "Same contents seen again" refreshes display spelling and timestamps instead
-- of inserting a duplicate (decision D3). created_at keeps the first sighting.
ALTER TABLE salary_records
    ADD COLUMN last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ADD COLUMN updated_at TIMESTAMPTZ;

-- A payload fingerprint lets a refresh skip database work when a source has no
-- trustworthy HTTP validator or modification timestamp.
ALTER TABLE source_resources
    ADD COLUMN content_sha256 TEXT CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    ADD COLUMN last_row_count INTEGER CHECK (last_row_count >= 0);

-- One row per sync attempt. A run that crashes stays 'running' with no
-- finished_at, which is itself useful evidence when investigating.
CREATE TABLE sync_runs (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'succeeded', 'partial', 'failed')),
    resources_total INTEGER CHECK (resources_total >= 0),
    resources_loaded INTEGER CHECK (resources_loaded >= 0),
    resources_unchanged INTEGER CHECK (resources_unchanged >= 0),
    resources_failed INTEGER CHECK (resources_failed >= 0),
    CHECK ((status = 'running') = (finished_at IS NULL)),
    CHECK (finished_at IS NULL OR finished_at >= started_at)
);

-- What happened to each dataset in a run. Failures are recorded in their own
-- short transaction, so rolling back a failed load does not erase its record.
CREATE TABLE sync_run_resources (
    run_id BIGINT NOT NULL REFERENCES sync_runs(id),
    resource_id TEXT NOT NULL REFERENCES source_resources(resource_id),
    status TEXT NOT NULL CHECK (status IN ('loaded', 'unchanged', 'failed')),
    rows_fetched INTEGER CHECK (rows_fetched >= 0),
    rows_valid INTEGER CHECK (rows_valid >= 0),
    rows_rejected INTEGER CHECK (rows_rejected >= 0),
    rows_inserted INTEGER CHECK (rows_inserted >= 0),
    rows_refreshed INTEGER CHECK (rows_refreshed >= 0),
    error_message TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    finished_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (run_id, resource_id),
    CHECK (finished_at >= started_at),
    CHECK ((status = 'failed') = (error_message IS NOT NULL))
);
