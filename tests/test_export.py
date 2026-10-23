"""write_records must publish atomically and quote awkward text."""
import tempfile
import unittest
from pathlib import Path

from sunshine_scraper.export import COLUMNS, write_records


class WriteRecordsTests(unittest.TestCase):
    def test_writes_header_and_rows_and_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.txt'
            write_records([dict.fromkeys(COLUMNS, 'a\tb')], path)
            lines = path.read_text(encoding='utf-8').splitlines()
            self.assertEqual(lines[0], '\t'.join(COLUMNS))
            self.assertIn('"a\tb"', lines[1])  # embedded tab is quoted
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['out.txt'])

    def test_failure_keeps_previous_export_and_removes_temp_file(self):
        def broken():
            yield dict.fromkeys(COLUMNS, 'x')
            raise RuntimeError('boom')

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'out.txt'
            path.write_text('old', encoding='utf-8')
            with self.assertRaises(RuntimeError):
                write_records(broken(), path)
            self.assertEqual(path.read_text(encoding='utf-8'), 'old')
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['out.txt'])


if __name__ == '__main__':
    unittest.main()
