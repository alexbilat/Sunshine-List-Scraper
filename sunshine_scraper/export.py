"""Write TSV atomically so a failed export preserves the previous output."""
import csv
import os
import tempfile
from pathlib import Path

COLUMNS = ('Name', 'Salary', 'Job Title', 'Employer', 'Year', 'UUID')


def write_records(records, output_path):
    """Write beside the destination, then replace it only after closing the file."""
    destination = Path(output_path)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='',
                dir=destination.parent, prefix=f'.{destination.name}.',
                suffix='.tmp', delete=False) as output_file:
            temporary_path = Path(output_file.name)
            writer = csv.DictWriter(output_file, fieldnames=COLUMNS,
                                    delimiter='\t', lineterminator='\n')
            writer.writeheader()
            writer.writerows(records)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
