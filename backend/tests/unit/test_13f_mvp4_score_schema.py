"""MVP4-01 score schema tests.

TDD coverage for the precomputed scoring tables introduced by
`MVP4-01 Oracle's Lens Score Schema and ORM`. No score-computation
logic is tested here (that lands in MVP4-02 onward); these tests
pin the schema contract.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from itertools import count

import pytest
from sqlalchemy.exc import IntegrityError

from app.models.oracles_lens import (
    OraclesLensScoreComponent,
    OraclesLensSignal,
)
from app.models.stocks import Stock


_STOCK_SEQ = count(70001)


def _stock(db_session, ticker: str | None = None) -> Stock:
    seq = next(_STOCK_SEQ)
    stock = Stock(
        ticker=ticker or f"MV4{seq:05d}"[-10:],
        exchange="NYSE",
        company_name=f"Mv4Co {seq}",
    )
    db_session.add(stock)
    db_session.flush()
    return stock


def _signal(
    db_session,
    stock: Stock,
    *,
    report_quarter: str = "2026-Q1",
    score_version: str = "v1.0",
    score_confidence: str = "high_confidence",
    caution_flag_codes: list[str] | None = None,
    source_job_id: int | None = None,
) -> OraclesLensSignal:
    signal = OraclesLensSignal(
        stock_id=stock.id,
        report_quarter=report_quarter,
        quarter_end_date=date(2026, 3, 31),
        score_version=score_version,
        raw_consensus_count=3,
        signal_weighted_consensus_score=1.5,
        conviction_score=2.0,
        distinctive_consensus_score=0.75,
        add_intensity=0.10,
        holding_streak_quarters=4,
        score_confidence=score_confidence,
        caution_flag_codes=caution_flag_codes,
        score_explanation={"summary": "test"},
        computed_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        source_job_id=source_job_id,
    )
    db_session.add(signal)
    db_session.flush()
    return signal


def test_unique_constraint_on_stock_quarter_version(db_session):
    stock = _stock(db_session)
    _signal(db_session, stock)
    db_session.commit()

    duplicate = OraclesLensSignal(
        stock_id=stock.id,
        report_quarter="2026-Q1",
        quarter_end_date=date(2026, 3, 31),
        score_version="v1.0",
        raw_consensus_count=5,
        score_confidence="medium_confidence",
        computed_at=datetime(2026, 5, 11, 13, 0, tzinfo=timezone.utc),
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_different_score_versions_for_same_stock_quarter_coexist(db_session):
    stock = _stock(db_session)
    _signal(db_session, stock, score_version="v1.0")
    _signal(db_session, stock, score_version="v1.1")
    db_session.flush()
    rows = (
        db_session.query(OraclesLensSignal)
        .filter(OraclesLensSignal.stock_id == stock.id)
        .filter(OraclesLensSignal.report_quarter == "2026-Q1")
        .all()
    )
    assert {row.score_version for row in rows} == {"v1.0", "v1.1"}


@pytest.mark.parametrize(
    "value",
    ["high_confidence", "medium_confidence", "low_confidence", "unavailable"],
)
def test_score_confidence_accepts_canonical_vocabulary(db_session, value):
    stock = _stock(db_session)
    signal = _signal(db_session, stock, score_confidence=value)
    assert signal.score_confidence == value


def test_score_confidence_rejects_invalid_value(db_session):
    stock = _stock(db_session)
    with pytest.raises(ValueError, match="score_confidence"):
        _signal(db_session, stock, score_confidence="huge")


def test_caution_flag_codes_jsonb_roundtrip(db_session):
    stock = _stock(db_session)
    codes = [
        "CONFIDENTIAL_TREATMENT",
        "PARTIAL_COVERAGE",
        "OWNERSHIP_CHANGES_NEEDS_RECOMPUTE",
        "NT_QUARTER_STREAK_BREAK",
    ]
    signal = _signal(db_session, stock, caution_flag_codes=codes)
    db_session.expire_all()
    refreshed = db_session.get(OraclesLensSignal, signal.id)
    assert refreshed.caution_flag_codes == codes


def test_components_cascade_delete_when_score_removed(db_session):
    stock = _stock(db_session)
    signal = _signal(db_session, stock)
    db_session.add(
        OraclesLensScoreComponent(
            score_id=signal.id,
            component_name="manager_signal_weight",
            manager_id=None,
            numeric_value=0.85,
            string_value=None,
            evidence_json={"manager_type": "long_term_fundamental"},
        )
    )
    db_session.add(
        OraclesLensScoreComponent(
            score_id=signal.id,
            component_name="position_signal_weight",
            manager_id=None,
            numeric_value=1.20,
        )
    )
    db_session.flush()
    assert (
        db_session.query(OraclesLensScoreComponent)
        .filter_by(score_id=signal.id)
        .count()
        == 2
    )

    db_session.delete(signal)
    db_session.flush()
    assert (
        db_session.query(OraclesLensScoreComponent)
        .filter_by(score_id=signal.id)
        .count()
        == 0
    )


def test_source_job_id_accepts_null(db_session):
    stock = _stock(db_session)
    signal = _signal(db_session, stock, source_job_id=None)
    assert signal.source_job_id is None


def test_source_job_id_accepts_real_job_run_id(db_session):
    from app.models.institutions import JobRun

    job = JobRun(
        job_type="oracles_lens_score_backfill",
        status="queued",
        trigger_source="manual",
        lock_key="test:mvp4-01:source_job_id",
        dedupe_key="test:mvp4-01:source_job_id",
    )
    db_session.add(job)
    db_session.flush()

    stock = _stock(db_session)
    signal = _signal(db_session, stock, source_job_id=job.id)
    assert signal.source_job_id == job.id


def test_score_version_constant_importable():
    from app.services.oracles_lens.constants import SCORE_VERSION

    assert isinstance(SCORE_VERSION, str)
    assert SCORE_VERSION  # non-empty


def test_oracles_lens_score_backfill_job_type_registered():
    from app.services.thirteenf_job_worker import JOB_TIMEOUT_SECONDS_BY_TYPE

    assert "oracles_lens_score_backfill" in JOB_TIMEOUT_SECONDS_BY_TYPE
    # Should be > 10 min (the default fallback) given a scoring backfill
    # touches every active manager-quarter; longer timeout matches the
    # ingest_holdings_for_quarter precedent.
    assert JOB_TIMEOUT_SECONDS_BY_TYPE["oracles_lens_score_backfill"] >= 30 * 60
