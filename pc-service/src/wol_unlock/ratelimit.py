"""Token-bucket rate limiting, keyed independently by source IP and device.

Applied before any signature verification, because Ed25519 verification is cheap
but not free and an unauthenticated peer should not be able to spend the CPU.
"""

from __future__ import annotations

import time
from dataclasses import dataclass


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class RateLimiter:
    def __init__(self, per_minute: int, burst: int, *, max_keys: int = 4096) -> None:
        self._rate = per_minute / 60.0
        self._burst = float(burst)
        self._max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str, *, cost: float = 1.0, now: float | None = None) -> bool:
        """Consume ``cost`` tokens for ``key``; False once the bucket is empty."""
        now = time.monotonic() if now is None else now
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._evict(now)
            bucket = _Bucket(tokens=self._burst, updated=now)
            self._buckets[key] = bucket
        else:
            elapsed = max(0.0, now - bucket.updated)
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate)
            bucket.updated = now

        if bucket.tokens < cost:
            return False
        bucket.tokens -= cost
        return True

    def _evict(self, now: float) -> None:
        """Drop buckets that have refilled completely -- they carry no state.

        Bounds memory so a peer cycling through source addresses cannot grow the
        table without limit.
        """
        stale = [
            key
            for key, bucket in self._buckets.items()
            if bucket.tokens + (now - bucket.updated) * self._rate >= self._burst
        ]
        for key in stale:
            del self._buckets[key]
        if len(self._buckets) >= self._max_keys:
            # Still full: forget the least recently touched half.
            ordered = sorted(self._buckets.items(), key=lambda kv: kv[1].updated)
            for key, _ in ordered[: len(ordered) // 2]:
                del self._buckets[key]

    def reset(self) -> None:
        self._buckets.clear()
