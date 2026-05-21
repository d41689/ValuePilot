"""On-disk response cache.

Keyed by (upstream, method, url, body) so two callers asking for the same
immutable EDGAR archive file share one fetch. A hit skips the upstream call
*and* the token bucket entirely.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


class ResponseCache:
    def __init__(self, root: str) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(upstream: str, method: str, url: str, body: bytes = b"") -> str:
        h = hashlib.sha256()
        for part in (upstream, method.upper(), url):
            h.update(part.encode("utf-8"))
            h.update(b"\x00")
        h.update(body)
        return h.hexdigest()

    def _path(self, key: str) -> Path:
        return self._root / key[:2] / f"{key}.json"

    def get(self, key: str, ttl_s: float) -> dict | None:
        """Return a cached entry if present and within `ttl_s`, else None."""
        if ttl_s <= 0:
            return None
        try:
            entry = json.loads(self._path(key).read_text())
        except (FileNotFoundError, ValueError, OSError):
            return None
        if time.time() - float(entry.get("stored_at", 0.0)) > ttl_s:
            return None
        return entry

    def put(self, key: str, status: int, headers: dict, body_b64: str) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "status": status,
                "headers": headers,
                "body_b64": body_b64,
                "stored_at": time.time(),
            }
        )
        # Each write gets its own temp file: two threads writing the same key
        # must not share one `.tmp` name, or the second os.replace races on a
        # file the first already renamed away (FileNotFoundError → HTTP 500).
        fd, tmp_name = tempfile.mkstemp(
            dir=path.parent, prefix=f"{key}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(payload)
            os.replace(tmp_name, path)  # atomic publish
        except BaseException:
            # Never leak the temp file if the write or replace fails.
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass
            raise
