"""Real random-schema PostgreSQL coverage for amendment source authority."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.models.stocks import Stock
from app.services.sec_financial_ingestion import (
    finalize_sec_financial_ingestion_operation,
    ingest_latest_financial_filings,
)
from app.services.sec_metric_publication import (
    PublicationRequest,
    SecPublicationError,
    finalize_sec_publication,
    publish_sec_mapping_result,
    resolve_latest_known_v1_sources,
)
from app.services.sec_financial_locking import acquire_sec_financial_stock_lock
from app.services.canonical_financials import active_sec_run_unresolved_states
from test_sec_metric_publication_service_e2e import (
    _FailedAmendmentClient,
    _SuccessfulLaterAmendmentClient,
    _request,
)
from test_sec_financial_lineage import CIK, _canonical_artifact_url
from test_support.database_isolation import (
    build_isolated_database_url,
    create_test_schema,
    drop_test_schema,
    new_test_schema_name,
)


BACKEND = Path(__file__).resolve().parents[2]
BASE = make_url(settings.SQLALCHEMY_DATABASE_URI).set(
    query={
        key: value
        for key, value in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items()
        if key != "options"
    }
).render_as_string(hide_password=False)


@pytest.fixture
def isolated_engine():
    schema = new_test_schema_name()
    url = build_isolated_database_url(BASE, schema)
    create_test_schema(BASE, schema)
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND,
        env={**os.environ, "DATABASE_URL": url},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    engine = create_engine(url, pool_pre_ping=True)
    try:
        yield engine
    finally:
        engine.dispose()
        drop_test_schema(BASE, schema)


@pytest.fixture
def db(isolated_engine):
    session = sessionmaker(bind=isolated_engine)()
    try:
        yield session
    finally:
        session.close()


class _ChangedSuccessfulAmendmentClient(_SuccessfulLaterAmendmentClient):
    def __init__(self):
        super().__init__()
        prefix = "https://www.sec.gov/Archives/edgar/data/320193/" + self.accession.replace("-", "") + "/"
        for url, content in tuple(self.responses.items()):
            if url.startswith(prefix) and isinstance(content, bytes):
                self.responses[url] = content.replace(b"94,000", b"95,000").replace(
                    b"250,000", b"251,000"
                )


class _NonfinancialAmendmentClient(_SuccessfulLaterAmendmentClient):
    accession = "0000320193-26-000082"

    def __init__(self):
        super().__init__()
        prefix = _canonical_artifact_url(CIK, self.accession, "")
        old_colon = b"us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
        old_underscore = b"us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"
        for url, content in tuple(self.responses.items()):
            if not url.startswith(prefix) or not isinstance(content, bytes):
                continue
            self.responses[url] = content.replace(
                old_colon, b"aapl:IssuerNarrativeOnly"
            ).replace(old_underscore, b"aapl_IssuerNarrativeOnly")
        index_url = _canonical_artifact_url(CIK, self.accession, "index.json")
        index = json.loads(self.responses[index_url])
        for item in index["directory"]["item"]:
            artifact_url = _canonical_artifact_url(CIK, self.accession, item["name"])
            if artifact_url in self.responses:
                item["size"] = len(self.responses[artifact_url])
        self.responses[index_url] = json.dumps(index).encode()


class _NamespaceCollisionAmendmentClient(_SuccessfulLaterAmendmentClient):
    accession = "0000320193-26-000083"

    def __init__(self):
        super().__init__()
        prefix = _canonical_artifact_url(CIK, self.accession, "")
        local = b"RevenueFromContractWithCustomerExcludingAssessedTax"
        for url, content in tuple(self.responses.items()):
            if not url.startswith(prefix) or not isinstance(content, bytes):
                continue
            self.responses[url] = content.replace(
                b"us-gaap:" + local, b"aapl:" + local
            ).replace(b"us-gaap_" + local, b"aapl_" + local)
        index_url = _canonical_artifact_url(CIK, self.accession, "index.json")
        index = json.loads(self.responses[index_url])
        for item in index["directory"]["item"]:
            artifact_url = _canonical_artifact_url(CIK, self.accession, item["name"])
            if artifact_url in self.responses:
                item["size"] = len(self.responses[artifact_url])
        self.responses[index_url] = json.dumps(index).encode()


class _SuccessfulReparseOfFailedAmendmentClient(_SuccessfulLaterAmendmentClient):
    accession = _FailedAmendmentClient.accession

    def __init__(self):
        super().__init__()
        normal_primary_url = _canonical_artifact_url(
            CIK, self.accession, "aapl-20260627.htm"
        )
        failed_primary_url = _canonical_artifact_url(
            CIK, self.accession, _FailedAmendmentClient.primary
        )
        self.responses[failed_primary_url] = self.responses[normal_primary_url]
        index_url = _canonical_artifact_url(CIK, self.accession, "index.json")
        index = json.loads(self.responses[index_url])
        index["directory"]["item"][0]["name"] = _FailedAmendmentClient.primary
        index["directory"]["item"][0]["size"] = len(
            self.responses[failed_primary_url]
        )
        self.responses[index_url] = json.dumps(index).encode()


def _ingest_changed_amendment(db, tmp_path, original):
    report = ingest_latest_financial_filings(
        db,
        stock_id=original.stock_id,
        client=_ChangedSuccessfulAmendmentClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 29, 17, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    amendment = db.execute(
        text(
            """SELECT pr.id, a.available_at
               FROM sec_financial_parse_runs pr
               JOIN sec_financial_filings f ON f.id=pr.filing_id
               JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
               WHERE f.accession_no=:accession AND pr.status='succeeded'"""
        ),
        {"accession": _ChangedSuccessfulAmendmentClient.accession},
    ).mappings().one()
    rule = db.execute(
        text(
            """SELECT id FROM sec_metric_mapping_rules
               WHERE mapping_version_id='sec-us-gaap-v1' AND rule_id='sec.revenue'"""
        )
    ).scalar_one()
    raws = db.execute(
        text(
            """SELECT DISTINCT raw.id,raw.raw_value,raw.scale,raw.sign
               FROM sec_raw_xbrl_facts raw
               JOIN sec_statement_fact_authorities a ON a.raw_fact_id=raw.id
               WHERE raw.parse_run_id=:parse
                 AND raw.concept LIKE '%RevenueFromContract%'
                 AND (raw.transformation_format IS NOT NULL OR raw.raw_value NOT LIKE '%,%')"""
        ),
        {"parse": amendment.id},
    ).all()
    for raw_id, raw_value, scale, sign in raws:
        normalized = Decimal(raw_value.replace(",", "")) * (Decimal(10) ** (scale or 0))
        if sign == "-":
            normalized = -normalized
        db.execute(
            text(
                """INSERT INTO sec_raw_numeric_normalizations
                     (raw_fact_id,mapping_rule_id,mapping_version_id,
                      normalization_version,normalized_value,raw_semantic_sha256,
                      transformation_identity)
                   VALUES (:raw,:rule,'sec-us-gaap-v1','sec_numeric_v1',:value,:sha,
                           'fixture-exact-decimal')"""
            ),
            {
                "raw": raw_id,
                "rule": rule,
                "value": normalized,
                "sha": hashlib.sha256(f"{raw_id}:{raw_value}".encode()).hexdigest(),
            },
        )
    db.commit()
    return amendment.available_at


def _request_with_sources(original, cutoff, sources):
    return PublicationRequest(
        original.stock_id,
        original.issuer_identity_id,
        original.mapping_version_id,
        cutoff,
        original.amendment_policy,
        sources,
    )


def _ingest_client(db, tmp_path, original, client, *, now):
    report = ingest_latest_financial_filings(
        db,
        stock_id=original.stock_id,
        client=client,
        storage_root=tmp_path,
        max_filings=1,
        now=now,
        parser_version="xbrl-lineage-v2",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    return db.execute(
        text(
            """SELECT a.available_at
               FROM sec_financial_lineage_availabilities a
               WHERE a.operation_id=:operation"""
        ),
        {"operation": report.operation_id},
    ).scalar_one()


def test_database_resolves_complete_ordered_sources_and_rejects_caller_variants(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDAUTH")
    early_sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=original.requested_cutoff,
    )
    assert early_sources == original.sources

    amendment_available_at = _ingest_changed_amendment(db, tmp_path, original)
    cutoff = amendment_available_at + timedelta(seconds=1)
    exact = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    assert [source.accession_no for source in exact] == [
        original.sources[0].accession_no,
        _ChangedSuccessfulAmendmentClient.accession,
    ]

    extra = exact + (original.sources[0],)
    for supplied in (exact[:1], exact[1:], tuple(reversed(exact)), extra):
        with pytest.raises(SecPublicationError, match="complete ordered source authority"):
            publish_sec_mapping_result(db, _request_with_sources(original, cutoff, supplied))
        db.rollback()
    assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one() == 0


def test_empty_database_first_publication_combines_original_and_amendment_slot_authority(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDFIRST")
    amendment_available_at = _ingest_changed_amendment(db, tmp_path, original)
    cutoff = amendment_available_at + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    request = _request_with_sources(original, cutoff, sources)

    first = publish_sec_mapping_result(db, request)
    db.commit()
    finalize_sec_publication(db, first.run_id)
    db.commit()
    replay = publish_sec_mapping_result(db, request)
    db.commit()

    assert replay.replayed is True
    assert replay.run_id == first.run_id
    source_accessions = tuple(
        db.execute(
            text(
                """SELECT accession_no FROM sec_metric_publication_run_sources
                   WHERE publication_run_id=:run ORDER BY source_ordinal"""
            ),
            {"run": first.run_id},
        ).scalars()
    )
    assert source_accessions == tuple(source.accession_no for source in sources)
    direct_parse_ids = set(
        db.execute(
            text(
                """SELECT src.parse_run_id
                   FROM sec_metric_publications p
                   JOIN sec_metric_publication_inputs i ON i.publication_id=p.id
                   JOIN sec_metric_publication_run_sources src ON src.id=i.run_source_id
                   WHERE p.publication_run_id=:run AND p.status='published'
                     AND p.derivation_kind='direct'"""
            ),
            {"run": first.run_id},
        ).scalars()
    )
    assert direct_parse_ids == {sources[-1].parse_run_id}
    current_count, duplicate_count = db.execute(
        text(
            """SELECT count(*), count(*)-count(DISTINCT (metric_key,period_type,period_end_date))
               FROM metric_facts
               WHERE stock_id=:stock AND source_type='sec' AND is_current"""
        ),
        {"stock": original.stock_id},
    ).one()
    assert current_count > 0
    assert duplicate_count == 0


def test_later_amendment_publication_demotes_only_matching_current_slots(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDDEMOTE")
    initial = publish_sec_mapping_result(db, original)
    db.commit()
    finalize_sec_publication(db, initial.run_id)
    db.commit()
    initial_fact_ids = set(initial.fact_ids)
    assert initial_fact_ids

    amendment_available_at = _ingest_changed_amendment(db, tmp_path, original)
    cutoff = amendment_available_at + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    amended = publish_sec_mapping_result(
        db, _request_with_sources(original, cutoff, sources)
    )
    db.commit()

    assert not set(amended.fact_ids) & initial_fact_ids
    assert db.execute(
        text(
            """SELECT count(*) FROM metric_facts
               WHERE id=ANY(:facts) AND is_current"""
        ),
        {"facts": list(initial_fact_ids)},
    ).scalar_one() == 0
    amended_direct_parses = set(
        db.execute(
            text(
                """SELECT source.parse_run_id
                   FROM sec_metric_publications publication
                   JOIN sec_metric_publication_inputs input
                     ON input.publication_id=publication.id
                   JOIN sec_metric_publication_run_sources source
                     ON source.id=input.run_source_id
                   WHERE publication.publication_run_id=:run
                     AND publication.derivation_kind='direct'"""
            ),
            {"run": amended.run_id},
        ).scalars()
    )
    assert amended_direct_parses == {sources[-1].parse_run_id}


def test_successful_nonfinancial_amendment_is_typed_and_preserves_original_slots(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDNONFIN")
    report = ingest_latest_financial_filings(
        db,
        stock_id=original.stock_id,
        client=_NonfinancialAmendmentClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 30, 17, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    amendment_available_at = db.execute(
        text(
            """SELECT a.available_at
               FROM sec_financial_parse_runs pr
               JOIN sec_financial_filings f ON f.id=pr.filing_id
               JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
               WHERE f.accession_no=:accession AND pr.status='succeeded'"""
        ),
        {"accession": _NonfinancialAmendmentClient.accession},
    ).scalar_one()
    cutoff = amendment_available_at + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    receipt = publish_sec_mapping_result(
        db, _request_with_sources(original, cutoff, sources)
    )
    db.commit()

    reason, detail = db.execute(
        text(
            """SELECT reason_code,detail FROM sec_metric_publication_audits
               WHERE publication_run_id=:run
                 AND reason_code='nonfinancial_amendment_no_slot_effect'"""
        ),
        {"run": receipt.run_id},
    ).one()
    assert reason == "nonfinancial_amendment_no_slot_effect"
    assert detail == "filing_authority_id=" + _NonfinancialAmendmentClient.accession
    direct_parse_ids = set(
        db.execute(
            text(
                """SELECT source.parse_run_id
                   FROM sec_metric_publications publication
                   JOIN sec_metric_publication_inputs input
                     ON input.publication_id=publication.id
                   JOIN sec_metric_publication_run_sources source
                     ON source.id=input.run_source_id
                   WHERE publication.publication_run_id=:run
                     AND publication.derivation_kind='direct'"""
            ),
            {"run": receipt.run_id},
        ).scalars()
    )
    assert direct_parse_ids == {sources[0].parse_run_id}


def test_custom_namespace_same_local_name_is_nonfinancial_in_database_authority(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDNS")
    available_at = _ingest_client(
        db,
        tmp_path,
        original,
        _NamespaceCollisionAmendmentClient(),
        now=datetime(2026, 8, 30, 18, tzinfo=timezone.utc),
    )
    cutoff = available_at + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    receipt = publish_sec_mapping_result(
        db, _request_with_sources(original, cutoff, sources)
    )
    db.commit()

    reasons = set(
        db.execute(
            text(
                """SELECT reason_code FROM sec_metric_publication_audits
                   WHERE publication_run_id=:run"""
            ),
            {"run": receipt.run_id},
        ).scalars()
    )
    assert "unresolved_custom_concept" in reasons
    assert "nonfinancial_amendment_no_slot_effect" in reasons
    direct_parse_ids = set(
        db.execute(
            text(
                """SELECT source.parse_run_id
                   FROM sec_metric_publications publication
                   JOIN sec_metric_publication_inputs input
                     ON input.publication_id=publication.id
                   JOIN sec_metric_publication_run_sources source
                     ON source.id=input.run_source_id
                   WHERE publication.publication_run_id=:run
                     AND publication.derivation_kind='direct'"""
            ),
            {"run": receipt.run_id},
        ).scalars()
    )
    assert direct_parse_ids == {sources[0].parse_run_id}


def test_later_separate_amendment_does_not_classify_an_earlier_failed_accession(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDFAILSEP")
    _ingest_client(
        db,
        tmp_path,
        original,
        _FailedAmendmentClient(),
        now=datetime(2026, 8, 28, 17, tzinfo=timezone.utc),
    )
    later_available = _ingest_client(
        db,
        tmp_path,
        original,
        _ChangedSuccessfulAmendmentClient(),
        now=datetime(2026, 8, 29, 17, tzinfo=timezone.utc),
    )
    cutoff = later_available + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    assert [source.accession_no for source in sources] == [
        original.sources[0].accession_no,
        _FailedAmendmentClient.accession,
        _ChangedSuccessfulAmendmentClient.accession,
    ]
    receipt = publish_sec_mapping_result(
        db, _request_with_sources(original, cutoff, sources)
    )
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()

    states = active_sec_run_unresolved_states(db, stock_id=original.stock_id)
    assert len(states) == 1
    assert states[0]["filing"]["accession"] == _FailedAmendmentClient.accession


def test_successful_reparse_of_same_failed_filing_replaces_run_level_unavailability(
    db, tmp_path
):
    original = _request(db, tmp_path, ticker="AMENDREPARSE")
    _ingest_client(
        db,
        tmp_path,
        original,
        _FailedAmendmentClient(),
        now=datetime(2026, 8, 28, 17, tzinfo=timezone.utc),
    )
    recovered_available = _ingest_client(
        db,
        tmp_path,
        original,
        _SuccessfulReparseOfFailedAmendmentClient(),
        now=datetime(2026, 8, 29, 17, tzinfo=timezone.utc),
    )
    cutoff = recovered_available + timedelta(seconds=1)
    sources = resolve_latest_known_v1_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        requested_cutoff=cutoff,
    )
    assert [source.accession_no for source in sources] == [
        original.sources[0].accession_no,
        _FailedAmendmentClient.accession,
    ]
    recovered_source = sources[-1]
    recovered_status = db.execute(
        text("SELECT status FROM sec_financial_parse_runs WHERE id=:parse"),
        {"parse": recovered_source.parse_run_id},
    ).scalar_one()
    assert recovered_status == "succeeded"
    receipt = publish_sec_mapping_result(
        db, _request_with_sources(original, cutoff, sources)
    )
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()
    assert not db.execute(
        text(
            """SELECT EXISTS(
                 SELECT 1 FROM sec_metric_publication_audits
                 WHERE publication_run_id=:run
                   AND reason_code='unresolved_amendment_parse_failure'
               )"""
        ),
        {"run": receipt.run_id},
    ).scalar_one()
    assert active_sec_run_unresolved_states(db, stock_id=original.stock_id) == []


def test_publication_waits_for_uncommitted_availability_then_rejects_stale_sources(
    isolated_engine, tmp_path
):
    Session = sessionmaker(bind=isolated_engine)
    with Session() as setup:
        original = _request(setup, tmp_path, ticker="AMENDRACE")
        report = ingest_latest_financial_filings(
            setup,
            stock_id=original.stock_id,
            client=_ChangedSuccessfulAmendmentClient(),
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 29, 17, tzinfo=timezone.utc),
            parser_version="xbrl-lineage-v2",
        )
        setup.commit()

    finalizer = Session()
    available_at = finalize_sec_financial_ingestion_operation(
        finalizer, operation_id=report.operation_id
    )
    stale_request = _request_with_sources(
        original,
        available_at + timedelta(seconds=1),
        original.sources,
    )
    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def publish_stale() -> None:
        session = Session()
        try:
            started.set()
            publish_sec_mapping_result(session, stale_request)
            session.commit()
        except BaseException as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()
            finished.set()

    thread = threading.Thread(target=publish_stale)
    try:
        thread.start()
        assert started.wait(timeout=5)
        assert not finished.wait(timeout=1), (
            "publication resolved authority while availability was uncommitted"
        )
        finalizer.commit()
        assert finished.wait(timeout=10)
        thread.join(timeout=10)
    finally:
        finalizer.rollback()
        finalizer.close()
    assert len(errors) == 1
    assert isinstance(errors[0], SecPublicationError)
    assert "complete ordered source authority" in str(errors[0])
    with Session() as verify:
        assert verify.execute(
            text("SELECT count(*) FROM sec_metric_publication_runs")
        ).scalar_one() == 0


def test_stock_authority_lock_does_not_block_another_stock(isolated_engine, tmp_path):
    Session = sessionmaker(bind=isolated_engine)
    with Session() as setup:
        first = Stock(ticker="LOCKFIRST", exchange="US", company_name="First")
        second = Stock(ticker="LOCKSECOND", exchange="US", company_name="Second")
        setup.add_all((first, second))
        setup.commit()
        first_stock_id = first.id
        second_stock_id = second.id

    blocker = Session()
    acquire_sec_financial_stock_lock(blocker, stock_id=first_stock_id)
    finished = threading.Event()
    errors: list[BaseException] = []

    def lock_second() -> None:
        session = Session()
        try:
            acquire_sec_financial_stock_lock(session, stock_id=second_stock_id)
            session.commit()
        except BaseException as exc:
            session.rollback()
            errors.append(exc)
        finally:
            session.close()
            finished.set()

    thread = threading.Thread(target=lock_second)
    try:
        thread.start()
        assert finished.wait(timeout=10), "a different stock shared the publication lock"
        thread.join(timeout=10)
    finally:
        blocker.rollback()
        blocker.close()
    assert not errors
