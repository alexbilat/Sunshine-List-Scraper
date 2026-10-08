# Learn the Sunshine List scraper

Read these chapters in order:

1. [Application flow](01-app-flow.md): the original run order and each module's job.
2. [Follow one record](02-follow-one-record.md): discovery, cleaning, deduplication, export.
3. [Python and errors](03-python-and-errors.md): exceptions, retries, logging, and tests.
4. [PostgreSQL architecture](04-postgresql-architecture.md): how PostgreSQL became
   the source of truth, the decisions behind it, and what is still open.

Chapters 1–3 were written for the earlier in-memory pipeline; each starts with a
note on what changed. The SQLite practice module (`sunshine_scraper/database.py`)
is separate and not used by the scraper.
