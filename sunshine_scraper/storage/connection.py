"""Explicit, optional PostgreSQL connection setup with no import-time I/O."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import os


class DatabaseConfigurationError(ValueError):
    """A missing setting or optional dependency prevents database access."""


class DatabaseAccessError(RuntimeError):
    """Database access failed; the public message excludes connection secrets."""


@dataclass(frozen=True)
class DatabaseSettings:
    # URLs can contain passwords; exclude them from generated repr output.
    database_url: str = field(repr=False)
    connect_timeout: int = 10

    def __post_init__(self):
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise DatabaseConfigurationError("SUNSHINE_DATABASE_URL is required")
        if type(self.connect_timeout) is not int or self.connect_timeout <= 0:
            raise DatabaseConfigurationError("connect_timeout must be a positive integer")

    @classmethod
    def from_environment(cls, environment=None):
        environment = os.environ if environment is None else environment
        return cls(database_url=environment.get('SUNSHINE_DATABASE_URL', ''))


@contextmanager
def open_connection(settings):
    """Own one connection and its transaction for an explicit operation.

    Psycopg commits on success, rolls back on exception, and always closes.
    A future web service can replace this boundary with a connection pool.
    """
    try:
        import psycopg
    except ImportError as error:
        raise DatabaseConfigurationError(
            "Install optional database dependencies with "
            "python -m pip install -r requirements-postgres.txt"
        ) from error
    try:
        with psycopg.connect(settings.database_url,
                             connect_timeout=settings.connect_timeout,
                             application_name='sunshine_scraper') as connection:
            yield connection
    except psycopg.Error as error:
        # Do not echo a driver's raw error or the URL into a public CLI message.
        raise DatabaseAccessError(
            "PostgreSQL operation failed; check server access, permissions, and schema"
        ) from error
