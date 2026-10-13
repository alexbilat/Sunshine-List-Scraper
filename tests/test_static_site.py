"""Offline checks for the static public site: building and publishing.

Building uses a fake SalaryReader. Publishing pushes to a bare Git repository
in a temporary folder, standing in for GitHub, so nothing leaves the machine.
"""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from sunshine_scraper.api.app import app, get_open_reader
from sunshine_scraper import static_site
from sunshine_scraper.static_site import PublishError, build_from_database, build_site, publish
from sunshine_scraper.storage import connection as connection_module
from sunshine_scraper.storage.models import SalaryResult

from fakes import FakeSalaryReader

GENERATED_AT = datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


class BuildSiteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.site = Path(temporary.name) / 'site'
        # test_json_matches_the_live_api_exactly calls the API, and the rate
        # limiter is shared app state; start each test with a full budget.
        app.state.rate_limiter.reset()

    def test_writes_page_in_static_mode_and_all_data_files(self):
        reader = FakeSalaryReader()
        self.assertEqual(build_site(reader, self.site, GENERATED_AT), 1)
        html = (self.site / 'index.html').read_text(encoding='utf-8')
        self.assertIn('<meta name="data-source" content="static">', html)
        self.assertNotIn('content="api"', html)
        for name in ['app.js', 'styles.css', '.nojekyll', 'data/years.json',
                     'data/titles.json', 'data/salaries/2024.json', 'data/meta.json']:
            self.assertTrue((self.site / name).is_file(), name)
        # A year with nobody listed gets no file (the page never offers it).
        self.assertFalse((self.site / 'data/salaries/2023.json').exists())
        # The largest list the page can ask for is stored.
        self.assertEqual(reader.calls, [('yearly_summary',), ('top_job_titles', 100),
                                        ('get_top_salaries', 2024, 100)])
        self.assertEqual(read_json(self.site / 'data/meta.json'),
                         {'generated_at': '2026-10-12T15:30:00+00:00'})

    def test_json_matches_the_live_api_exactly(self):
        # The page treats both sources the same, so the shapes must be identical.
        reader = FakeSalaryReader()
        build_site(reader, self.site, GENERATED_AT)
        app.dependency_overrides[get_open_reader] = lambda: (lambda: nullcontext(reader))
        self.addCleanup(app.dependency_overrides.clear)
        client = TestClient(app)
        self.assertEqual(read_json(self.site / 'data/years.json'), client.get('/api/years').json())
        self.assertEqual(read_json(self.site / 'data/titles.json'),
                         client.get('/api/titles/top', params={'limit': 100}).json())
        self.assertEqual(read_json(self.site / 'data/salaries/2024.json'),
                         client.get('/api/salaries/top', params={'year': 2024, 'limit': 100}).json())

    def test_text_is_stored_as_data_not_markup(self):
        reader = FakeSalaryReader(salaries=[
            SalaryResult('Zoë', 'Example', 'Hôpital <b>Example</b>', 12345678)])
        build_site(reader, self.site, GENERATED_AT)
        salary = read_json(self.site / 'data/salaries/2024.json')[0]
        # Unchanged text: escaping is the page's job (textContent), and
        # accented names stay readable.
        self.assertEqual(salary['employer'], 'Hôpital <b>Example</b>')
        self.assertEqual(salary['name'], 'Zoë Example')

    def test_empty_database_is_refused(self):
        with self.assertRaises(PublishError):
            build_site(FakeSalaryReader(years=[]), self.site, GENERATED_AT)


class BuildFromDatabaseTests(unittest.TestCase):
    """The replace-on-success wrapper, with the database patched out."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.connection = MagicMock()
        for patcher in [
                # Patched one level down, so the real open_read_only_connection
                # still runs and its SET TRANSACTION READ ONLY can be checked.
                patch.object(connection_module, 'open_connection',
                             return_value=nullcontext(self.connection)),
                patch.object(static_site, 'PostgresSalaryRepository',
                             side_effect=lambda connection: self.reader)]:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.reader = FakeSalaryReader()
        self.settings = MagicMock()

    def test_reads_in_a_read_only_transaction_and_replaces_an_old_build(self):
        site = self.root / 'site'
        build_from_database(site, self.settings)
        (site / 'stale.txt').write_text('from an old build')
        build_from_database(site, self.settings)
        self.assertFalse((site / 'stale.txt').exists())
        self.connection.execute.assert_any_call('SET TRANSACTION READ ONLY')

    def test_failed_build_keeps_the_previous_site(self):
        site = self.root / 'site'
        build_from_database(site, self.settings)
        self.reader = FakeSalaryReader(years=[])
        with self.assertRaises(PublishError):
            build_from_database(site, self.settings)
        self.assertTrue((site / 'data/salaries/2024.json').is_file())

    def test_never_deletes_a_folder_it_did_not_build(self):
        precious = self.root / 'project'
        precious.mkdir()
        (precious / 'important.py').write_text('keep me')
        with self.assertRaises(PublishError):
            build_from_database(precious, self.settings)
        self.assertTrue((precious / 'important.py').is_file())


def run_git(*arguments, cwd):
    return subprocess.run(['git', *arguments], cwd=cwd, check=True,
                          capture_output=True, text=True).stdout


class PublishTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        # A fixed identity, so the test works on machines without git config.
        identity = patch.dict(os.environ, {
            'GIT_AUTHOR_NAME': 'Test', 'GIT_AUTHOR_EMAIL': 'test@example.com',
            'GIT_COMMITTER_NAME': 'Test', 'GIT_COMMITTER_EMAIL': 'test@example.com'})
        identity.start()
        self.addCleanup(identity.stop)
        # "GitHub": a bare repository. "Project": a clone whose origin is it.
        self.remote = root / 'remote.git'
        run_git('init', '--bare', '--quiet', str(self.remote), cwd=root)
        self.project = root / 'project'
        self.project.mkdir()
        run_git('init', '--quiet', cwd=self.project)
        run_git('remote', 'add', 'origin', str(self.remote), cwd=self.project)
        self.site = root / 'site'
        build_site(FakeSalaryReader(), self.site, GENERATED_AT)

    def published_files(self):
        listing = run_git('ls-tree', '-r', '--name-only', 'gh-pages', cwd=self.remote)
        return set(listing.split())

    def test_pushes_the_site_to_the_pages_branch(self):
        publish(self.site, 'gh-pages', repository=self.project)
        self.assertIn('index.html', self.published_files())
        self.assertIn('data/salaries/2024.json', self.published_files())
        # The project's own repository is untouched: no commits, no branch.
        self.assertEqual(run_git('branch', '--list', cwd=self.project), '')

    def test_each_publish_replaces_the_branch_with_one_commit(self):
        publish(self.site, 'gh-pages', repository=self.project)
        (self.site / 'data/salaries/2024.json').unlink()
        publish(self.site, 'gh-pages', repository=self.project)
        self.assertNotIn('data/salaries/2024.json', self.published_files())
        count = run_git('rev-list', '--count', 'gh-pages', cwd=self.remote).strip()
        self.assertEqual(count, '1')

    def test_refuses_to_publish_without_a_built_site(self):
        with self.assertRaises(PublishError):
            publish(self.site / 'missing', 'gh-pages', repository=self.project)

    def test_git_failure_is_reported(self):
        run_git('remote', 'set-url', 'origin', str(self.project / 'nowhere.git'), cwd=self.project)
        with self.assertRaises(PublishError) as raised:
            publish(self.site, 'gh-pages', repository=self.project)
        self.assertIn('git push failed', str(raised.exception))

    def test_credentials_in_the_remote_url_never_reach_messages(self):
        # A token in the origin URL would otherwise be logged by publish_site.py
        # (the returned URL) or shown in a PublishError (git's stderr).
        secret_url = 'https://alex:ghp_s3cret@github.com/alex/repo.git'
        self.assertEqual(static_site.hide_credentials(f'fatal: {secret_url} denied'),
                         'fatal: https://***@github.com/alex/repo.git denied')
        failed = subprocess.CompletedProcess([], 128, '', f'fatal: unable to access {secret_url}')
        with patch.object(static_site.subprocess, 'run', return_value=failed), \
                self.assertRaises(PublishError) as raised:
            static_site.git(['push', secret_url], cwd=self.project)
        self.assertNotIn('ghp_s3cret', str(raised.exception))


if __name__ == '__main__':
    unittest.main()
