from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.edgar import fetcher as edgar_fetcher
from app.models.institutions import RawSourceDocument


class _StaticClient:
    """Minimal EdgarClient stub for fetch_and_store: returns canned bytes."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self.body

    def close(self) -> None:
        return None


def test_fetch_and_store_self_heals_when_cached_body_file_missing(
    db_session, tmp_path, monkeypatch
):
    """If a RawSourceDocument row exists but its body_path file is gone
    (e.g. a stale row from before the persistent edgar_raw volume was
    mounted), fetch_and_store should re-fetch the URL and update the
    row's body_path / raw_sha256 in place."""
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_FETCH_MODE", "live")

    source_url = "https://www.sec.gov/Archives/edgar/full-index/2025/QTR4/master.idx"
    stale_body_path = "/code/storage/edgar_raw/edgar/45/deadbeef.txt"
    assert not Path(stale_body_path).exists()

    stale_row = RawSourceDocument(
        source_system="edgar",
        document_type="full_index_idx",
        source_url=source_url,
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="deadbeef",
        body_path=stale_body_path,
        parse_status="parsed",
    )
    db_session.add(stale_row)
    db_session.flush()

    fresh_body = b"new EDGAR index payload"
    client = _StaticClient(fresh_body)

    result = edgar_fetcher.fetch_and_store(
        db_session,
        source_system="edgar",
        document_type="full_index_idx",
        source_url=source_url,
        client=client,
    )

    assert client.calls == [source_url], "fetcher should have called client.get exactly once"
    assert result.id == stale_row.id, "self-heal should update the existing row, not insert a new one"
    assert Path(result.body_path).exists(), "new body file should be written to disk"
    assert Path(result.body_path).read_bytes() == fresh_body
    assert result.raw_sha256 != "deadbeef", "raw_sha256 should be recomputed from the fresh body"
    assert result.parse_status == "pending", "self-heal resets parse_status for re-processing"


def test_fetch_and_store_returns_cached_row_when_body_file_exists(
    db_session, tmp_path, monkeypatch
):
    """Sanity check the happy path: when the cached row's body file does
    exist, fetch_and_store returns it without re-fetching."""
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_FETCH_MODE", "live")

    cached_file = tmp_path / "edgar" / "ab" / "abcd.txt"
    cached_file.parent.mkdir(parents=True, exist_ok=True)
    cached_file.write_bytes(b"cached payload")

    source_url = "https://www.sec.gov/Archives/edgar/full-index/2025/QTR3/master.idx"
    row = RawSourceDocument(
        source_system="edgar",
        document_type="full_index_idx",
        source_url=source_url,
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="abcd",
        body_path=str(cached_file),
        parse_status="parsed",
    )
    db_session.add(row)
    db_session.flush()

    client = _StaticClient(b"should not be fetched")

    result = edgar_fetcher.fetch_and_store(
        db_session,
        source_system="edgar",
        document_type="full_index_idx",
        source_url=source_url,
        client=client,
    )

    assert client.calls == [], "happy path must not re-fetch"
    assert result.id == row.id
    assert result.body_path == str(cached_file)


def test_fetch_and_store_replay_mode_raises_when_body_file_missing(
    db_session, tmp_path, monkeypatch
):
    """Replay mode is a debug contract: do not silently fall back to a
    live fetch when the file is missing — raise so the caller sees it."""
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(edgar_fetcher.settings, "EDGAR_FETCH_MODE", "replay")

    source_url = "https://www.sec.gov/Archives/edgar/full-index/2025/QTR2/master.idx"
    row = RawSourceDocument(
        source_system="edgar",
        document_type="full_index_idx",
        source_url=source_url,
        http_status=200,
        fetched_at=datetime.now(timezone.utc),
        raw_sha256="abcd",
        body_path="/tmp/does-not-exist-replay.txt",
        parse_status="parsed",
    )
    db_session.add(row)
    db_session.flush()

    client = _StaticClient(b"never used in replay")

    with pytest.raises(RuntimeError, match="body file missing"):
        edgar_fetcher.fetch_and_store(
            db_session,
            source_system="edgar",
            document_type="full_index_idx",
            source_url=source_url,
            client=client,
        )

    assert client.calls == [], "replay mode must not fetch"
