-- Reviewable initial migration; apply explicitly to an empty application schema.
-- This is not a scraper startup action. Reapplying fails instead of silently
-- accepting a different existing table definition. See learning/04-postgresql-architecture.md.
BEGIN;

CREATE TABLE source_resources (
    resource_id TEXT PRIMARY KEY CHECK (btrim(resource_id) <> ''),
    source_url TEXT NOT NULL CHECK (btrim(source_url) <> ''),
    source_kind TEXT NOT NULL CHECK (source_kind IN ('ckan', 'csv')),
    etag TEXT,
    last_modified TEXT,
    last_successful_sync TIMESTAMPTZ
);

CREATE TABLE salary_records (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    content_key TEXT NOT NULL UNIQUE CHECK (content_key ~ '^[0-9a-f]{64}$'),
    first_name TEXT NOT NULL CHECK (btrim(first_name) <> ''),
    last_name TEXT NOT NULL CHECK (btrim(last_name) <> ''),
    job_title TEXT NOT NULL,
    employer TEXT NOT NULL CHECK (btrim(employer) <> ''),
    year INTEGER NOT NULL CHECK (year BETWEEN 0 AND 9999),
    salary_cents BIGINT NOT NULL CHECK (salary_cents >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- One disclosure can occur in several datasets. Keep every source association
-- instead of keeping only the first UUID encountered during deduplication.
CREATE TABLE disclosure_sources (
    disclosure_id BIGINT NOT NULL REFERENCES salary_records(id),
    resource_id TEXT NOT NULL REFERENCES source_resources(resource_id),
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (disclosure_id, resource_id),
    CHECK (last_seen_at >= first_seen_at)
);

CREATE INDEX salary_records_year_salary_idx
    ON salary_records (year, salary_cents DESC, id ASC);
CREATE INDEX disclosure_sources_resource_idx
    ON disclosure_sources (resource_id, disclosure_id);

COMMIT;
