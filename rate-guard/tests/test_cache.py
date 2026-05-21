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


def test_key_varies_by_upstream_method_url_and_body():
    keys = {
        ResponseCache.key("edgar", "GET", "https://x/a"),
        ResponseCache.key("dataroma", "GET", "https://x/a"),
        ResponseCache.key("edgar", "GET", "https://x/b"),
        ResponseCache.key("edgar", "POST", "https://x/a", b"body"),
    }
    assert len(keys) == 4
