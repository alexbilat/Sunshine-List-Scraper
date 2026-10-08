"""PostgreSQL storage: models, connection, migrations, and SQL repositories.

Importing this package does not connect, create tables, or import Psycopg.
sunshine_scraper.sync decides what to write; these modules translate it to SQL.
"""
