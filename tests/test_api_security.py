"""Offline checks for API protection and the web frontend.

The limiter is tested directly with a fake clock (no sleeping), then through
TestClient to prove the middleware wires it in front of the routes. The
frontend tests confirm the page is served with its security headers and that
mounting it at '/' does not hide the API.
"""
from contextlib import nullcontext
import os
import threading
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
import psycopg

import config
import sunshine_scraper.api.app as app_module  # the module, to patch query_slots
from sunshine_scraper.api.app import app, get_open_reader
from sunshine_scraper.api.ratelimit import RateLimiter


class FakeClock:
    """A clock that only moves when a test says so."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class RateLimiterTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        # 3 requests at once, then one more every 2 seconds.
        self.limiter = RateLimiter(capacity=3, refill_per_second=0.5, clock=self.clock)

    def test_allows_a_burst_up_to_capacity_then_refuses(self):
        self.assertEqual([self.limiter.check('a') for _ in range(3)], [None, None, None])
        self.assertAlmostEqual(self.limiter.check('a'), 2.0)

    def test_refused_requests_do_not_spend_tokens(self):
        for _ in range(3):
            self.limiter.check('a')
        # Hammering while blocked must not push the wait further out.
        for _ in range(5):
            self.assertAlmostEqual(self.limiter.check('a'), 2.0)

    def test_tokens_refill_over_time_but_never_beyond_capacity(self):
        for _ in range(3):
            self.limiter.check('a')
        self.clock.now += 1.0  # half a token: still refused, 1 second left
        self.assertAlmostEqual(self.limiter.check('a'), 1.0)
        self.clock.now += 1.0
        self.assertIsNone(self.limiter.check('a'))
        # A long idle period refills to capacity, not to an unlimited burst.
        self.clock.now += 3600
        self.assertEqual([self.limiter.check('a') for _ in range(3)], [None, None, None])
        self.assertIsNotNone(self.limiter.check('a'))

    def test_clients_have_separate_buckets(self):
        for _ in range(3):
            self.limiter.check('a')
        self.assertIsNotNone(self.limiter.check('a'))
        self.assertIsNone(self.limiter.check('b'))

    def test_reset_forgets_every_client(self):
        for _ in range(4):
            self.limiter.check('a')
        self.limiter.reset()
        self.assertIsNone(self.limiter.check('a'))

    def test_memory_is_bounded_and_idle_clients_are_dropped_first(self):
        limiter = RateLimiter(capacity=2, refill_per_second=1, max_clients=2, clock=self.clock)
        limiter.check('idle')           # will refill to full: carries no state
        limiter.check('busy')
        limiter.check('busy')           # empty bucket: must be remembered
        self.clock.now += 1.5           # idle is full again, busy is not
        limiter.check('new')
        self.assertEqual(set(limiter._buckets), {'busy', 'new'})

    def test_memory_cap_holds_even_when_every_client_is_mid_limit(self):
        limiter = RateLimiter(capacity=1, refill_per_second=0.001, max_clients=2, clock=self.clock)
        limiter.check('first')
        self.clock.now += 1
        limiter.check('second')
        self.clock.now += 1
        limiter.check('third')          # nobody is full: the longest idle goes
        self.assertEqual(set(limiter._buckets), {'second', 'third'})

    def test_rejects_nonsense_settings(self):
        for kwargs in [{'capacity': 0, 'refill_per_second': 1},
                       {'capacity': 1, 'refill_per_second': 0}]:
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                RateLimiter(**kwargs)


class FakeSalaryReader:
    def __init__(self):
        self.calls = 0

    def yearly_summary(self):
        self.calls += 1
        return []


class RateLimitMiddlewareTests(unittest.TestCase):
    def setUp(self):
        self.reader = FakeSalaryReader()
        app.dependency_overrides[get_open_reader] = lambda: (lambda: nullcontext(self.reader))
        self.addCleanup(app.dependency_overrides.clear)
        # Swap in a tiny limit (2 requests, effectively no refill) for these tests.
        original = app.state.rate_limiter
        app.state.rate_limiter = RateLimiter(capacity=2, refill_per_second=0.01)
        self.addCleanup(setattr, app.state, 'rate_limiter', original)
        self.client = TestClient(app)

    def test_too_many_api_requests_get_429_with_retry_after(self):
        for _ in range(2):
            self.assertEqual(self.client.get('/api/years').status_code, 200)
        with self.assertLogs('sunshine_scraper.api.app', level='WARNING') as logs:
            response = self.client.get('/api/years', params={'secret': 'typed-by-client'})
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.json(), {'detail': 'Too many requests'})
        # 1 token at 0.01 tokens/second = 100 seconds, sent as whole seconds.
        self.assertEqual(response.headers['Retry-After'], '100')
        # The refused request never reached the route or the database.
        self.assertEqual(self.reader.calls, 2)
        # The log names the path but not the query string.
        self.assertNotIn('typed-by-client', ''.join(logs.output))

    def test_refused_responses_still_carry_security_headers(self):
        for _ in range(3):
            response = self.client.get('/api/years')
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_static_files_do_not_use_up_the_api_budget(self):
        for _ in range(5):
            self.assertEqual(self.client.get('/').status_code, 200)
        self.assertEqual(self.client.get('/api/years').status_code, 200)

    def test_spoofed_forwarded_for_header_does_not_bypass_the_limit(self):
        for number in range(3):
            response = self.client.get('/api/years',
                                       headers={'X-Forwarded-For': f'10.0.0.{number}'})
        self.assertEqual(response.status_code, 429)


class QuerySlotTests(unittest.TestCase):
    """The cap on simultaneous database queries, using the real connection code."""

    def setUp(self):
        app.state.rate_limiter.reset()
        self.client = TestClient(app)
        for patcher in [patch.dict(os.environ, {'SUNSHINE_DATABASE_URL': 'postgresql://x@db/x'}),
                        patch.object(config, 'api_query_wait_seconds', 0)]:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_busy_slots_give_503_without_connecting(self):
        with patch.object(app_module, 'query_slots', threading.BoundedSemaphore(1)) as slots:
            slots.acquire()  # another request is holding the only slot
            with patch('psycopg.connect') as connect, \
                    self.assertLogs('sunshine_scraper.api.app', level='ERROR'):
                response = self.client.get('/api/health')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'detail': 'Database unavailable'})
        connect.assert_not_called()

    def test_slot_is_given_back_even_when_the_query_fails(self):
        slots = threading.BoundedSemaphore(1)
        with patch.object(app_module, 'query_slots', slots), \
                patch('psycopg.connect', side_effect=psycopg.OperationalError('down')), \
                self.assertLogs('sunshine_scraper.api.app', level='ERROR'):
            for _ in range(2):  # the second request would 503 for "busy" if leaked
                self.assertEqual(self.client.get('/api/health').status_code, 503)
        # Exactly one slot free again: a leaked slot would make this fail, and
        # an extra release would have raised ValueError (BoundedSemaphore).
        self.assertTrue(slots.acquire(blocking=False))
        self.assertFalse(slots.acquire(blocking=False))


class FrontendTests(unittest.TestCase):
    def setUp(self):
        app.state.rate_limiter.reset()
        self.client = TestClient(app)

    def test_home_page_is_served_with_strict_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn('text/html', response.headers['content-type'])
        self.assertIn('Ontario Sunshine List', response.text)
        policy = response.headers['Content-Security-Policy']
        self.assertIn("script-src 'self'", policy)
        self.assertIn("frame-ancestors 'none'", policy)
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')

    def test_page_has_no_inline_script_or_style(self):
        # The policy forbids inline code, so any added later would silently
        # fail in the browser. Catch it here instead.
        html = self.client.get('/').text
        self.assertNotIn('<script>', html)
        self.assertNotIn('style=', html)
        self.assertNotIn('<style', html)

    def test_script_and_stylesheet_are_served(self):
        for path, content_type in [('/app.js', 'javascript'), ('/styles.css', 'text/css')]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(content_type, response.headers['content-type'])

    def test_frontend_never_parses_data_as_html(self):
        # Names and employers are external data; they must be set as text.
        # The pattern matches property use, so comments may still name it.
        script = self.client.get('/app.js').text
        self.assertNotRegex(script, r'\.(innerHTML|outerHTML|insertAdjacentHTML)\b')
        self.assertNotIn('document.write', script)
        # ASCII only, so the script can't be garbled by a charset guess.
        self.assertTrue(script.isascii())

    def test_mount_does_not_hide_the_api_or_docs(self):
        app.dependency_overrides[get_open_reader] = lambda: (lambda: nullcontext(FakeSalaryReader()))
        self.addCleanup(app.dependency_overrides.clear)
        self.assertEqual(self.client.get('/api/years').json(), [])
        self.assertEqual(self.client.get('/openapi.json').status_code, 200)
        docs = self.client.get('/docs')
        self.assertEqual(docs.status_code, 200)
        # Swagger UI needs a CDN script, so /docs is exempt from the policy.
        self.assertNotIn('Content-Security-Policy', docs.headers)

    def test_unknown_paths_are_404(self):
        self.assertEqual(self.client.get('/no-such-page').status_code, 404)
        self.assertEqual(self.client.get('/api/no-such-route').status_code, 404)

    def test_only_reads_are_allowed_on_the_frontend_too(self):
        self.assertEqual(self.client.post('/').status_code, 405)


if __name__ == '__main__':
    unittest.main()
