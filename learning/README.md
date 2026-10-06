# Learn the Sunshine List scraper

Read these chapters in order:

1. [Application flow](01-app-flow.md): what runs today and each module's job.
2. [Follow one record](02-follow-one-record.md): discovery, cleaning, deduplication, export.
3. [Python and errors](03-python-and-errors.md): exceptions, retries, logging, and tests.
4. [PostgreSQL architecture](04-postgresql-architecture.md): the new foundation,
   design tradeoffs, and decisions to review before enabling persistence.

The PostgreSQL foundation is separate from the standalone SQLite practice module.
Neither database module is called by the normal scraper yet.
