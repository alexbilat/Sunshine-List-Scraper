"""PostgreSQL foundation, separate from collection and file export.

Importing this package does not connect, create tables, or import Psycopg.
The scraper does not write to PostgreSQL until a sync service is introduced.
"""
