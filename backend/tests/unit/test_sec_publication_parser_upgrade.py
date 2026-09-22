"""Parser upgrades preserve exact publication replay, not old-parser new writes."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.services import sec_metric_publication as publication
from app.services.canonical_financials import resolve_sec_publication_evidence
from app.services.sec_financial_ingestion import (
    PARSER_V2, PARSER_V2_9, PARSER_V2_10, PARSER_V2_11, ingest_latest_financial_filings,
    finalize_sec_financial_ingestion_operation,
)
from app.services.sec_financial_mapping import MappingResult
from test_sec_metric_publication_service_e2e import (
    _request, _FailedAmendmentClient, db as publication_db, isolated_engine,
)


def counts(db):
    return tuple(db.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                 for table in ("sec_metric_publication_runs", "sec_metric_publications", "metric_facts"))


def old_published_request(db, tmp_path, monkeypatch, parser_version=PARSER_V2_9):
    monkeypatch.setattr(publication, "SEC_PUBLICATION_V1_PARSER_VERSION", parser_version)
    original = _request(db, tmp_path, parser_version=parser_version)
    report = ingest_latest_financial_filings(
        db, stock_id=original.stock_id, client=_FailedAmendmentClient(), storage_root=tmp_path,
        max_filings=1, now=datetime(2026, 8, 28, 17, tzinfo=timezone.utc), parser_version=parser_version,
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    cutoff = db.execute(text(
        "SELECT max(available_at) FROM sec_financial_lineage_availabilities"
    )).scalar_one() + timedelta(seconds=1)
    sources = publication.resolve_latest_known_v1_sources(
        db, stock_id=original.stock_id, issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    assert len(sources) == 2
    request = replace(original, requested_cutoff=cutoff, sources=sources)
    receipt = publication.publish_sec_mapping_result(db, request)
    db.commit()
    publication.finalize_sec_publication(db, receipt.run_id)
    db.commit()
    monkeypatch.setattr(publication, "SEC_PUBLICATION_V1_PARSER_VERSION", PARSER_V2)
    return request, receipt


@pytest.mark.parametrize("parser_version", [PARSER_V2_9, PARSER_V2_10, PARSER_V2_11])
def test_old_parser_exact_publication_replays_and_evidence_remains_readable(
    publication_db, tmp_path, monkeypatch, parser_version,
):
    db = publication_db
    request, original = old_published_request(db, tmp_path, monkeypatch, parser_version)
    before = counts(db)
    replay = publication.publish_sec_mapping_result(db, request)
    db.commit()
    assert replay.replayed and replay.available
    assert replay.run_id == original.run_id
    assert replay.fact_ids == original.fact_ids
    assert counts(db) == before
    decision_id = db.execute(text(
        "SELECT id FROM sec_metric_publications WHERE metric_fact_id=:fact"
    ), {"fact": replay.fact_ids[0]}).scalar_one()
    evidence = resolve_sec_publication_evidence(db, stock_id=request.stock_id, publication_id=decision_id)
    assert evidence is not None
    assert {item["parser_version"] for item in evidence["filings"]} == {parser_version}


def test_old_parser_replay_rejects_changed_or_forged_requests(publication_db, tmp_path, monkeypatch):
    db = publication_db
    request, _ = old_published_request(db, tmp_path, monkeypatch)
    before = counts(db)
    bad_requests = (
        replace(request, sources=request.sources[:1]),
        replace(request, sources=tuple(reversed(request.sources))),
        replace(request, sources=(replace(request.sources[0], input_manifest_hash="f" * 64), request.sources[1])),
        replace(request, sources=(request.sources[0], replace(request.sources[1], parser_version=PARSER_V2))),
        replace(request, requested_cutoff=request.requested_cutoff + timedelta(microseconds=1)),
        replace(request, stock_id=request.stock_id + 100),
        replace(request, issuer_identity_id=request.issuer_identity_id + 100),
        replace(request, outcome=MappingResult((), (), 0)),
    )
    for bad in bad_requests:
        with pytest.raises(publication.SecPublicationError):
            publication.publish_sec_mapping_result(db, bad)
        db.rollback()
        assert counts(db) == before
    # Even a digest collision cannot authorize different ordered durable
    # sources: the digest is an index aid, never the acceptance check.
    real_identity = publication._identity
    digest = real_identity(request)[1]
    with monkeypatch.context() as patch:
        patch.setattr(publication, "_identity", lambda item: (real_identity(item)[0], digest))
        for bad in bad_requests[:4]:
            with pytest.raises(publication.SecPublicationError, match="exact homogeneous sources"):
                publication.publish_sec_mapping_result(db, bad)
            db.rollback()
            assert counts(db) == before


def test_old_parser_replay_still_rebuilds_and_rejects_changed_outcome(publication_db, tmp_path, monkeypatch):
    db = publication_db
    request, _ = old_published_request(db, tmp_path, monkeypatch)
    before = counts(db)
    real_rebuild = publication._rebuild_mapping_result
    calls = []

    def changed_rebuild(session, item, **kwargs):
        outcome = real_rebuild(session, item, **kwargs)
        calls.append(kwargs["parser_version"])
        assert outcome.candidates
        return MappingResult((), outcome.dispositions, 0)

    monkeypatch.setattr(publication, "_rebuild_mapping_result", changed_rebuild)
    with pytest.raises(publication.SecPublicationError, match="immutable replay identity"):
        publication.publish_sec_mapping_result(db, request)
    db.rollback()
    assert calls == [PARSER_V2_9]
    assert counts(db) == before


@pytest.mark.parametrize("parser_version", [PARSER_V2_9, PARSER_V2_10, PARSER_V2_11])
def test_new_publication_cannot_request_previous_parser(publication_db, tmp_path, parser_version):
    request = _request(publication_db, tmp_path, parser_version=parser_version)
    before = counts(publication_db)
    with pytest.raises(publication.SecPublicationError):
        publication.publish_sec_mapping_result(publication_db, request)
    publication_db.rollback()
    assert counts(publication_db) == before
