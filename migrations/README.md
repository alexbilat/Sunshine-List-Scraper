# Migrations

Numbered SQL files that build and change the database schema, applied in order
by:

```powershell
python -m sunshine_scraper.storage migrate
```

The runner records each applied file, with a checksum, in `schema_migrations`.
Running it again applies only files the database has not received.

## Adding a migration

1. Create the next number: `003_short_description.sql` (three digits, lowercase
   letters, digits and underscores).
2. Write plain SQL **without** `BEGIN;`/`COMMIT;`. The runner wraps each file in
   one transaction together with its `schema_migrations` row, so a failing file
   leaves no trace. (`001` has its own `BEGIN;`/`COMMIT;` lines because it was
   first applied by hand; the runner removes exactly those lines before running it.)
3. Test it: `python -m unittest discover -s tests -v` with
   `SUNSHINE_TEST_DATABASE_URL` set applies every file to a fresh schema.

## Rules

- **Never edit a file after it has been applied anywhere.** The runner compares
  checksums and refuses to continue if an applied file changed. Write a new
  migration instead.
- The scraper never migrates by itself. When files are pending, it stops before
  downloading and names this command.
- `migrate --status` lists applied and pending files without changing anything.
- `migrate --baseline 001` records files up to `001` as applied without running
  them, for databases where they were applied by hand. It refuses unless the
  tables those files create already exist.
