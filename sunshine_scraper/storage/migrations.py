"""Apply numbered SQL files in order and remember which ones a database has.

A migration is a reviewed SQL file that changes the schema. The database
records each applied file in schema_migrations, so running the runner again
applies only newer files. An applied file must never be edited: its stored
checksum makes that mistake visible instead of leaving databases different.
"""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import re

from .connection import DatabaseConfigurationError

MIGRATIONS_DIRECTORY = Path(__file__).resolve().parents[2] / 'migrations'
FILENAME_PATTERN = re.compile(r'^(\d{3})_[a-z0-9_]+\.sql$')
# Advisory locks are application-chosen numbers that PostgreSQL only uses to
# make sessions take turns. Two migrators racing could apply a file twice.
MIGRATION_LOCK_ID = 7141100001
# Files applied by hand with psql may wrap themselves in BEGIN/COMMIT. The
# runner supplies its own transaction, so it removes only those exact lines.
TRANSACTION_CONTROL_LINE = re.compile(r'^\s*(BEGIN|COMMIT)\s*;\s*$', re.IGNORECASE | re.MULTILINE)
CREATE_TABLE_PATTERN = re.compile(r'\bCREATE\s+TABLE\s+(\w+)', re.IGNORECASE)
CREATE_MIGRATION_TABLE = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        filename TEXT NOT NULL,
        checksum TEXT NOT NULL CHECK (checksum ~ '^[0-9a-f]{64}$'),
        applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
"""


class MigrationError(RuntimeError):
    """The schema cannot be brought to, or confirmed at, the expected version."""


@dataclass(frozen=True)
class Migration:
    version: str
    filename: str
    sql: str

    @property
    def checksum(self):
        # Git may check files out with Windows line endings. Hash normalized
        # text so one unchanged file has one checksum on every machine.
        normalized = self.sql.replace('\r\n', '\n')
        return sha256(normalized.encode('utf-8')).hexdigest()

    @property
    def executable_sql(self):
        return TRANSACTION_CONTROL_LINE.sub('', self.sql)

    @property
    def created_tables(self):
        return CREATE_TABLE_PATTERN.findall(self.sql)


def load_migrations(directory=MIGRATIONS_DIRECTORY):
    """Return migration files sorted by version; reject ambiguous numbering."""
    migrations = {}
    for path in sorted(Path(directory).glob('*.sql')):
        match = FILENAME_PATTERN.fullmatch(path.name)
        if not match:
            raise MigrationError(f"Unexpected migration filename: {path.name}")
        version = match.group(1)
        if version in migrations:
            raise MigrationError(f"Two migration files use version {version}")
        migrations[version] = Migration(version, path.name, path.read_text(encoding='utf-8'))
    return [migrations[version] for version in sorted(migrations)]


def pending_migrations(available, applied):
    """Compare files with a database's record; return files still to apply.

    applied maps version to stored checksum. Pure logic, so offline tests can
    check every mismatch rule without a server.
    """
    known = {migration.version for migration in available}
    unknown = sorted(set(applied) - known)
    if unknown:
        raise MigrationError("Database has migrations this code does not know: "
                             + ', '.join(unknown))
    pending = []
    for migration in available:
        stored = applied.get(migration.version)
        if stored is None:
            pending.append(migration)
        elif stored != migration.checksum:
            raise MigrationError(
                f"Applied migration {migration.filename} was edited afterwards; "
                "restore the original file and add a new migration instead")
    if pending and applied and pending[0].version < max(applied):
        # A gap means an older file appeared after newer ones were applied.
        raise MigrationError(f"Migration {pending[0].filename} is older than applied migrations")
    return pending


def applied_migrations(connection):
    """Return {version: checksum}; empty when schema_migrations does not exist."""
    exists = connection.execute("SELECT to_regclass('schema_migrations')").fetchone()[0]
    if exists is None:
        return {}
    rows = connection.execute('SELECT version, checksum FROM schema_migrations').fetchall()
    return dict(rows)


def ensure_schema_current(connection, directory=MIGRATIONS_DIRECTORY):
    """Raise MigrationError unless every migration file has been applied.

    The scraper calls this before downloading. It never migrates by itself:
    schema changes are a deliberate, separately run step.
    """
    pending = pending_migrations(load_migrations(directory), applied_migrations(connection))
    if pending:
        raise MigrationError(
            "Database schema is not up to date (pending: "
            + ', '.join(migration.filename for migration in pending)
            + "); run: python -m sunshine_scraper.storage migrate")


def migrate(connection, directory=MIGRATIONS_DIRECTORY):
    """Apply pending migrations; return the filenames applied.

    The connection must use autocommit, so each file gets its own explicit
    transaction. A failing file rolls back with its schema_migrations row.
    """
    connection.execute('SELECT pg_advisory_lock(%s)', (MIGRATION_LOCK_ID,))
    try:
        connection.execute(CREATE_MIGRATION_TABLE)
        # Read the record only after holding the lock, so it cannot be stale.
        pending = pending_migrations(load_migrations(directory), applied_migrations(connection))
        applied = []
        for migration in pending:
            with connection.transaction():
                connection.execute(migration.executable_sql)
                record_migration(connection, migration)
            applied.append(migration.filename)
        return applied
    finally:
        connection.execute('SELECT pg_advisory_unlock(%s)', (MIGRATION_LOCK_ID,))


def baseline(connection, through_version, directory=MIGRATIONS_DIRECTORY):
    """Record already-present migrations without running them.

    For databases where a file was applied by hand with psql before the runner
    existed. Refuses unless every table those files create already exists.
    """
    available = load_migrations(directory)
    targets = [migration for migration in available if migration.version <= through_version]
    if not targets or targets[-1].version != through_version:
        raise DatabaseConfigurationError(f"No migration has version {through_version}")
    missing = []
    for migration in targets:
        for table in migration.created_tables:
            if connection.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0] is None:
                missing.append(table)
    if missing:
        raise MigrationError("Cannot baseline; these tables do not exist: " + ', '.join(missing))
    connection.execute('SELECT pg_advisory_lock(%s)', (MIGRATION_LOCK_ID,))
    try:
        connection.execute(CREATE_MIGRATION_TABLE)
        already = applied_migrations(connection)
        recorded = []
        with connection.transaction():
            for migration in targets:
                if migration.version not in already:
                    record_migration(connection, migration)
                    recorded.append(migration.filename)
        return recorded
    finally:
        connection.execute('SELECT pg_advisory_unlock(%s)', (MIGRATION_LOCK_ID,))


def record_migration(connection, migration):
    connection.execute(
        'INSERT INTO schema_migrations (version, filename, checksum) VALUES (%s, %s, %s)',
        (migration.version, migration.filename, migration.checksum))
