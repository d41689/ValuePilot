import time

from app.bucket import TokenBucket


def test_first_acquire_is_immediate():
    bucket = TokenBucket(rate_per_sec=10.0, burst=1)
    assert bucket.acquire() == 0.0


def test_acquire_waits_once_the_bucket_is_empty():
    bucket = TokenBucket(rate_per_sec=20.0, burst=1)
    bucket.acquire()  # consume the single token
    start = time.monotonic()
    bucket.acquire()  # must wait ~1/20s for a refill
    waited = time.monotonic() - start
    assert waited >= 0.03  # ~0.05s expected; generous slack for CI


def test_burst_allows_several_immediate_acquires():
    bucket = TokenBucket(rate_per_sec=1.0, burst=3)
    assert bucket.acquire() == 0.0
    assert bucket.acquire() == 0.0
    assert bucket.acquire() == 0.0
    assert bucket.acquire() > 0.0  # 4th must wait
