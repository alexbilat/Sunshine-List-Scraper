"""A small in-memory rate limiter: how many requests one client may send.

Without a limit, one script in a loop could keep every worker thread and
database connection busy, and everyone else would wait. A limit keeps one
client from crowding out the rest.

This uses a "token bucket". Each client has a bucket holding up to `capacity`
tokens. Every request takes one token; tokens drip back in at a steady rate.
A client can therefore send a short burst (up to `capacity` requests at once)
but, over time, no more than `refill_per_second` requests per second.

State lives in this process's memory. That is enough for one uvicorn process.
With several worker processes each has its own buckets, so the effective limit
multiplies; a shared store such as Redis would be the next step.
"""
from dataclasses import dataclass
import threading
import time
from typing import Callable


@dataclass
class _Bucket:
    tokens: float
    updated: float  # clock reading when `tokens` was last brought up to date


class RateLimiter:
    """Token-bucket limiter keyed by a client identifier (e.g. an IP address)."""

    def __init__(self, capacity: int, refill_per_second: float, *,
                 max_clients: int = 10_000,
                 clock: Callable[[], float] = time.monotonic):
        if capacity < 1 or refill_per_second <= 0 or max_clients < 1:
            raise ValueError('capacity, refill_per_second and max_clients must be positive')
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.max_clients = max_clients
        # monotonic, not time.time: the wall clock can jump (daylight saving,
        # NTP corrections), which would wrongly refill or drain every bucket.
        # Tests pass a fake clock so they never have to sleep.
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}
        # Middleware may be called from several threads; the lock makes the
        # read-modify-write of a bucket atomic so two requests can't both
        # spend the same last token.
        self._lock = threading.Lock()

    def check(self, key: str) -> float | None:
        """Spend one token for `key`.

        Returns None when the request may proceed, or the number of seconds
        until a token is available when it must be refused.
        """
        with self._lock:
            now = self.clock()
            bucket = self._buckets.get(key)
            if bucket is None:
                self._make_room(now)
                bucket = self._buckets[key] = _Bucket(float(self.capacity), now)
            else:
                self._refill(bucket, now)
            if bucket.tokens >= 1:
                bucket.tokens -= 1
                return None
            return (1 - bucket.tokens) / self.refill_per_second

    def reset(self) -> None:
        """Forget every client (used by tests so state can't leak between them)."""
        with self._lock:
            self._buckets.clear()

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = max(0.0, now - bucket.updated)
        bucket.tokens = min(float(self.capacity), bucket.tokens + elapsed * self.refill_per_second)
        bucket.updated = now

    def _make_room(self, now: float) -> None:
        """Keep memory bounded when a new client arrives and the table is full.

        Without a cap, requests from many different addresses would grow the
        dictionary forever. A bucket that has refilled to capacity carries no
        information (a new bucket would start the same), so those go first.
        If every client is still mid-limit, drop the one idle the longest.
        """
        if len(self._buckets) < self.max_clients:
            return
        for key, bucket in list(self._buckets.items()):
            # Work out the refilled amount without saving it, so `updated`
            # still records real activity for the fallback below.
            refilled = bucket.tokens + max(0.0, now - bucket.updated) * self.refill_per_second
            if refilled >= self.capacity:
                del self._buckets[key]
        if len(self._buckets) >= self.max_clients:
            oldest = min(self._buckets, key=lambda key: self._buckets[key].updated)
            del self._buckets[oldest]
