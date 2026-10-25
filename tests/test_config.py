"""config.py holds hand-edited settings; catch values that would break a run."""
import unittest

import config


class ConfigTests(unittest.TestCase):
    def test_retry_and_timeout_settings_are_usable(self):
        self.assertGreater(config.request_timeout, 0)
        self.assertGreaterEqual(config.max_retries, 0)
        self.assertGreaterEqual(config.retry_backoff, 0)

    def test_source_urls_are_https(self):
        for value in (config.url, config.api_url):
            self.assertTrue(value.startswith('https://'))

    def test_log_level_is_a_real_logging_level(self):
        import logging
        self.assertIsInstance(logging.getLevelName(config.log_level), int)

    def test_api_protection_limits_are_positive(self):
        for name in ('api_rate_limit_requests', 'api_rate_limit_window',
                     'api_statement_timeout_ms', 'api_max_concurrent_queries',
                     'api_query_wait_seconds'):
            with self.subTest(setting=name):
                self.assertGreater(getattr(config, name), 0)

    def test_full_refresh_is_a_bool(self):
        # A string like 'False' would be truthy and silently reload everything.
        self.assertIsInstance(config.full_refresh, bool)

    def test_publish_settings_are_not_empty(self):
        # An empty pages_branch would make publish_site.py force-push nowhere useful.
        self.assertTrue(config.site_dir.strip())
        self.assertTrue(config.pages_branch.strip())


if __name__ == '__main__':
    unittest.main()
