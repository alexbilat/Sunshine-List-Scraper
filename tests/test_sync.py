"""Offline checks for the sync algorithm: what is fetched, skipped, and recorded.

A fake writer records calls instead of running SQL, and network functions are
patched. SQL behaviour is covered by tests/test_postgres_integration.py.
"""
import unittest
from unittest.mock import MagicMock, patch

import psycopg

from sunshine_scraper.client import CsvDownload
from sunshine_scraper.errors import ScraperError
from sunshine_scraper.storage.writer import LoadCounts, SourceState
from sunshine_scraper.sync import run_sync

CKAN_LINK = 'https://data.ontario.ca/dataset/x/resource/old-id'
CSV_LINK = 'https://www.ontario.ca/artifacts/2025/Compendium/new-id/data.csv'


def row(first='Alex', salary='$123,456.00'):
    return {'First Name': first, 'Last Name': 'Bilat', 'Job Title': 'Developer',
            'Employer': 'Ontario', 'Calendar Year': '2024', 'Salary Paid': salary}


class FakeWriter:
    """Records what the sync asked the database to do."""

    def __init__(self, states=None, locked=False, load_error=None):
        self.states = states or {}
        self.locked = locked
        self.load_error = load_error
        self.loaded = {}
        self.marked_loaded = {}
        self.marked_unchanged = []
        self.results = []
        self.finished = None
        self.released = False

    def try_acquire_sync_lock(self):
        return not self.locked

    def release_sync_lock(self):
        self.released = True

    def start_run(self, started_at):
        return 7

    def finish_run(self, run_id, **summary):
        self.finished = summary

    def register_source(self, resource_id, source_url, source_kind):
        pass

    def get_source_state(self, resource_id):
        return self.states.get(resource_id)

    def load_disclosures(self, resource_id, disclosures):
        if self.load_error:
            raise self.load_error
        self.loaded[resource_id] = disclosures
        return LoadCounts(inserted=len(disclosures), refreshed=0)

    def mark_source_loaded(self, resource_id, **validators):
        self.marked_loaded[resource_id] = validators

    def mark_source_unchanged(self, resource_id, **validators):
        self.marked_unchanged.append(resource_id)

    def record_resource_result(self, run_id, result):
        self.results.append(result)


class SyncTests(unittest.TestCase):
    def sync(self, writer, links=(CKAN_LINK, CSV_LINK), full_refresh=False, **overrides):
        """Run the sync with patched network functions; return (result, mocks).

        overrides replaces one network function's patch options, e.g.
        fetch_csv_download={'return_value': None} simulates HTTP 304.
        """
        mocks = {}
        patches = {
            'discover_resource_links': {'return_value': list(links)},
            'fetch_all_records': {'return_value': [row()]},
            'fetch_csv_download': {'return_value': CsvDownload([row('Other')], '"e1"', 'Mon',
                                                               'c' * 64)},
            'fetch_ckan_resource_version': {'return_value': 'v1'},
        }
        patches.update(overrides)
        started = []
        for name, options in patches.items():
            patcher = patch(f'sunshine_scraper.sync.{name}', **options)
            mocks[name] = patcher.start()
            started.append(patcher)
        try:
            with patch('sunshine_scraper.sync.PostgresDisclosureWriter', return_value=writer):
                result = run_sync(MagicMock(), 'page', 'api', full_refresh=full_refresh)
        finally:
            for patcher in started:
                patcher.stop()
        return result, mocks

    def test_new_datasets_are_validated_loaded_and_recorded(self):
        writer = FakeWriter()
        result, _ = self.sync(writer)
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(result.loaded, ['old-id', 'new-id'])
        self.assertEqual(writer.loaded['old-id'][0].salary_cents, 12345600)
        self.assertEqual(writer.marked_loaded['new-id']['etag'], '"e1"')
        self.assertEqual(writer.marked_loaded['old-id']['last_modified'], 'v1')
        self.assertEqual([r.status for r in writer.results], ['loaded', 'loaded'])
        self.assertEqual(writer.finished['status'], 'succeeded')
        self.assertTrue(writer.released)

    def test_one_failed_dataset_makes_a_partial_run(self):
        writer = FakeWriter()
        with self.assertLogs('sunshine_scraper.sync', level='ERROR'):
            result, _ = self.sync(writer, fetch_csv_download={'side_effect': ScraperError('down')})
        self.assertEqual(result.status, 'partial')
        self.assertEqual((result.loaded, result.failed), (['old-id'], ['new-id']))
        failure = writer.results[-1]
        self.assertEqual((failure.status, failure.error_message), ('failed', 'down'))

    def test_empty_datasets_fail_the_run(self):
        writer = FakeWriter()
        with self.assertLogs('sunshine_scraper.sync', level='ERROR'):
            result, _ = self.sync(writer, links=[CKAN_LINK],
                                  fetch_all_records={'return_value': []})
        self.assertEqual(result.status, 'failed')
        self.assertIn('no rows', writer.results[0].error_message)
        self.assertEqual(writer.loaded, {})

    def test_datasets_without_disclosures_are_loaded_with_a_warning(self):
        """Ontario's organizations-only lists have rows but no people."""
        writer = FakeWriter()
        organizations = [{'Sector': 'Crown Agencies', 'Employer': 'Example Council'}]
        with self.assertLogs('sunshine_scraper.sync', level='WARNING') as logs:
            result, _ = self.sync(writer, links=[CKAN_LINK],
                                  fetch_all_records={'return_value': organizations})
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(writer.results[0].rows_valid, 0)
        self.assertEqual(writer.results[0].rows_rejected, 1)
        self.assertIn('no disclosures', ' '.join(logs.output))

    def test_database_error_rolls_back_only_that_dataset(self):
        writer = FakeWriter(load_error=psycopg.errors.CheckViolation('bad value'))
        with self.assertLogs('sunshine_scraper.sync', level='ERROR'):
            result, _ = self.sync(writer, links=[CKAN_LINK])
        self.assertEqual(result.failed, ['old-id'])
        self.assertEqual(writer.results[0].error_message, 'bad value')

    def test_locked_database_does_nothing(self):
        writer = FakeWriter(locked=True)
        with self.assertLogs('sunshine_scraper.sync', level='WARNING'):
            result, mocks = self.sync(writer)
        self.assertEqual(result.status, 'locked')
        mocks['discover_resource_links'].assert_not_called()
        self.assertFalse(writer.released)

    def test_discovery_failure_finishes_the_run_and_raises(self):
        writer = FakeWriter()
        with patch('sunshine_scraper.sync.discover_resource_links',
                   side_effect=ScraperError('page moved')), \
                patch('sunshine_scraper.sync.PostgresDisclosureWriter', return_value=writer):
            with self.assertRaises(ScraperError):
                run_sync(MagicMock(), 'page', 'api')
        self.assertEqual(writer.finished['status'], 'failed')
        self.assertTrue(writer.released)

    def test_unchanged_sources_are_not_downloaded_or_rewritten(self):
        """A 304 for the CSV and an equal CKAN timestamp skip both downloads."""
        writer = FakeWriter(states={'old-id': SourceState(None, 'v1', 'a' * 64),
                                    'new-id': SourceState('"e1"', 'Mon', 'c' * 64)})
        result, mocks = self.sync(writer, fetch_csv_download={'return_value': None})
        self.assertEqual(result.status, 'succeeded')
        self.assertEqual(result.unchanged, ['old-id', 'new-id'])
        self.assertEqual(writer.marked_unchanged, ['old-id', 'new-id'])
        self.assertEqual(writer.loaded, {})
        mocks['fetch_all_records'].assert_not_called()

    def test_conditional_and_hash_checks(self):
        states = {'old-id': SourceState(None, 'old-version', None),
                  'new-id': SourceState('"e1"', 'Mon', 'c' * 64)}
        writer = FakeWriter(states=states)
        result, mocks = self.sync(writer, fetch_csv_download={'return_value': None})
        # The CSV server answered 304: unchanged, with our stored validators sent.
        self.assertEqual(mocks['fetch_csv_download'].call_args.kwargs['etag'], '"e1"')
        self.assertIn('new-id', result.unchanged)
        # CKAN's timestamp moved, so the rows were downloaded and loaded.
        self.assertIn('old-id', result.loaded)
        mocks['fetch_all_records'].assert_called_once()

    def test_identical_content_without_validators_is_unchanged(self):
        from sunshine_scraper.client import records_sha256
        rows = [row()]
        writer = FakeWriter(states={'old-id': SourceState(None, None, records_sha256(rows))})
        result, _ = self.sync(writer, links=[CKAN_LINK],
                              fetch_all_records={'return_value': rows},
                              fetch_ckan_resource_version={'return_value': None})
        self.assertEqual(result.unchanged, ['old-id'])
        self.assertEqual(writer.loaded, {})

    def test_full_refresh_ignores_stored_validators(self):
        writer = FakeWriter(states={'old-id': SourceState(None, 'v1', 'a' * 64)})
        result, mocks = self.sync(writer, links=[CKAN_LINK], full_refresh=True)
        self.assertEqual(result.loaded, ['old-id'])
        mocks['fetch_all_records'].assert_called_once()


if __name__ == '__main__':
    unittest.main()
