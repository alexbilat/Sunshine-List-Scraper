-- Group job titles that mean the same thing ("Elementary Teacher",
-- "Teacher - Elementary", "Elementary Teachers"). Apply with:
--   python -m sunshine_scraper.storage migrate
-- The runner wraps this file in a transaction together with its
-- schema_migrations row, so this file has no BEGIN/COMMIT of its own.

-- title_key is the one rule for "same title": fold case and accents, split
-- into words, drop filler words, strip plural endings, then sort the unique
-- words so word order stops mattering. Keys are only compared, never shown,
-- so a clumsy stem ("busines") is harmless as long as it is consistent.
CREATE FUNCTION title_key(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$
        SELECT coalesce(string_agg(token, ' ' ORDER BY token), '')
        FROM (
            SELECT DISTINCT CASE
                WHEN word ~ '.ies$' THEN regexp_replace(word, 'ies$', 'y')
                WHEN word ~ '[^s]s$' THEN left(word, -1)
                ELSE word
            END AS token
            FROM regexp_split_to_table(fold_name($1), '[^a-z0-9]+') AS word
            WHERE word <> '' AND word NOT IN ('of', 'and', 'the', 'for', 'to', 'in')
        ) AS tokens
    $$;

-- Stored, so adding the column backfills existing rows and every later insert
-- (the sync's upsert) fills it without any Python change. The original
-- job_title is untouched, and content_key does not use this column.
ALTER TABLE salary_records
    ADD COLUMN title_key text GENERATED ALWAYS AS (title_key(job_title)) STORED;

CREATE INDEX salary_records_title_key_idx ON salary_records (title_key);
