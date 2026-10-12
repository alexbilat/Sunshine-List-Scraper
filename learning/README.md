# Learn the Sunshine List scraper

Read these chapters in order:

1. [Application flow](01-app-flow.md): the original run order and each module's job.
2. [Follow one record](02-follow-one-record.md): discovery, cleaning, deduplication, export.
3. [Python and errors](03-python-and-errors.md): exceptions, retries, logging, and tests.
4. [PostgreSQL architecture](04-postgresql-architecture.md): how PostgreSQL became
   the source of truth, the decisions behind it, and what is still open.
5. [PostgreSQL primer](05-postgresql-primer.md): how the database works, conceptually.
6. [Hands-on PostgreSQL tutorial](06-postgresql-tutorial.md): lessons using this project.
7. [The web API](07-api.md): how HTTP APIs work and how the read-only JSON API
   in `sunshine_scraper/api/` serves the database to browsers and other programs.

Chapters 1–3 were written for the earlier in-memory pipeline; each starts with a
note on what changed. The SQLite practice module (`sunshine_scraper/database.py`)
is separate and not used by the scraper.
