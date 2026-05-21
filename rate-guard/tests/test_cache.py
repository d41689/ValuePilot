import threading
import time

from app.cache import ResponseCache


def test_put_then_get_roundtrip(tmp_path):
    cache = ResponseCache(str(tmp_path))
    key = ResponseCache.key("edgar", "GET", "https://www.sec.gov/y")
    assert cache.get(key, ttl_s=3600) is None  # miss before put

    cache.put(key, 200, {"content-type": "text/plain"}, "Ym9keQ==")
    entry = cache.get(key, ttl_s=3600)
    assert entry["status"] == 200
    assert entry["body_b64"] == "Ym9keQ=="
    assert entry["headers"]["content-type"] == "text/plain"


def test_get_returns_none_when_ttl_disabled_or_expired(tmp_path):
    cache = ResponseCache(str(tmp_path))
    key = ResponseCache.key("edgar", "GET", "https://www.sec.gov/z")
    cache.put(key, 200, {}, "")

    assert cache.get(key, ttl_s=3600) is not None
    assert cache.get(key, ttl_s=0) is None  # 0 disables the cache
    time.sleep(0.05)
    assert cache.get(key, ttl_s=0.01) is None  # 0.05s old > 0.01s ttl


def test_concurrent_put_same_key_does_not_crash(tmp_path):
    """Two callers racing on the same immutable resource is the cache's
    designed-for workload — concurrent put() on one key must not crash."""
    cache = ResponseCache(str(tmp_path))
    key = ResponseCache.key("edgar", "GET", "https://www.sec.gov/shared")
    errors: list[Exception] = []

    def worker():
        for _ in range(40):
            try:
                cache.put(key, 200, {"content-type": "text/plain"}, "Ym9keQ==")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"{len(errors)} concurrent put(s) crashed: {errors[:3]}"
    # The cache still serves a valid, complete entry afterwards.
    entry = cache.get(key, ttl_s=3600)
    assert entry is not None
    assert entry["status"] == 200
    assert entry["body_b64"] == "Ym9keQ=="
    # No temp files leaked into the shard directory.
    leftovers = list(cache._path(key).parent.glob("*.tmp"))
    assert leftovers == [], f"leaked temp files: {leftovers}"


def test_key_varies_by_upstream_method_url_and_body():
    keys = {
        ResponseCache.key("edgar", "GET", "https://x/a"),
        ResponseCache.key("dataroma", "GET", "https://x/a"),
        ResponseCache.key("edgar", "GET", "https://x/b"),
        ResponseCache.key("edgar", "POST", "https://x/a", b"body"),
    }
    assert len(keys) == 4
