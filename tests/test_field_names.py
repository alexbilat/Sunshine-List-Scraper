"""Column-label matching and alias preference in processing.py."""
import unittest

from sunshine_scraper.processing import get_record_field, normalize_field_name


class FieldNameTests(unittest.TestCase):
    def test_labels_ignore_case_underscores_bom_and_spacing(self):
        self.assertEqual(normalize_field_name('﻿ Job_Title  '), 'job title')

    def test_non_text_label_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_field_name(None)

    def test_first_nonempty_alias_wins_and_zero_counts_as_present(self):
        self.assertEqual(get_record_field({'last name': ' ', 'surname': 'Lee'}, 'last_name'), 'Lee')
        self.assertEqual(get_record_field({'salary paid': 0}, 'salary'), 0)
        self.assertIsNone(get_record_field({}, 'employer'))


if __name__ == '__main__':
    unittest.main()
