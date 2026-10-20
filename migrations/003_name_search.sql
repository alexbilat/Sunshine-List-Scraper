-- Exact-name lookup that ignores case and accents. Apply with:
--   python -m sunshine_scraper.storage migrate
-- The runner wraps this file in a transaction together with its
-- schema_migrations row, so this file has no BEGIN/COMMIT of its own.

-- unaccent is a contrib extension; PostgreSQL marks it trusted, so the
-- database owner may create it without being a superuser.
CREATE EXTENSION IF NOT EXISTS unaccent;

-- unaccent() is only STABLE (its dictionary can change), which PostgreSQL
-- refuses to index. Naming the dictionary explicitly lets this wrapper be
-- IMMUTABLE. fold_name is the one rule for "same name": lowercase, no accents.
CREATE FUNCTION fold_name(text) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
    AS $$ SELECT lower(public.unaccent('public.unaccent'::regdictionary, $1)) $$;

-- Last name first: it is the more selective half of a full-name lookup.
CREATE INDEX salary_records_folded_name_idx
    ON salary_records (fold_name(last_name), fold_name(first_name));
