# 4. PostgreSQL architecture and decisions

## What exists now

PostgreSQL is the scraper's source of truth. `python Sunshine_List_Scaper.py`
syncs Ontario's datasets into the database (`sunshine_scraper/sync.py`), then
writes `output.txt`, the yearly summary, and the charts from it
(`sunshine_scraper/pipeline.py`). The in-memory `names_list`/`seen_records`
pipeline is gone; the database's unique `content_key` replaces it, across runs.

This chapter began as a design review before any ingestion existed. The design
sections below still describe the reasoning; "Decisions" at the end records what
was settled and how it was implemented. The SQLite practice file is independent.

| New piece | Responsibility |
| --- | --- |
| `storage/migrations.py` + `migrate` command | Apply numbered SQL files once, in order, with checksums |
| `migrations/002_sync_tracking.sql` | Run records and refresh timestamps |
| `storage/writer.py` | COPY into a staging table, upsert disclosures, link sources, record runs |
| `sync.py` | Lock, discover, check for changes, download, validate, one transaction per dataset |
| `storage/repository.py` | Export stream, yearly aggregates, top titles |

## The intended architecture

```mermaid
flowchart LR
    A[Ontario CKAN and CSV sources] --> B[Existing client and shared cleaning rules]
    B --> C[Synchronization service: sync.py]
    C --> D[PostgresDisclosureWriter]
    D --> E[PostgreSQL]
    F[Future frontend] --> G[Backend API]
    G --> H[SalaryReader interface]
    H --> I[PostgresSalaryRepository]
    I --> E
    J[External scheduler] --> C
```

The sync service will control the algorithm: which sources to fetch, which rows
to accept, when a resource counts as successful, and when to commit. A repository
will translate those decisions into SQL. The HTTP client should not open database
connections, and the frontend should call the backend instead of receiving database
credentials. The API must read persisted data without launching a scrape.

In computer science terms, each boundary hides one kind of mechanism. A reader's
caller asks for salaries without needing to know SQL. A writer's caller will ask
to persist a batch without needing to know Psycopg's connection protocol.

## The reviewable code

| File | Responsibility | Why it is separate |
| --- | --- | --- |
| `storage/models.py` | `Disclosure`, exact cents, and content fingerprint | Pure data conversion can be checked without a server |
| `storage/connection.py` | Settings, lazy driver loading, and connection lifetime | Credentials and transaction ownership stay in one boundary |
| `storage/repository.py` | `SalaryReader` contract and a parameterized PostgreSQL read | A future API can depend on a small operation instead of database details |
| `storage/__main__.py` | Explicit read-only `check` and `top` commands | Importing modules or running the scraper performs no database I/O |
| `migrations/001_disclosure_foundation.sql` | Tables, constraints, and query indexes | Database structure can be reviewed independently of Python |

`Protocol` describes methods a caller expects; it does not require subclasses.
`PostgresSalaryRepository` satisfies `SalaryReader` by providing that method. The
interface currently has only `get_top_salaries(year, limit)`; expand it around real
API needs instead of adding speculative methods.

A repository receives an already opened connection. It does not close or commit
that connection. This will let the sync service use several repository operations
inside the same transaction. `open_connection()` currently owns one connection;
its context commits on success, rolls back on exception, and closes. A connection
pool belongs at this boundary when a concurrent backend becomes necessary.
See [Psycopg's connection behavior](https://www.psycopg.org/psycopg3/docs/basic/usage.html).

## Three tables and their meaning

```mermaid
erDiagram
    salary_records ||--o{ disclosure_sources : observed_in
    source_resources ||--o{ disclosure_sources : contains
```

- **`salary_records`** stores one distinct normalized disclosure: separate first
  and last names, title, employer, year, and salary in cents. An internal generated
  `id` is a reference to this row, not an identifier for a real employee.
- **`source_resources`** stores dataset identity, its URL and kind, optional HTTP
  validators (`etag`, `last_modified`), and a successful-sync timestamp. These
  fields are placeholders for a future sync policy, not evidence that Ontario
  supports conditional fetching or record-level incremental changes.
- **`disclosure_sources`** connects the two. The same disclosure may appear in
  several datasets, and each dataset may contain many disclosures. Its composite
  primary key prevents repeating the same association.

Why not store a single UUID on each salary row? The existing scraper keeps only
the first dataset UUID when matching disclosures occur in multiple resources. A
join table preserves all those source associations. A future writer must observe
and link each valid row before cross-source deduplication discards that association.

Why no employee or employer identity tables yet? We have display names but no
verified stable identity for real people, or reviewed rules for employer renames.
Treating names as identities could merge unrelated people. Normalizing employers
can be a later migration once we understand the needed queries and identity rules.

The index `(year, salary_cents DESC, id ASC)` matches the first read: filter one
year and return its largest salaries with deterministic tie ordering. The content
key's unique constraint supplies an index for future duplicate conflicts. The
source-first relationship index supports finding disclosures for a dataset.
These indexes have storage and write costs; add more after measuring real queries.

## Exact money and content identity

The current export path converts salary to a binary float. The new adapter instead
parses the raw source salary with `Decimal`, requires whole cents, checks the
PostgreSQL `BIGINT` bound, and stores integer cents. For example, `$123,456.78`
becomes `12345678`. A few 2021-2023 rows publish fractions of a cent (e.g.
`111259.878`); these are rounded half-up to the nearest cent from the exact
`Decimal`, never through a float. Direct float input is rejected because its
original precision is unknown.

Both paths share the same field aliases and whitespace normalizers. The database
adapter additionally preserves first/last-name boundaries and exact money. It must
be called on raw CKAN/CSV rows, not on the existing six-column export dictionaries.
Before wiring ingestion, review whether both paths should use this one model and
then create their own export/report representations.

`Disclosure` is an immutable dataclass: its named fields are easier to reason about
than positional tuples, and it cannot accidentally change after its key is computed.
`content_key` hashes a versioned JSON array containing lowercased names, title,
employer, year, and cents. JSON preserves field boundaries; a separator-joined
string can be ambiguous if the separator occurs in a field. SHA-256 makes a compact,
repeatable lookup key. Hash collisions are theoretically possible; this is a
practical fingerprint, not a mathematical proof of equality or person identity.
Changing its encoding or matching rules later requires an explicit migration.

The key mirrors the current duplicate policy. It can collapse two truly different
disclosures whose available fields are identical; we do not have enough identity
information to distinguish them. Source-specific row identifiers, if available,
should be retained in the later ingestion design.

**A salary correction produces a different content key.** The initial table stores
observed contents, so it is not yet a corrected, current-view dataset. The example
top-salary query reads those observed contents directly. Once corrections are
ingested, it must read a reviewed current-view policy instead of summing all
historical observations. Addendum change/deletion actions are not applied by the
existing scraper either. Do not interpret this foundation as solving corrections.

## How a future 15-minute refresh should work

1. An external scheduler invokes a dedicated sync command. It does not keep a
   frontend request open or embed an infinite loop inside the web server.
2. Permit one sync worker at a time, using scheduler controls and/or a database
   advisory lock. Runs can take longer than 15 minutes.
3. Discover resources, then determine which need fetching. Prefer trustworthy
   source cursors or conditional requests if supported; otherwise compare source
   snapshots. A `last_successful_sync` timestamp alone cannot prove a dataset is
   unchanged. Historical resources may be corrected too.
4. Fetch and validate outside a long-lived database transaction. For a large
   snapshot, load rows into a staging area, preserving source associations.
5. In a short publish transaction, insert new disclosure contents, link sources,
   apply the reviewed correction rules, and advance validators/checkpoints.
   `INSERT ... ON CONFLICT` can make repeated inputs safe to replay. Avoid an
   existence query followed by a separate insertion for every row.
6. Mark success only after publication commits. Record failures separately; a
   failed or partially validated source must not cause deletions or advance its
   successful checkpoint. Decide explicitly how rejected rows affect publication.

Readers continue to use the last committed dataset during a refresh. Availability
and freshness differ: a 15-minute schedule means source changes can lag by that
interval plus processing time. Per-resource publication is simpler but exposes a
mixture of resource versions; publishing a complete run requires staging and a
run/version pointer. Choose that boundary before enabling the worker.

The future writes should use bounded batches initially; use bulk `COPY` into
staging when measured volume makes that worthwhile. PostgreSQL handles uniqueness
through its index rather than asking Python to scan every persisted record.
See [PostgreSQL conflict handling](https://www.postgresql.org/docs/current/sql-insert.html).

## Commands

```powershell
python -m pip install -r requirements.txt
$env:SUNSHINE_DATABASE_URL = 'postgresql://sunshine:YOUR_LOCAL_PASSWORD@localhost:5432/sunshine'
python -m sunshine_scraper.storage migrate
python Sunshine_List_Scaper.py
python -m sunshine_scraper.storage top --year 2024 --limit 10
```

`.env.example` documents the setting; this project does not automatically load
`.env` files. Do not commit credentials. `migrate` is the only command that
changes the schema; the scraper checks that no migration is pending and stops
before downloading if one is. `check` and `top` use read-only transactions.

For real SQL checks, set `SUNSHINE_TEST_DATABASE_URL` to a **dedicated test
database** before running `python -m unittest discover -s tests -v`. Integration
tests migrate randomly named schemas there and drop only their own schemas.
Without that variable they are skipped.

## Decisions

These were settled by the project owner before implementation:

| # | Decision | Implementation |
| --- | --- | --- |
| D1 | PostgreSQL replaces the TSV as the source of truth | The pipeline syncs, then exports from one `REPEATABLE READ` snapshot |
| D2 | Store disclosures as published; no correction logic yet | Nothing is deleted; addendum change/deletion actions are not applied |
| D3 | "Same entry" means identical normalized contents (`content_key`) | `ON CONFLICT DO UPDATE` refreshes spelling, `last_seen_at`, `updated_at`; a changed salary is a new row |
| D4 | Commit per dataset | One transaction per dataset; failures are recorded separately in `sync_run_resources` |
| D5 | Plain SQL migrations plus a small runner | `schema_migrations` with checksums; `migrate`, `--status`, `--baseline` |
| D6 | Prepare for a 15-minute refresh | Advisory lock (one sync at a time); HTTP `304` for CSVs; CKAN `resource_show` timestamps; content hashes as fallback |

Consequences worth knowing:

- **Republished files add rows.** Because of D2 and D3, when Ontario republishes
  a year with corrected salaries, the corrected rows are new disclosures and
  the originals stay. Yearly counts can grow over time. A future "current view"
  would need correction rules: the addenda's change/deletion semantics, or
  preferring the newest dataset per year.
- **Organizations-only datasets.** Ontario lists "organizations with no salaries
  to disclose" beside the salary lists. They have rows but no people. They are
  recorded as loaded with zero disclosures, not as failures.
- **Overlapping runs.** A run that finds the sync lock held exits with status 0
  and exports nothing; the running sync will export.

Still open:

1. Correction handling (see above) and which source fields identify corrections.
2. Which queries a first API/frontend needs beyond top salaries and yearly totals.
3. Scheduling, hosting, and a read-only role for the API.
