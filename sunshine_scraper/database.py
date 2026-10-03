""" Main file for sqlite database"""

# Importing
import sqlite3

connection = sqlite3.connect('sunshine.db')

rows = connection.execute(
    """
    SELECT name, employer, salary_cents
    FROM salary_records
    WHERE year = ?
    ORDER BY salary_cents DESC
    LIMIT 10
    """,
    (2024,),
).fetchall()


for row in rows:
    print(row)

connection.close()







