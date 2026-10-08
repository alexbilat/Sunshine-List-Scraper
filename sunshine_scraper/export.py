"""Write TSV atomically so a failed export preserves the previous output."""
import csv
import os
import tempfile
from pathlib import Path

COLUMNS = ('Name', 'Salary', 'Job Title', 'Employer', 'Year', 'UUID')


def write_records(records, output_path):
    """Write a six-column TSV without truncating an existing export on failure.

    records may be any iterable of dictionaries, including a generator that
    streams rows from the database, so the file never needs them all in memory.

    File errors propagate to the CLI. The temporary file is in the destination
    directory so os.replace operates within one filesystem.
    """
    destination = Path(output_path)
    temporary_path = None  # No temporary file exists yet if opening fails.
    try:
        # with closes the file even on failure. delete=False lets us rename it
        # after closing, which is required for replacement on Windows.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                dir=destination.parent, prefix=f'.{destination.name}.',
                suffix='.tmp', delete=False) as output_file:
            temporary_path = Path(output_file.name)
            # A TSV is CSV with tab delimiters. DictWriter quotes embedded tabs
            # and newlines correctly; newline="" avoids extra Windows newlines.
            writer = csv.DictWriter(output_file, fieldnames=COLUMNS,
                                    delimiter='\t', lineterminator='\n')
            writer.writeheader()
            writer.writerows(records)
        # Publish only after every row has been written and the file is closed.
        os.replace(temporary_path, destination)
    finally:
        # On failure, remove the unfinished file; after replacement it is absent.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
