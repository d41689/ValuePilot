"""Real isolated-PostgreSQL tests for canonical SEC publication authority."""
from __future__ import annotations
import hashlib, os, subprocess, threading
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
import typer
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner
from app.cli import sec_financials as financial_cli
from app.core.config import settings
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.sec_financial_ingestion import finalize_sec_financial_ingestion_operation, ingest_latest_financial_filings, register_reviewed_sec_identity
from app.services import sec_financial_ingestion as financial_ingestion
from app.services.sec_metric_publication import PublicationRequest, SecPublicationError, VerifiedPublicationSource, finalize_sec_publication, publish_sec_mapping_result, resolve_latest_known_v1_sources
from app.services.sec_financial_locking import acquire_sec_financial_stock_lock
from app.acceptance.sec_gold_publication import (
    acquire_acceptance_completion_lease,
    append_acceptance_completion_claim,
    acceptance_operation_authority,
    begin_acceptance_case_attempt,
    initialize_acceptance_case_attempt,
    execute_acceptance_publication,
    link_acceptance_operation,
    load_completed_acceptance_publication,
    load_acceptance_evidence_delta,
    linked_acceptance_ingestion_reports,
    mark_acceptance_report_ready,
    record_acceptance_evidence_checkpoint,
    select_ordered_authoritative_sources,
)
from app.acceptance import sec_gold_publication as gold_publication
from app.acceptance.sec_gold_report import build_case_report, case_report_payload
from app.acceptance.sec_gold_audit import (
    _schema_v2_acquisition_audit,
    _control_plane_counts,
    audit_case_report_operation,
    audit_runtime_snapshot_rate_guard,
    build_runtime_snapshot,
    locked_case_contract,
    persist_rate_guard_snapshot,
    rate_guard_configuration_digest,
    retained_storage_authority,
)
from app.acceptance import sec_gold_audit as gold_audit
from app.services.sec_financial_ingestion import (
    FinancialFilingSelection,
    FinancialIngestionReport,
)
from test_sec_financial_lineage import (
    CIK,
    FakeEdgarClient,
    GeneratedInheritedFrenchRevenueLabelClient,
    GeneratedMixedConceptAuthorityClient,
    GeneratedStatementAuthorityClient,
    StatementAuthorityClient,
    SUBMISSIONS_URL,
    ToggleInitialMainOutageClient,
    _canonical_artifact_url,
)
from app.services.canonical_financials import (
    CanonicalUnavailableError,
    active_sec_run_unresolved_states,
    guard_sec_run_availability,
    sec_fact_filing_cycles,
)
from types import SimpleNamespace
from test_support.database_isolation import build_isolated_database_url, create_test_schema, drop_test_schema, new_test_schema_name

BACKEND=Path(__file__).resolve().parents[2]
BASE=make_url(settings.SQLALCHEMY_DATABASE_URI).set(query={k:v for k,v in make_url(settings.SQLALCHEMY_DATABASE_URI).query.items() if k!="options"}).render_as_string(hide_password=False)


def _release_test_completion_leases(db):
    for lease in reversed(db.info.pop("acceptance_completion_leases", [])):
        lease.release()


def _claim_acceptance_attempt(db, *, run_id, case_id, acceptance_pass, attempt_id):
    _release_test_completion_leases(db)
    lease = acquire_acceptance_completion_lease(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=acceptance_pass,
    )
    assert lease is not None
    if lease.attempt_id is None:
        append_acceptance_completion_claim(lease, attempt_id=attempt_id)
    else:
        assert lease.attempt_id == attempt_id
    db.info.setdefault("acceptance_completion_leases", []).append(lease)

@pytest.fixture
def isolated_engine():
    schema=new_test_schema_name(); url=build_isolated_database_url(BASE,schema); create_test_schema(BASE,schema)
    result=subprocess.run(["alembic","upgrade","head"],cwd=BACKEND,env={**os.environ,"DATABASE_URL":url},capture_output=True,text=True)
    assert result.returncode==0,result.stdout+result.stderr
    engine=create_engine(url,pool_pre_ping=True)
    try: yield engine
    finally: engine.dispose(); drop_test_schema(BASE,schema)

@pytest.fixture
def db(isolated_engine):
    session=sessionmaker(bind=isolated_engine)()
    try: yield session
    finally:
        _release_test_completion_leases(session)
        session.close()

def _request(
    db,
    tmp_path,
    *,
    ticker="PUB",
    normalize=True,
    acceptance_scope: tuple[str, str, int] | None = None,
    client=None,
    concept_like="%RevenueFromContract%",
    rule_id="sec.revenue",
):
    known=datetime(2026,8,27,12,tzinfo=timezone.utc)
    acceptance_attempt = None
    if acceptance_scope is not None:
        run_id, case_id, acceptance_pass = acceptance_scope
        instance = "11111111-1111-4111-8111-111111111111"
        persist_rate_guard_snapshot(
            db,
            run_id=run_id,
            phase="before",
            configured_route="https://rate-guard.example.test",
            expected_instance_id=instance,
            observed_instance_id=instance,
            fetch_mode="rate_guard",
            fallback_enabled=False,
            fallback_url=None,
            metrics={"rate_per_sec": 1.0},
            manifest_digest="e" * 64,
            database_name="valuepilot_acceptance_gold_report",
            storage_root=tmp_path,
        )
        acceptance_attempt = begin_acceptance_case_attempt(
            db,
            run_id=run_id,
            case_id=case_id,
            acceptance_pass=acceptance_pass,
        )
        _claim_acceptance_attempt(
            db,
            run_id=run_id,
            case_id=case_id,
            acceptance_pass=acceptance_pass,
            attempt_id=acceptance_attempt["id"],
        )
        record_acceptance_evidence_checkpoint(
            db,
            run_id=run_id,
            case_id=case_id,
            acceptance_pass=acceptance_pass,
            phase="before",
            attempt_id=acceptance_attempt["id"],
        )
    stock=Stock(ticker=ticker,exchange="US",company_name="Apple Inc."); db.add(stock); db.flush()
    identity=register_reviewed_sec_identity(db,stock_id=stock.id,cik=CIK,effective_from=date(1980,12,12),known_at=known,review_reason="publication fixture reviewed identity")
    db.commit()
    report=ingest_latest_financial_filings(db,stock_id=stock.id,client=client or StatementAuthorityClient(),storage_root=tmp_path,max_filings=1,now=known+timedelta(minutes=5),parser_version=financial_ingestion.PARSER_V2)
    if acceptance_attempt is not None:
        link_acceptance_operation(
            db,
            attempt_id=acceptance_attempt["id"],
            operation_id=report.operation_id,
            operation_ordinal=1,
            operation_role="main",
        )
    db.commit()
    finalize_sec_financial_ingestion_operation(db,operation_id=report.operation_id); db.commit()
    parse=db.execute(text("""SELECT pr.id,pr.filing_id,pr.parser_version,pr.input_manifest_hash,f.accession_no,a.available_at
      FROM sec_financial_parse_runs pr JOIN sec_financial_filings f ON f.id=pr.filing_id
      JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
      WHERE pr.status='succeeded' ORDER BY pr.id DESC LIMIT 1""")).mappings().one()
    rule=db.execute(text("SELECT id FROM sec_metric_mapping_rules WHERE mapping_version_id='sec-us-gaap-v1' AND rule_id=:rule"), {"rule": rule_id}).scalar_one()
    raws=db.execute(text("""SELECT DISTINCT raw.id,raw.raw_value,raw.scale,raw.sign FROM sec_raw_xbrl_facts raw JOIN sec_statement_fact_authorities a ON a.raw_fact_id=raw.id
      WHERE raw.parse_run_id=:parse AND raw.concept LIKE :concept
        AND (raw.transformation_format IS NOT NULL OR raw.raw_value NOT LIKE '%,%') ORDER BY raw.id"""),{"parse":parse.id,"concept":concept_like}).all()
    assert raws
    for raw_id,raw_value,scale,sign in (raws if normalize else ()):
        normalized=Decimal(raw_value.replace(",",""))*(Decimal(10)**(scale or 0))
        if sign=='-': normalized=-normalized
        db.execute(text("""INSERT INTO sec_raw_numeric_normalizations
          (raw_fact_id,mapping_rule_id,mapping_version_id,normalization_version,normalized_value,raw_semantic_sha256,transformation_identity)
          VALUES (:raw,:rule,'sec-us-gaap-v1','sec_numeric_v1',:value,:sha,'fixture-exact-decimal')"""),
          {"raw":raw_id,"rule":rule,"value":normalized,"sha":hashlib.sha256(f"{raw_id}:{raw_value}".encode()).hexdigest()})
    db.commit()
    source=VerifiedPublicationSource(parse.id,parse.filing_id,parse.accession_no,parse.parser_version,parse.input_manifest_hash,parse.available_at)
    return PublicationRequest(stock.id,identity.id,"sec-us-gaap-v1",parse.available_at+timedelta(seconds=1),"latest-known-v1",(source,))


def test_publication_never_uses_partially_resolved_rejected_concept(db, tmp_path):
    request = _request(
        db,
        tmp_path,
        ticker="MIXEDPUB",
        client=GeneratedMixedConceptAuthorityClient(),
        concept_like="%GrossProfit",
        rule_id="sec.gross_profit",
    )
    receipt = publish_sec_mapping_result(db, request)
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()
    facts = db.execute(
        text(
            "SELECT metric_key FROM metric_facts WHERE stock_id=:stock "
            "AND source_type='sec' AND is_current=true ORDER BY metric_key"
        ),
        {"stock": request.stock_id},
    ).scalars().all()
    assert "is.gross_profit" in facts
    assert "is.revenue" not in facts
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_statement_fact_authorities authority "
            "JOIN sec_raw_xbrl_facts raw ON raw.id=authority.raw_fact_id "
            "WHERE raw.concept LIKE '%Revenue%'"
        )
    ).scalar_one() == 0
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_metric_publications "
            "WHERE publication_run_id=:run AND metric_key='is.revenue' "
            "AND status='published'"
        ),
        {"run": receipt.run_id},
    ).scalar_one() == 0


def test_publication_accepts_real_sec_shared_label_resource_roles(db, tmp_path):
    request = _request(
        db,
        tmp_path,
        ticker="SHAREDLABEL",
        client=GeneratedStatementAuthorityClient(),
    )

    receipt = publish_sec_mapping_result(db, request)
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()

    assert db.execute(text(
        "SELECT count(*) FROM metric_facts WHERE stock_id=:stock "
        "AND source_type='sec' AND metric_key='is.revenue'"
    ), {"stock": request.stock_id}).scalar_one() > 0
    assert db.execute(text(
        "SELECT count(*) FROM sec_metric_publications "
        "WHERE publication_run_id=:run AND metric_key='is.revenue' "
        "AND status='published'"
    ), {"run": receipt.run_id}).scalar_one() > 0


def test_publication_excludes_ancestor_french_label_authority(db, tmp_path):
    request = _request(
        db,
        tmp_path,
        ticker="FRENLABEL",
        client=GeneratedInheritedFrenchRevenueLabelClient(),
        concept_like="%GrossProfit",
        rule_id="sec.gross_profit",
    )
    receipt = publish_sec_mapping_result(db, request)
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()

    metrics = set(db.execute(text(
        "SELECT metric_key FROM metric_facts WHERE stock_id=:stock "
        "AND source_type='sec'"
    ), {"stock": request.stock_id}).scalars())
    assert "is.gross_profit" in metrics
    assert "is.revenue" not in metrics


class _FailedAmendmentClient(StatementAuthorityClient):
    accession = "0000320193-26-000080"
    primary = "aapl-20260627a.htm"

    def __init__(self):
        super().__init__()
        submissions = json.loads(self.responses[SUBMISSIONS_URL])
        recent = submissions["filings"]["recent"]
        values = {
            "accessionNumber": self.accession,
            "filingDate": "2026-08-28",
            "reportDate": "2026-06-27",
            "acceptanceDateTime": "20260828160528",
            "form": "10-Q/A",
            "primaryDocument": self.primary,
            "primaryDocDescription": "10-Q/A",
        }
        for key, value in values.items():
            recent[key].insert(0, value)
        self.responses[SUBMISSIONS_URL] = json.dumps(submissions).encode()
        index_url = _canonical_artifact_url(CIK, self.accession, "index.json")
        primary_url = _canonical_artifact_url(CIK, self.accession, self.primary)
        no_facts = b"<html><body>amendment content unavailable for classification</body></html>"
        self.responses[index_url] = json.dumps(
            {
                "directory": {
                    "item": [
                        {
                            "name": self.primary,
                            "type": "10-Q/A",
                            "size": len(no_facts),
                            "description": "10-Q/A",
                        }
                    ]
                }
            }
        ).encode()
        self.responses[primary_url] = no_facts


class _SuccessfulLaterAmendmentClient(StatementAuthorityClient):
    accession = "0000320193-26-000081"

    def __init__(self):
        super().__init__()
        submissions = json.loads(self.responses[SUBMISSIONS_URL])
        recent = submissions["filings"]["recent"]
        values = {
            "accessionNumber": self.accession,
            "filingDate": "2026-08-29",
            "reportDate": "2026-06-27",
            "acceptanceDateTime": "20260829160528",
            "form": "10-Q/A",
            "primaryDocument": "aapl-20260627.htm",
            "primaryDocDescription": "10-Q/A",
        }
        for key, value in values.items():
            recent[key].insert(0, value)
        self.responses[SUBMISSIONS_URL] = json.dumps(submissions).encode()
        original_prefix = "https://www.sec.gov/Archives/edgar/data/320193/000032019326000079/"
        later_prefix = _canonical_artifact_url(CIK, self.accession, "")
        for url, content in list(self.responses.items()):
            if url.startswith(original_prefix):
                self.responses[later_prefix + url.removeprefix(original_prefix)] = content


def test_failed_amendment_state_is_bounded_to_its_filing_cycle(db, tmp_path):
    original = _request(db, tmp_path, ticker="AMENDCYCLE")
    initial = publish_sec_mapping_result(db, original)
    db.commit()
    finalize_sec_publication(db, initial.run_id)
    db.commit()

    report = ingest_latest_financial_filings(
        db,
        stock_id=original.stock_id,
        client=_FailedAmendmentClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 17, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    failed = db.execute(text("""
      SELECT pr.id,pr.filing_id,pr.parser_version,pr.input_manifest_hash,
             f.accession_no,a.available_at
      FROM sec_financial_parse_runs pr
      JOIN sec_financial_filings f ON f.id=pr.filing_id
      JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
      WHERE f.accession_no=:accession AND pr.status='failed'
      ORDER BY pr.id DESC LIMIT 1
    """), {"accession": _FailedAmendmentClient.accession}).mappings().one()
    failed_source = VerifiedPublicationSource(
        failed.id,
        failed.filing_id,
        failed.accession_no,
        failed.parser_version,
        failed.input_manifest_hash,
        failed.available_at,
    )
    request = PublicationRequest(
        original.stock_id,
        original.issuer_identity_id,
        original.mapping_version_id,
        failed.available_at + timedelta(seconds=1),
        original.amendment_policy,
        original.sources + (failed_source,),
    )
    receipt = publish_sec_mapping_result(db, request)
    db.commit()
    finalize_sec_publication(db, receipt.run_id)
    db.commit()

    states = active_sec_run_unresolved_states(db, stock_id=original.stock_id)
    assert len(states) == 1
    assert states[0]["period_end_date"] == date(2026, 6, 27)
    assert states[0]["filing"]["form"] == "10-Q/A"
    same_cycle_sec = db.query(MetricFact).filter_by(
        stock_id=original.stock_id,
        source_type="sec",
        is_current=True,
    ).first()
    assert sec_fact_filing_cycles(db, facts=[same_cycle_sec]) == {
        same_cycle_sec.source_ref_id: {("10-Q", date(2026, 6, 27))}
    }
    unproven_sec = SimpleNamespace(
        source_type="sec",
        source_ref_id=None,
        period_end_date=date(2022, 12, 31),
    )
    parsed = SimpleNamespace(source_type="parsed", period_end_date=date(2026, 6, 27))
    manual = SimpleNamespace(source_type="manual", period_end_date=date(2026, 6, 27))
    assert guard_sec_run_availability(db, stock_id=original.stock_id, facts=[parsed, manual]) == [parsed, manual]
    with pytest.raises(CanonicalUnavailableError):
        guard_sec_run_availability(db, stock_id=original.stock_id, facts=[same_cycle_sec])
    with pytest.raises(CanonicalUnavailableError):
        guard_sec_run_availability(db, stock_id=original.stock_id, facts=[unproven_sec])

    restored_report = ingest_latest_financial_filings(
        db,
        stock_id=original.stock_id,
        client=_SuccessfulLaterAmendmentClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 29, 17, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=restored_report.operation_id)
    db.commit()
    restored = db.execute(text("""
      SELECT pr.id,pr.filing_id,pr.parser_version,pr.input_manifest_hash,
             f.accession_no,a.available_at
      FROM sec_financial_parse_runs pr
      JOIN sec_financial_filings f ON f.id=pr.filing_id
      JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
      WHERE f.accession_no=:accession AND pr.status='succeeded'
      ORDER BY pr.id DESC LIMIT 1
    """), {"accession": _SuccessfulLaterAmendmentClient.accession}).mappings().one()
    rule = db.execute(text(
        "SELECT id FROM sec_metric_mapping_rules "
        "WHERE mapping_version_id='sec-us-gaap-v1' AND rule_id='sec.revenue'"
    )).scalar_one()
    raws = db.execute(text("""
      SELECT DISTINCT raw.id,raw.raw_value,raw.scale,raw.sign
      FROM sec_raw_xbrl_facts raw
      JOIN sec_statement_fact_authorities a ON a.raw_fact_id=raw.id
      WHERE raw.parse_run_id=:parse AND raw.concept LIKE '%RevenueFromContract%'
        AND (raw.transformation_format IS NOT NULL OR raw.raw_value NOT LIKE '%,%')
    """), {"parse": restored.id}).all()
    for raw_id, raw_value, scale, sign in raws:
        normalized = Decimal(raw_value.replace(",", "")) * (Decimal(10) ** (scale or 0))
        if sign == "-":
            normalized = -normalized
        db.execute(text("""
          INSERT INTO sec_raw_numeric_normalizations
            (raw_fact_id,mapping_rule_id,mapping_version_id,normalization_version,
             normalized_value,raw_semantic_sha256,transformation_identity)
          VALUES (:raw,:rule,'sec-us-gaap-v1','sec_numeric_v1',:value,:sha,
                  'fixture-exact-decimal')
        """), {
            "raw": raw_id,
            "rule": rule,
            "value": normalized,
            "sha": hashlib.sha256(f"{raw_id}:{raw_value}".encode()).hexdigest(),
        })
    db.commit()
    restored_source = VerifiedPublicationSource(
        restored.id,
        restored.filing_id,
        restored.accession_no,
        restored.parser_version,
        restored.input_manifest_hash,
        restored.available_at,
    )
    restored_cutoff = restored.available_at + timedelta(seconds=1)
    restored_request = PublicationRequest(
        original.stock_id,
        original.issuer_identity_id,
        original.mapping_version_id,
        restored_cutoff,
        original.amendment_policy,
        resolve_latest_known_v1_sources(
            db,
            stock_id=original.stock_id,
            issuer_identity_id=original.issuer_identity_id,
            requested_cutoff=restored_cutoff,
        ),
    )
    assert select_ordered_authoritative_sources(
        db,
        stock_id=original.stock_id,
        issuer_identity_id=original.issuer_identity_id,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        requested_cutoff=restored_cutoff,
    ) == restored_request.sources
    restored_receipt = publish_sec_mapping_result(db, restored_request)
    db.commit()
    finalize_sec_publication(db, restored_receipt.run_id)
    db.commit()
    # A separate later amendment can prove only its own mapped slots.  It does
    # not classify the unknown scope of the earlier failed accession.
    assert len(active_sec_run_unresolved_states(db, stock_id=original.stock_id)) == 1
    with pytest.raises(CanonicalUnavailableError):
        guard_sec_run_availability(
            db, stock_id=original.stock_id, facts=[same_cycle_sec]
        )

def test_database_rebuild_publish_replay_audits_and_availability(db,tmp_path):
    request=_request(db,tmp_path); first=publish_sec_mapping_result(db,request); db.commit()
    assert not first.replayed and not first.available and first.fact_ids
    replay=publish_sec_mapping_result(db,request); db.commit(); assert replay.replayed and replay.fact_ids==first.fact_ids
    counts=db.execute(text("""SELECT r.published_count,r.unresolved_count,r.rejected_count,
      (SELECT count(*) FROM sec_metric_publication_audits a WHERE a.publication_run_id=r.id)
      FROM sec_metric_publication_runs r WHERE r.id=:run"""),{"run":first.run_id}).one()
    assert counts.rejected_count==counts[3]
    provenance=db.execute(text("""SELECT p.source_role,p.locator_json,p.audit_json,f.value_json,
      a.id,a.statement_report_reference_id,a.statement_artifact_id,a.statement_sha256,
      a.occurrence_fact_id,a.report_ordinal,a.occurrence_ordinal,o.row_ordinal,o.column_ordinal
      FROM sec_metric_publications p JOIN metric_facts f ON f.id=p.metric_fact_id
      JOIN sec_metric_publication_inputs i ON i.publication_id=p.id
      JOIN sec_statement_fact_authorities a ON a.raw_fact_id=i.raw_fact_id
      JOIN sec_statement_occurrence_evidence o ON o.id=a.statement_occurrence_id
      WHERE p.publication_run_id=:run AND p.derivation_kind='direct' ORDER BY p.id LIMIT 1"""),{"run":first.run_id}).mappings().one()
    locator=provenance.locator_json
    assert provenance.source_role=="primary_as_filed_actual"
    assert locator["statement_authority_id"]==provenance.id
    assert locator["statement_report_reference_id"]==provenance.statement_report_reference_id
    assert locator["statement_artifact_id"]==provenance.statement_artifact_id
    assert locator["statement_sha256"]==provenance.statement_sha256
    assert locator["occurrence_fact_id"]==provenance.occurrence_fact_id
    assert (locator["report_ordinal"],locator["occurrence_ordinal"],locator["row_ordinal"],locator["column_ordinal"])==(provenance.report_ordinal,provenance.occurrence_ordinal,provenance.row_ordinal,provenance.column_ordinal)
    assert provenance.value_json["locator"]==locator and provenance.audit_json["ordered_input_occurrences"]==[locator]
    assert finalize_sec_publication(db,first.run_id).available; db.commit()


def test_gold_acceptance_executes_real_publication_and_exact_zero_growth_replay(
    db, tmp_path
):
    request = _request(
        db,
        tmp_path,
        ticker="GOLDPUB",
        acceptance_scope=("gold-publication-test", "gold-publication-primary", 1),
    )
    selection_cutoff = datetime(2026, 8, 30, tzinfo=timezone.utc)
    first_attempt_id = int(db.execute(text(
        "SELECT id FROM sec_acceptance_case_attempts WHERE run_id='gold-publication-test' "
        "AND case_id='gold-publication-primary' AND acceptance_pass=1"
    )).scalar_one())

    first = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=selection_cutoff,
        attempt_id=first_attempt_id,
        acceptance_pass=1,
    )
    before = db.execute(text("""
      SELECT
        (SELECT count(*) FROM sec_metric_publication_runs),
        (SELECT count(*) FROM sec_metric_publication_run_sources),
        (SELECT count(*) FROM sec_metric_publications),
        (SELECT count(*) FROM sec_metric_publication_inputs),
        (SELECT count(*) FROM sec_metric_publication_unresolved_inputs),
        (SELECT count(*) FROM sec_metric_publication_audits),
        (SELECT count(*) FROM sec_metric_publication_availabilities),
        (SELECT count(*) FROM metric_facts WHERE source_type='sec'),
        (SELECT count(*) FROM sec_raw_numeric_normalizations)
    """)).one()

    second_attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-publication-test",
        case_id="gold-publication-primary",
        acceptance_pass=2,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-publication-test",
        case_id="gold-publication-primary",
        acceptance_pass=2,
        attempt_id=second_attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-publication-test",
        case_id="gold-publication-primary",
        acceptance_pass=2,
        phase="before",
        attempt_id=second_attempt["id"],
    )
    pass_two_ingestion = ingest_latest_financial_filings(
        db,
        stock_id=request.stock_id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=second_attempt["id"],
        operation_id=pass_two_ingestion.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=pass_two_ingestion.operation_id
    )
    db.commit()
    second = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=selection_cutoff,
        replay_cutoff=first.requested_cutoff,
        expected_run_id=first.receipt.run_id,
        attempt_id=second_attempt["id"],
        acceptance_pass=2,
    )
    after = db.execute(text("""
      SELECT
        (SELECT count(*) FROM sec_metric_publication_runs),
        (SELECT count(*) FROM sec_metric_publication_run_sources),
        (SELECT count(*) FROM sec_metric_publications),
        (SELECT count(*) FROM sec_metric_publication_inputs),
        (SELECT count(*) FROM sec_metric_publication_unresolved_inputs),
        (SELECT count(*) FROM sec_metric_publication_audits),
        (SELECT count(*) FROM sec_metric_publication_availabilities),
        (SELECT count(*) FROM metric_facts WHERE source_type='sec'),
        (SELECT count(*) FROM sec_raw_numeric_normalizations)
    """)).one()

    assert first.receipt.available is True
    assert first.receipt.replayed is False
    assert second.receipt.available is True
    assert second.receipt.replayed is True
    assert second.receipt.run_id == first.receipt.run_id
    assert second.normalizations_created == 0
    assert after == before


def test_gold_acceptance_publication_binding_recovers_publish_finalize_crashes(
    db, tmp_path, monkeypatch: pytest.MonkeyPatch
):
    request = _request(
        db,
        tmp_path,
        ticker="GOLDCRASH",
        acceptance_scope=("gold-binding-crash", "gold-binding-primary", 1),
    )
    attempt_id = int(db.execute(text(
        "SELECT id FROM sec_acceptance_case_attempts WHERE run_id='gold-binding-crash' "
        "AND case_id='gold-binding-primary' AND acceptance_pass=1"
    )).scalar_one())
    selection_cutoff = datetime(2026, 8, 30, tzinfo=timezone.utc)
    original_finalize = gold_publication.finalize_sec_publication

    def crash_after_publish(*args, **kwargs):
        raise RuntimeError("simulated crash after publication commit")

    monkeypatch.setattr(gold_publication, "finalize_sec_publication", crash_after_publish)
    with pytest.raises(RuntimeError, match="after publication commit"):
        execute_acceptance_publication(
            db,
            stock_id=request.stock_id,
            issuer_identity_id=request.issuer_identity_id,
            filing_selection_as_of=selection_cutoff,
            attempt_id=attempt_id,
            acceptance_pass=1,
        )
    bound = db.execute(text(
        "SELECT publication_run_id,requested_cutoff FROM sec_acceptance_publication_bindings "
        "WHERE attempt_id=:attempt"
    ), {"attempt": attempt_id}).mappings().one()
    assert db.execute(text(
        "SELECT count(*) FROM sec_metric_publication_availabilities "
        "WHERE publication_run_id=:run"
    ), {"run": bound.publication_run_id}).scalar_one() == 0
    before_retry = db.execute(text(
        "SELECT (SELECT count(*) FROM sec_metric_publication_runs),"
        "(SELECT count(*) FROM sec_metric_publications),"
        "(SELECT count(*) FROM metric_facts WHERE source_type='sec')"
    )).one()

    monkeypatch.setattr(gold_publication, "finalize_sec_publication", original_finalize)
    recovered = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=selection_cutoff,
        attempt_id=attempt_id,
        acceptance_pass=1,
    )
    after_retry = db.execute(text(
        "SELECT (SELECT count(*) FROM sec_metric_publication_runs),"
        "(SELECT count(*) FROM sec_metric_publications),"
        "(SELECT count(*) FROM metric_facts WHERE source_type='sec')"
    )).one()
    assert recovered.receipt.run_id == str(bound.publication_run_id)
    assert recovered.requested_cutoff == bound.requested_cutoff
    assert recovered.receipt.available is True
    assert after_retry == before_retry

    # A retry after finalization but before the durable after checkpoint remains
    # owned by the same attempt and creates no publication evidence.
    repeated = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=selection_cutoff,
        attempt_id=attempt_id,
        acceptance_pass=1,
    )
    assert repeated.receipt.run_id == recovered.receipt.run_id
    assert db.execute(text(
        "SELECT (SELECT count(*) FROM sec_metric_publication_runs),"
        "(SELECT count(*) FROM sec_metric_publications),"
        "(SELECT count(*) FROM metric_facts WHERE source_type='sec')"
    )).one() == after_retry

    other = publish_sec_mapping_result(
        db,
        PublicationRequest(
            stock_id=request.stock_id,
            issuer_identity_id=request.issuer_identity_id,
            mapping_version_id="sec-us-gaap-v1",
            requested_cutoff=recovered.requested_cutoff + timedelta(microseconds=1),
            amendment_policy="latest-known-v1",
            sources=recovered.sources,
        ),
    )
    db.commit()
    finalize_sec_publication(db, other.run_id)
    db.commit()
    assert other.run_id != recovered.receipt.run_id

    operation_id = db.execute(text(
        "SELECT operation_id FROM sec_financial_parse_runs WHERE id=:parse"
    ), {"parse": recovered.sources[0].parse_run_id}).scalar_one()
    checkpoint = record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-binding-crash",
        case_id="gold-binding-primary",
        acceptance_pass=1,
        phase="after",
        attempt_id=attempt_id,
        operation_id=operation_id,
    )
    loaded = load_completed_acceptance_publication(
        db,
        attempt_id=attempt_id,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        acceptance_pass=1,
        completed_at=checkpoint["captured_at"],
    )
    assert loaded.receipt.run_id == recovered.receipt.run_id
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(
            "UPDATE sec_acceptance_publication_bindings SET amendment_policy='tampered' "
            "WHERE attempt_id=:attempt"
        ), {"attempt": attempt_id})
    db.rollback()


def test_gold_acceptance_report_is_rebuilt_and_verified_against_isolated_database(
    db, tmp_path
):
    request = _request(
        db,
        tmp_path,
        ticker="GOLDREPORT",
        acceptance_scope=("gold-report-test", "aapl-primary", 1),
    )
    publication = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        attempt_id=int(db.execute(text(
            "SELECT id FROM sec_acceptance_case_attempts WHERE run_id='gold-report-test' "
            "AND case_id='aapl-primary' AND acceptance_pass=1"
        )).scalar_one()),
        acceptance_pass=1,
    )
    source = publication.sources[0]
    operation_id = db.execute(
        text("SELECT operation_id FROM sec_financial_parse_runs WHERE id=:id"),
        {"id": source.parse_run_id},
    ).scalar_one()
    attempt_id = int(
        db.execute(
            text(
                "SELECT id FROM sec_acceptance_case_attempts "
                "WHERE run_id='gold-report-test' AND case_id='aapl-primary' "
                "AND acceptance_pass=1"
            )
        ).scalar_one()
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        acceptance_pass=1,
        phase="after",
        attempt_id=attempt_id,
        operation_id=operation_id,
    )
    operation = db.execute(
        text("SELECT attempted_at FROM sec_financial_ingestion_operations WHERE id=:id"),
        {"id": operation_id},
    ).mappings().one()
    availability = db.execute(
        text("SELECT available_at FROM sec_financial_lineage_availabilities WHERE operation_id=:id"),
        {"id": operation_id},
    ).scalar_one()
    filing = db.execute(
        text("SELECT form_type,accepted_at,report_date FROM sec_financial_filings WHERE id=:id"),
        {"id": source.filing_id},
    ).mappings().one()
    counts = db.execute(text("""
      SELECT
        (SELECT count(*) FROM sec_financial_accession_attempts WHERE operation_id=:operation) AS discovered,
        (SELECT count(*) FROM sec_submission_snapshots WHERE operation_id=:operation) AS snapshots,
        (SELECT count(*) FROM sec_filing_artifacts WHERE filing_id=:filing) AS artifacts,
        (SELECT count(*) FROM sec_financial_parse_runs WHERE operation_id=:operation) AS parses,
        (SELECT count(*) FROM sec_raw_xbrl_facts raw JOIN sec_financial_parse_runs pr
          ON pr.id=raw.parse_run_id WHERE pr.operation_id=:operation) AS raws
    """), {"operation": operation_id, "filing": source.filing_id}).mappings().one()
    ingestion = FinancialIngestionReport(
        operation_id=operation_id,
        stock_id=request.stock_id,
        cik=CIK,
        filings_discovered=counts.discovered,
        filings_created=1,
        artifacts_created=counts.artifacts,
        parse_runs_created=counts.parses,
        raw_facts_created=counts.raws,
        failures=(),
        selected_filings=(
            FinancialFilingSelection(
                accession_no=source.accession_no,
                form_type=filing.form_type,
                accepted_at=filing.accepted_at,
                report_date=filing.report_date,
            ),
        ),
    )
    report = build_case_report(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        expected_completed_fiscal_years=(2026,),
        ingestion_report=ingestion,
        ingestion_reports=(ingestion,),
        evidence_available_at=availability,
        acceptance_pass=1,
        publication=publication,
        persistent_delta={"idempotent": False},
    )
    payload = case_report_payload(report)
    case = {
        "case_id": "aapl-primary",
        "cik": CIK,
        "primary_listing": {"ticker": "GOLDREPORT"},
    }
    audited = audit_case_report_operation(
        db,
        expected_run_id="gold-report-test",
        case=case,
        report=payload,
        acceptance_pass=1,
        expected_filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        expected_completed_fiscal_years=(2026,),
    )
    assert audited["publication"]["publication_run_id"] == publication.receipt.run_id

    recovery_counts = db.execute(
        text("SELECT sec_acceptance_runtime_counts()")
    ).scalar_one()
    recovered_path = tmp_path / "reports" / "pass-1" / "aapl-primary.json"
    recovered = financial_cli._recover_completed_gold_case_report(
        db,
        acceptance_run_id="gold-report-test",
        acceptance_pass=1,
        case=case,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        expected_years=(2026,),
        report_json=recovered_path,
        storage_root=tmp_path,
    )
    assert recovered is not None
    first_bytes = recovered_path.read_bytes()
    assert db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one() == recovery_counts
    repeated = financial_cli._recover_completed_gold_case_report(
        db,
        acceptance_run_id="gold-report-test",
        acceptance_pass=1,
        case=case,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        expected_years=(2026,),
        report_json=recovered_path,
        storage_root=tmp_path,
    )
    assert repeated is not None
    assert recovered_path.read_bytes() == first_bytes
    assert db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one() == recovery_counts
    with pytest.raises(DBAPIError, match="durable case after checkpoint"):
        begin_acceptance_case_attempt(
            db,
            run_id="gold-report-test",
            case_id="aapl-primary",
            acceptance_pass=1,
        )
    db.rollback()

    pass_two_attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        acceptance_pass=2,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        acceptance_pass=2,
        attempt_id=pass_two_attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        acceptance_pass=2,
        phase="before",
        attempt_id=pass_two_attempt["id"],
    )
    pass_two_ingestion = ingest_latest_financial_filings(
        db,
        stock_id=request.stock_id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 30, 1, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=pass_two_attempt["id"],
        operation_id=pass_two_ingestion.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=pass_two_ingestion.operation_id
    )
    db.commit()
    replayed_publication = execute_acceptance_publication(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        replay_cutoff=publication.requested_cutoff,
        expected_run_id=publication.receipt.run_id,
        attempt_id=pass_two_attempt["id"],
        acceptance_pass=2,
    )
    assert replayed_publication.receipt.replayed is True
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-report-test",
        case_id="aapl-primary",
        acceptance_pass=2,
        phase="after",
        attempt_id=pass_two_attempt["id"],
        operation_id=pass_two_ingestion.operation_id,
    )
    pass_two_counts = db.execute(
        text("SELECT sec_acceptance_runtime_counts()")
    ).scalar_one()
    pass_two_path = tmp_path / "reports" / "pass-2" / "aapl-primary.json"
    pass_two_recovered = financial_cli._recover_completed_gold_case_report(
        db,
        acceptance_run_id="gold-report-test",
        acceptance_pass=2,
        case=case,
        filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
        expected_years=(2026,),
        report_json=pass_two_path,
        storage_root=tmp_path,
    )
    assert pass_two_recovered is not None
    assert pass_two_recovered.publication_replayed is True
    assert pass_two_recovered.persistent_delta["idempotent"] is True
    assert db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one() == pass_two_counts

    malformed_bytes = b'{"malformed":true}\n'
    pass_two_path.write_bytes(malformed_bytes)
    with pytest.raises(ValueError):
        financial_cli._recover_completed_gold_case_report(
            db,
            acceptance_run_id="gold-report-test",
            acceptance_pass=2,
            case=case,
            filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_years=(2026,),
            report_json=pass_two_path,
            storage_root=tmp_path,
        )
    assert pass_two_path.read_bytes() == malformed_bytes
    assert db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one() == pass_two_counts

    for field, value, message in (
        ("expected_completed_fiscal_years", [], "expected fiscal years"),
        ("filing_selection_as_of", "2026-08-29T00:00:00+00:00", "selection cutoff"),
    ):
        tampered = json.loads(json.dumps(payload))
        tampered[field] = value
        with pytest.raises(ValueError, match=message):
            audit_case_report_operation(
                db,
                expected_run_id="gold-report-test",
                case=case,
                report=tampered,
                acceptance_pass=1,
                expected_filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
                expected_completed_fiscal_years=(2026,),
            )

    for field, value in (
        ("accession_no", "0000000000-00-000000"),
        ("form_type", "10-K"),
        ("accepted_at", "2026-08-29T00:00:00+00:00"),
        ("report_date", "2025-01-01"),
    ):
        tampered = json.loads(json.dumps(payload))
        tampered["selected_filings"][0][field] = value
        if field == "form_type":
            tampered["selected_forms"] = [value]
        with pytest.raises(ValueError, match="selected filing fields"):
            audit_case_report_operation(
                db,
                expected_run_id="gold-report-test",
                case=case,
                report=tampered,
                acceptance_pass=1,
                expected_filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
                expected_completed_fiscal_years=(2026,),
            )

    zero_denominator = json.loads(json.dumps(payload))
    zero_denominator["metric_outcomes"]["issuer_year_metric_denominator"] = 0
    zero_denominator["metric_outcomes"]["outcomes"] = []
    with pytest.raises(ValueError, match="metric denominator"):
        audit_case_report_operation(
            db,
            expected_run_id="gold-report-test",
            case=case,
            report=zero_denominator,
            acceptance_pass=1,
            expected_filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_completed_fiscal_years=(2026,),
        )

    malformed = json.loads(json.dumps(payload))
    malformed["publication_decision_ids"] = malformed["publication_decision_ids"][:-1]
    with pytest.raises(ValueError, match="publication lineage identity"):
        audit_case_report_operation(
            db,
            expected_run_id="gold-report-test",
            case=case,
            report=malformed,
            acceptance_pass=1,
            expected_filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_completed_fiscal_years=(2026,),
        )


def test_after_checkpoint_without_publication_is_typed_recovery_failure(db, tmp_path):
    request = _request(
        db,
        tmp_path,
        ticker="INCOMPLETE",
        acceptance_scope=("gold-incomplete", "incomplete-primary", 1),
    )
    authority = acceptance_operation_authority(
        db,
        run_id="gold-incomplete",
        case_id="incomplete-primary",
        acceptance_pass=1,
    )
    operation_id = authority["creation_operation_ids"][0]
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-incomplete",
        case_id="incomplete-primary",
        acceptance_pass=1,
        phase="after",
        attempt_id=int(authority["attempts"][0]["id"]),
        operation_id=operation_id,
    )
    case = {
        "case_id": "incomplete-primary",
        "cik": CIK,
        "primary_listing": {"ticker": "INCOMPLETE"},
    }

    with pytest.raises(ValueError, match="acceptance_recovery_authority_incomplete"):
        financial_cli._recover_completed_gold_case_report(
            db,
            acceptance_run_id="gold-incomplete",
            acceptance_pass=1,
            case=case,
            filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_years=(2026,),
            report_json=tmp_path / "reports" / "pass-1" / "incomplete-primary.json",
            storage_root=tmp_path,
        )
    assert request.stock_id > 0


def _write_content_addressed(root: Path, content: bytes) -> Path:
    digest = hashlib.sha256(content).hexdigest()
    target = root / "financial" / digest[:2] / digest
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return target


def test_retained_storage_descriptor_walk_is_deterministic_and_excludes_reports(
    tmp_path,
):
    first = _write_content_addressed(tmp_path, b"first retained object")
    second = _write_content_addressed(tmp_path, b"second retained object")
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "runtime.json").write_text("first", encoding="utf-8")

    authority = retained_storage_authority(tmp_path)
    (reports / "runtime.json").write_text("changed", encoding="utf-8")

    assert retained_storage_authority(tmp_path) == authority
    assert authority["file_count"] == 2
    assert authority["bytes"] == first.stat().st_size + second.stat().st_size


def _pause_first_descriptor_read(monkeypatch, mutate):
    started = threading.Event()
    completed = threading.Event()
    original_read = gold_audit.os.read
    paused = False

    def read(fd, size):
        nonlocal paused
        chunk = original_read(fd, size)
        if chunk and not paused:
            paused = True
            started.set()
            assert completed.wait(timeout=5)
        return chunk

    def worker():
        assert started.wait(timeout=5)
        mutate()
        completed.set()

    monkeypatch.setattr(gold_audit.os, "read", read)
    thread = threading.Thread(target=worker)
    thread.start()
    return thread


def test_retained_storage_rejects_concurrent_file_to_external_symlink_replacement(
    tmp_path, monkeypatch
):
    target = _write_content_addressed(tmp_path, b"a" * (2 * 1024 * 1024))
    external = tmp_path / "external-secret"
    external.write_bytes(b"must not be read")

    def replace():
        target.unlink()
        target.symlink_to(external)

    thread = _pause_first_descriptor_read(monkeypatch, replace)
    with pytest.raises(ValueError, match="storage identity race"):
        retained_storage_authority(tmp_path)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_retained_storage_rejects_concurrent_directory_component_swap(
    tmp_path, monkeypatch
):
    target = _write_content_addressed(tmp_path, b"b" * (2 * 1024 * 1024))
    bucket = target.parent
    displaced = bucket.with_name(f"{bucket.name}-displaced")

    def replace():
        bucket.rename(displaced)
        bucket.mkdir()

    thread = _pause_first_descriptor_read(monkeypatch, replace)
    with pytest.raises(ValueError, match="storage identity race"):
        retained_storage_authority(tmp_path)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_retained_storage_rejects_file_mutation_during_descriptor_read(
    tmp_path, monkeypatch
):
    target = _write_content_addressed(tmp_path, b"c" * (2 * 1024 * 1024))

    def mutate():
        with target.open("r+b") as handle:
            handle.write(b"changed")
            handle.flush()
            os.fsync(handle.fileno())

    thread = _pause_first_descriptor_read(monkeypatch, mutate)
    with pytest.raises(ValueError, match="storage identity race"):
        retained_storage_authority(tmp_path)
    thread.join(timeout=5)
    assert not thread.is_alive()


def test_gold_rate_guard_snapshot_is_append_only_database_authority(db, tmp_path):
    instance = "11111111-1111-4111-8111-111111111111"
    authority = persist_rate_guard_snapshot(
        db,
        run_id="gold-rate-guard",
        phase="before",
        configured_route="https://rate-guard.example.test/",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={
            "rate_per_sec": 1.0,
            "total_request_count": 3,
            "total_403_count": 0,
            "total_429_count": 0,
            "total_503_count": 0,
            "cache_hits": 1,
            "cache_misses": 2,
        },
        manifest_digest="a" * 64,
        database_name="valuepilot_acceptance_gold_rate_guard",
        storage_root=tmp_path,
    )
    payload = build_runtime_snapshot(
        db,
        run_id="gold-rate-guard",
        database_name="valuepilot_acceptance_gold_rate_guard",
        storage_root=tmp_path,
        rate_guard_authority=authority,
    )
    assert audit_runtime_snapshot_rate_guard(
        db, payload=payload, run_id="gold-rate-guard", phase="before"
    ) == authority

    tampered = json.loads(json.dumps(payload))
    tampered["rate_guard"]["metrics"]["total_request_count"] = 2
    for mutate in (
        lambda item: item["rate_guard"]["metrics"].__setitem__(
            "total_request_count", 2
        ),
        lambda item: item.__setitem__("metric_facts", 9),
        lambda item: item["lineage_counts"].__setitem__("filings", 9),
        lambda item: item["retained_storage"].__setitem__("file_count", 9),
    ):
        tampered = json.loads(json.dumps(payload))
        mutate(tampered)
        with pytest.raises(ValueError, match="durable runtime authority"):
            audit_runtime_snapshot_rate_guard(
                db, payload=tampered, run_id="gold-rate-guard", phase="before"
            )

    with pytest.raises(ValueError, match="counter regressed"):
        persist_rate_guard_snapshot(
            db,
            run_id="gold-rate-guard",
            phase="before",
            configured_route="https://rate-guard.example.test/",
            expected_instance_id=instance,
            observed_instance_id=instance,
            fetch_mode="rate_guard",
            fallback_enabled=False,
            fallback_url=None,
            metrics={
                "rate_per_sec": 1.0,
                "total_request_count": 2,
                "cache_hits": 1,
                "cache_misses": 1,
            },
            manifest_digest="a" * 64,
            database_name="valuepilot_acceptance_gold_rate_guard",
            storage_root=tmp_path,
        )

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text(
            "UPDATE sec_acceptance_rate_guard_snapshots SET total_request_count=4"
        ))
    db.rollback()

    with pytest.raises(DBAPIError):
        persist_rate_guard_snapshot(
            db,
            run_id="gold-rate-guard-wrong",
            phase="before",
            configured_route="https://rate-guard.example.test",
            expected_instance_id=instance,
            observed_instance_id="22222222-2222-4222-8222-222222222222",
            fetch_mode="rate_guard",
            fallback_enabled=False,
            fallback_url=None,
            metrics={"rate_per_sec": 1.0},
            manifest_digest="b" * 64,
            database_name="valuepilot_acceptance_gold_rate_guard_wrong",
            storage_root=tmp_path,
        )
    db.rollback()


@pytest.mark.parametrize(
    ("run_id", "configured_route", "fetch_mode", "fallback_enabled", "fallback_url"),
    (
        ("guard-bad-route", "rate-guard.invalid", "rate_guard", False, None),
        (
            "guard-bad-mode",
            "https://rate-guard.example.test",
            "live",
            False,
            None,
        ),
        (
            "guard-fallback",
            "https://rate-guard.example.test",
            "rate_guard",
            True,
            "http://fallback.invalid",
        ),
    ),
)
def test_gold_rate_guard_database_rejects_unsafe_routing_shape(
    db,
    tmp_path,
    run_id,
    configured_route,
    fetch_mode,
    fallback_enabled,
    fallback_url,
):
    instance = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(DBAPIError):
        persist_rate_guard_snapshot(
            db,
            run_id=run_id,
            phase="before",
            configured_route=configured_route,
            expected_instance_id=instance,
            observed_instance_id=instance,
            fetch_mode=fetch_mode,
            fallback_enabled=fallback_enabled,
            fallback_url=fallback_url,
            metrics={"rate_per_sec": 1.0},
            manifest_digest="c" * 64,
            database_name="valuepilot_acceptance_gold_rate_guard_shape",
            storage_root=tmp_path,
        )
    db.rollback()


def test_gold_evidence_checkpoints_are_database_computed_and_append_only(db, tmp_path):
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id="gold-checkpoint",
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="d" * 64,
        database_name="valuepilot_acceptance_gold_checkpoint",
        storage_root=tmp_path,
    )
    first_attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
        attempt_id=first_attempt["id"],
    )
    before = record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
        phase="before",
        attempt_id=first_attempt["id"],
    )
    stock = Stock(
        ticker="CHECKPOINT", exchange="US", company_name="Checkpoint One"
    )
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="acceptance checkpoint DB authority fixture",
    )
    db.commit()

    first_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=first_attempt["id"],
        operation_id=first_report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=first_report.operation_id
    )
    db.commit()

    resumed_attempt = first_attempt
    resumed_before = record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
        phase="before",
        attempt_id=resumed_attempt["id"],
    )
    assert resumed_before["attempt_id"] == first_attempt["id"]
    resumed_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 2, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=resumed_attempt["id"],
        operation_id=resumed_report.operation_id,
        operation_ordinal=2,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=resumed_report.operation_id
    )
    db.commit()
    second_resume_attempt = first_attempt
    second_resumed_before = record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
        phase="before",
        attempt_id=second_resume_attempt["id"],
    )
    assert second_resumed_before["attempt_id"] == first_attempt["id"]
    second_resumed_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 2, 30, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=second_resume_attempt["id"],
        operation_id=second_resumed_report.operation_id,
        operation_ordinal=3,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=second_resumed_report.operation_id
    )
    db.commit()
    after = record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
        phase="after",
        attempt_id=second_resume_attempt["id"],
        operation_id=second_resumed_report.operation_id,
    )
    assert after["evidence_counts"]["issuer_identities"] == (
        before["evidence_counts"]["issuer_identities"] + 1
    )
    delta = load_acceptance_evidence_delta(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
    )
    assert delta["issuer_identities"] == 1
    assert delta["idempotent"] is False
    assert {**delta, "idempotent": True} != load_acceptance_evidence_delta(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
    )

    authority = acceptance_operation_authority(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=1,
    )
    assert authority["creation_operation_ids"] == [
        first_report.operation_id,
        resumed_report.operation_id,
        second_resumed_report.operation_id,
    ]
    assert [item["operation_role"] for item in authority["links"]] == [
        "main",
        "main",
        "main",
    ]
    control = _control_plane_counts(
        db,
        {
            first_report.operation_id,
            resumed_report.operation_id,
            second_resumed_report.operation_id,
        },
    )
    assert control["ingestion_operations"] == 3
    assert control["operation_results"] == 3
    assert control["lineage_availabilities"] == 3

    replay_attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=2,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=2,
        attempt_id=replay_attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=2,
        phase="before",
        attempt_id=replay_attempt["id"],
    )
    replay_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 3, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=replay_attempt["id"],
        operation_id=replay_report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=replay_report.operation_id
    )
    db.commit()
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=2,
        phase="after",
        attempt_id=replay_attempt["id"],
        operation_id=replay_report.operation_id,
    )
    assert load_acceptance_evidence_delta(
        db,
        run_id="gold-checkpoint",
        case_id="checkpoint-primary",
        acceptance_pass=2,
    )["idempotent"] is True

    db.execute(text("ALTER TABLE sec_acceptance_case_attempts DISABLE TRIGGER USER"))
    try:
        forged_attempt = db.execute(
            text(
                """INSERT INTO sec_acceptance_case_attempts
                     (run_id,case_id,acceptance_pass,attempt_ordinal,
                      attempted_at,created_at,created_txid)
                   VALUES ('gold-checkpoint','checkpoint-primary',1,99,
                           clock_timestamp(),clock_timestamp(),txid_current())
                   RETURNING id"""
            )
        ).scalar_one()
        db.commit()
    finally:
        db.execute(
            text("ALTER TABLE sec_acceptance_case_attempts ENABLE TRIGGER USER")
        )
        db.commit()
    db.execute(
        text("ALTER TABLE sec_acceptance_evidence_checkpoints DISABLE TRIGGER USER")
    )
    try:
        db.execute(
            text(
                """UPDATE sec_acceptance_evidence_checkpoints
                   SET attempt_id=:attempt
                   WHERE run_id='gold-checkpoint' AND case_id='checkpoint-primary'
                     AND acceptance_pass=1 AND phase='after'"""
            ),
            {"attempt": forged_attempt},
        )
        db.commit()
    finally:
        db.execute(
            text("ALTER TABLE sec_acceptance_evidence_checkpoints ENABLE TRIGGER USER")
        )
        db.commit()
    with pytest.raises(ValueError, match="checkpoint owner authority mismatch"):
        load_acceptance_evidence_delta(
            db,
            run_id="gold-checkpoint",
            case_id="checkpoint-primary",
            acceptance_pass=1,
        )

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(
            text(
                "UPDATE sec_acceptance_evidence_checkpoints "
                "SET evidence_counts='{}'::jsonb"
            )
        )
    db.rollback()


def test_cli_recovers_finalized_failed_parse_without_sec_refetch(
    db, tmp_path, monkeypatch
):
    run_id = "gold-failed-parse-recovery"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_failed_parse_recovery",
        storage_root=tmp_path,
    )
    first_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    _claim_acceptance_attempt(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        attempt_id=first_attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="before",
        attempt_id=first_attempt["id"],
    )
    operation_attempt = first_attempt
    resumed_before = record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="before",
        attempt_id=operation_attempt["id"],
    )
    assert resumed_before["attempt_id"] == first_attempt["id"]

    stock = Stock(ticker="AAPL", exchange="US", company_name="Apple Inc.")
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2015, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="failed parse acceptance recovery fixture",
    )
    db.commit()

    class SgmlPrimaryClient(StatementAuthorityClient):
        def __init__(self):
            super().__init__()
            old_primary_url = next(
                url for url in self.responses if url.endswith("aapl-20260627.htm")
            )
            primary_filename = "d927922d10q.htm"
            primary_url = old_primary_url.rsplit("/", 1)[0] + "/" + primary_filename
            wrapped = (
                b"<DOCUMENT><TYPE>10-Q\n<SEQUENCE>1\n"
                b"<FILENAME>d927922d10q.htm\n<TEXT>"
                + self.responses.pop(old_primary_url)
                + b"</TEXT></DOCUMENT>"
            )
            self.responses[primary_url] = wrapped
            instance = b'''<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
              xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
              xmlns:us-gaap="http://fasb.org/us-gaap/2025"
              xmlns:dei="http://xbrl.sec.gov/dei/2025"
              xmlns:aapl="http://www.apple.com/20250628"
              xmlns:iso4217="http://www.xbrl.org/2003/iso4217">
              <xbrli:context id="D2026Q3"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier><xbrli:segment><xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">aapl:ProductsMember</xbrldi:explicitMember></xbrli:segment></xbrli:entity><xbrli:period><xbrli:startDate>2026-03-29</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period></xbrli:context>
              <xbrli:context id="FY2026YTD"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:startDate>2025-09-28</xbrli:startDate><xbrli:endDate>2026-06-27</xbrli:endDate></xbrli:period></xbrli:context>
              <xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>
              <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax id="fact-revenue" contextRef="D2026Q3" unitRef="USD" decimals="-6">94,000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
              <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax id="fact-revenue-ytd" contextRef="FY2026YTD" unitRef="USD" decimals="-6">250,000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
              <dei:DocumentFiscalYearFocus id="fy-focus" contextRef="FY2026YTD">2026</dei:DocumentFiscalYearFocus>
              <dei:DocumentFiscalPeriodFocus id="fp-focus" contextRef="FY2026YTD">Q3</dei:DocumentFiscalPeriodFocus>
            </xbrli:xbrl>'''
            self.instance_filename = "aapl-20150627.xml"
            self.instance_url = primary_url.rsplit("/", 1)[0] + "/" + self.instance_filename
            self.instance_content = (
                b"<DOCUMENT><TYPE>XML\n<SEQUENCE>12\n"
                b"<FILENAME>aapl-20150627.xml\n<TEXT>"
                + instance
                + b"</TEXT></DOCUMENT>"
            )
            self.responses[self.instance_url] = self.instance_content
            submissions = json.loads(self.responses[SUBMISSIONS_URL])
            submissions["filings"]["recent"]["primaryDocument"][0] = primary_filename
            self.responses[SUBMISSIONS_URL] = json.dumps(submissions).encode()
            index_url = next(url for url in self.responses if url.endswith("/index.json"))
            index = json.loads(self.responses[index_url])
            for item in index["directory"]["item"]:
                if item["name"] == "aapl-20260627.htm":
                    item["name"] = primary_filename
                    item["size"] = len(wrapped)
            index["directory"]["item"].append(
                {
                    "name": self.instance_filename,
                    "type": "text.gif",
                    "size": len(self.instance_content),
                    "description": "XBRL INSTANCE DOCUMENT",
                }
            )
            self.responses[index_url] = json.dumps(index).encode()

    original_retain_item = financial_ingestion._retain_item
    monkeypatch.setattr(
        financial_ingestion,
        "_retain_item",
        lambda item, primary_document, referenced_statement_names=None: (
            False
            if item.get("name") == "aapl-20150627.xml"
            else original_retain_item(
                item, primary_document, referenced_statement_names
            )
        ),
    )
    initial_client = SgmlPrimaryClient()
    failed_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=initial_client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2",
    )
    monkeypatch.setattr(
        financial_ingestion, "_retain_item", original_retain_item
    )
    link_acceptance_operation(
        db,
        attempt_id=operation_attempt["id"],
        operation_id=failed_report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=failed_report.operation_id
    )
    db.commit()
    assert db.execute(
        text(
            "SELECT result_kind FROM sec_financial_operation_results "
            "WHERE operation_id=:operation"
        ),
        {"operation": failed_report.operation_id},
    ).scalar_one() == "parse_run"
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_financial_parse_runs "
            "WHERE operation_id=:operation AND status='failed'"
        ),
        {"operation": failed_report.operation_id},
    ).scalar_one() == 1
    assert db.execute(
        text("SELECT count(*) FROM sec_metric_publication_runs")
    ).scalar_one() == 0
    assert db.execute(
        text("SELECT count(*) FROM sec_acceptance_publication_bindings")
    ).scalar_one() == 0

    old_selector_attempt = first_attempt
    db.rollback()
    _release_test_completion_leases(db)
    crashed_owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert crashed_owner is not None
    assert crashed_owner.attempt_id == old_selector_attempt["id"]
    canonical_instance_predicate = (
        financial_ingestion._is_standalone_instance_filename
    )
    canonical_inline_parser = financial_ingestion.parse_inline_xbrl
    monkeypatch.setattr(
        financial_ingestion,
        "_is_standalone_instance_filename",
        lambda filename: canonical_instance_predicate(filename)
        and Path(filename.lower()).stem == Path("d927922d10q.htm").stem,
    )
    monkeypatch.setattr(
        financial_ingestion,
        "parse_inline_xbrl",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ValueError("xml_parse_failed")
        ),
    )
    old_replay = financial_ingestion.build_retained_financial_replay_client(
        db,
        stock_id=stock.id,
        operation_ids=(failed_report.operation_id,),
        storage_root=tmp_path,
        upstream_factory=lambda: pytest.fail(
            "old selector recovery unexpectedly constructed an upstream client"
        ),
    )
    with old_replay:
        old_v21_report = ingest_latest_financial_filings(
            db,
            stock_id=stock.id,
            client=old_replay,
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 28, 1, 15, tzinfo=timezone.utc),
            parser_version="xbrl-lineage-v2.1",
        )
    monkeypatch.setattr(
        financial_ingestion,
        "_is_standalone_instance_filename",
        canonical_instance_predicate,
    )
    monkeypatch.setattr(
        financial_ingestion, "parse_inline_xbrl", canonical_inline_parser
    )
    link_acceptance_operation(
        db,
        attempt_id=old_selector_attempt["id"],
        operation_id=old_v21_report.operation_id,
        operation_ordinal=2,
        operation_role="continuation",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=old_v21_report.operation_id
    )
    db.commit()
    crashed_owner.abandon_for_test()
    assert old_replay.external_requests == []
    assert db.execute(
        text(
            "SELECT status FROM sec_financial_parse_runs "
            "WHERE operation_id=:operation AND parser_version='xbrl-lineage-v2.1'"
        ),
        {"operation": old_v21_report.operation_id},
    ).scalar_one() == "failed"
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_financial_parse_runs parse "
            "JOIN sec_financial_parse_run_artifacts link "
            "ON link.parse_run_id=parse.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE parse.operation_id=:operation "
            "AND artifact.filename=:filename"
        ),
        {
            "operation": old_v21_report.operation_id,
            "filename": initial_client.instance_filename,
        },
    ).scalar_one() == 0

    class LaterCollidingManifestClient(SgmlPrimaryClient):
        def __init__(self):
            super().__init__()
            primary_url = next(
                url for url in self.responses if url.endswith("d927922d10q.htm")
            )
            self.responses[primary_url] = self.responses[primary_url].replace(
                b"</TEXT>", b"\n</TEXT>"
            )
            index_url = next(
                url for url in self.responses if url.endswith("/index.json")
            )
            index = json.loads(self.responses[index_url])
            for item in index["directory"]["item"]:
                if item["name"] == "d927922d10q.htm":
                    item["size"] = len(self.responses[primary_url])
            self.responses[index_url] = json.dumps(index).encode()

    later_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=LaterCollidingManifestClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc),
        parser_version="collision-parser-v1",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=later_report.operation_id
    )
    db.commit()
    assert later_report.operation_id != failed_report.operation_id
    original_manifest = db.execute(
        text(
            "SELECT DISTINCT artifact.manifest_hash "
            "FROM sec_financial_accession_attempts attempt "
            "JOIN sec_financial_accession_attempt_artifacts link "
            "ON link.attempt_id=attempt.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE attempt.operation_id=:operation"
        ),
        {"operation": failed_report.operation_id},
    ).scalar_one()
    later_manifest = db.execute(
        text(
            "SELECT DISTINCT artifact.manifest_hash "
            "FROM sec_financial_accession_attempts attempt "
            "JOIN sec_financial_accession_attempt_artifacts link "
            "ON link.attempt_id=attempt.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE attempt.operation_id=:operation"
        ),
        {"operation": later_report.operation_id},
    ).scalar_one()
    assert later_manifest != original_manifest

    session_factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(financial_cli, "SessionLocal", session_factory)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda _run: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    monkeypatch.setattr(financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        financial_cli,
        "_utc_now",
        lambda: datetime(2026, 8, 28, 2, tzinfo=timezone.utc),
    )

    class NarrowInstanceEdgarClient:
        calls: list[str] = []
        constructions = 0

        def __init__(self):
            type(self).constructions += 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url: str) -> bytes:
            type(self).calls.append(url)
            if url != initial_client.instance_url:
                pytest.fail(f"recovery fetched non-instance SEC resource: {url}")
            return initial_client.instance_content

        def get_revalidated(self, url: str) -> bytes:
            return self.get(url)

    monkeypatch.setattr(
        financial_cli, "EdgarClient", NarrowInstanceEdgarClient
    )
    report_path = reports_root / "pass-1" / f"{case_id}.json"
    canonical_finalize = financial_cli.finalize_sec_financial_ingestion_operation
    continuation_committed = threading.Event()
    allow_owner_to_publish = threading.Event()

    def pause_after_continuation_commit(session, *, operation_id):
        if operation_id not in {
            failed_report.operation_id,
            old_v21_report.operation_id,
            later_report.operation_id,
        }:
            continuation_committed.set()
            assert allow_owner_to_publish.wait(timeout=20)
        return canonical_finalize(session, operation_id=operation_id)

    monkeypatch.setattr(
        financial_cli,
        "finalize_sec_financial_ingestion_operation",
        pause_after_continuation_commit,
    )
    outcomes: list[int] = []
    errors: list[BaseException] = []

    def concurrent_retry() -> None:
        try:
            financial_cli.ingest_gold_case(
                case_id=case_id,
                max_filings=50,
                parser_version=financial_ingestion.PARSER_V2,
                history_cursor=None,
                as_of=None,
                acceptance_run_id=run_id,
                acceptance_pass=1,
                report_json=report_path,
            )
            outcomes.append(0)
        except typer.Exit as exc:
            outcomes.append(int(exc.exit_code))
        except BaseException as exc:
            errors.append(exc)

    owner = threading.Thread(target=concurrent_retry)
    owner.start()
    assert continuation_committed.wait(timeout=20)

    late_join = threading.Thread(target=concurrent_retry)
    late_join.start()
    late_join.join(timeout=10)
    assert not late_join.is_alive()
    assert outcomes == [1]
    assert db.execute(
        text("SELECT count(*) FROM sec_metric_publication_runs")
    ).scalar_one() == 0
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_case_attempts "
            "WHERE run_id=:run AND case_id=:case AND acceptance_pass=1"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 1
    assert db.execute(
        text("SELECT count(*) FROM sec_acceptance_publication_bindings")
    ).scalar_one() == 0
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_operation_links link "
            "JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id "
            "WHERE attempt.run_id=:run AND attempt.case_id=:case "
            "AND attempt.acceptance_pass=1"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 3
    assert NarrowInstanceEdgarClient.calls == [initial_client.instance_url]
    assert NarrowInstanceEdgarClient.constructions == 1

    allow_owner_to_publish.set()
    owner.join(timeout=30)
    threads = [owner, late_join]

    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert sorted(outcomes) == [1, 2]
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["publication_run_id"]
    assert NarrowInstanceEdgarClient.calls == [initial_client.instance_url]
    assert NarrowInstanceEdgarClient.constructions == 1
    attempts = db.execute(
        text(
            "SELECT attempt_ordinal FROM sec_acceptance_case_attempts "
            "WHERE run_id=:run AND case_id=:case AND acceptance_pass=1 "
            "ORDER BY attempt_ordinal"
        ),
        {"run": run_id, "case": case_id},
    ).scalars().all()
    assert attempts == [1]
    claims = db.execute(
        text(
            "SELECT claim.generation,attempt.attempt_ordinal,claim.previous_claim_id "
            "FROM sec_acceptance_case_completion_claims claim "
            "JOIN sec_acceptance_case_attempts attempt ON attempt.id=claim.attempt_id "
            "WHERE claim.run_id=:run AND claim.case_id=:case "
            "AND claim.acceptance_pass=1 ORDER BY claim.generation"
        ),
        {"run": run_id, "case": case_id},
    ).all()
    assert [(row.generation, row.attempt_ordinal) for row in claims] == [
        (1, 1),
        (2, 1),
        (3, 1),
    ]
    assert claims[0].previous_claim_id is None
    assert all(row.previous_claim_id is not None for row in claims[1:])
    links = db.execute(
        text(
            "SELECT link.operation_id,link.operation_role "
            "FROM sec_acceptance_operation_links link "
            "JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id "
            "WHERE attempt.run_id=:run AND attempt.case_id=:case "
            "ORDER BY attempt.attempt_ordinal,link.operation_ordinal"
        ),
        {"run": run_id, "case": case_id},
    ).all()
    assert links[0] == (failed_report.operation_id, "main")
    assert links[1] == (old_v21_report.operation_id, "continuation")
    assert links[2][1] == "continuation"
    assert links[2][0] not in {
        failed_report.operation_id,
        old_v21_report.operation_id,
        later_report.operation_id,
    }
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_financial_accession_attempts attempt "
            "JOIN sec_financial_accession_attempt_artifacts link "
            "ON link.attempt_id=attempt.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE attempt.operation_id=:operation "
            "AND artifact.filename='aapl-20150627.xml' "
            "AND artifact.state='retained'"
        ),
        {"operation": links[2][0]},
    ).scalar_one() == 1
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one() == 4
    assert db.execute(
        text("SELECT count(*) FROM sec_metric_publication_runs")
    ).scalar_one() == 1
    assert db.execute(
        text(
            "SELECT attempt.attempt_ordinal "
            "FROM sec_acceptance_publication_bindings binding "
            "JOIN sec_acceptance_case_attempts attempt ON attempt.id=binding.attempt_id"
        )
    ).scalar_one() == 1
    assert db.execute(
        text(
            "SELECT parser_version,status FROM sec_financial_parse_runs "
            "WHERE parser_version IN "
            "('xbrl-lineage-v2','xbrl-lineage-v2.1','xbrl-lineage-v2.3') "
            "ORDER BY id"
        )
    ).all() == [
        ("xbrl-lineage-v2", "failed"),
        ("xbrl-lineage-v2.1", "failed"),
        ("xbrl-lineage-v2.3", "succeeded"),
    ]
    recovered_manifests = set(
        db.execute(
            text(
                "SELECT DISTINCT artifact.manifest_hash "
                "FROM sec_financial_parse_runs parse "
                "JOIN sec_financial_parse_run_artifacts link "
                "ON link.parse_run_id=parse.id "
                "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
                "WHERE parse.parser_version='xbrl-lineage-v2.3' "
                "AND parse.status='succeeded'"
            )
        ).scalars()
    )
    assert len(recovered_manifests) == 1
    assert original_manifest not in recovered_manifests
    assert later_manifest not in recovered_manifests
    assert db.execute(
        text(
            "SELECT input_manifest_hash FROM sec_financial_parse_runs "
            "WHERE operation_id=:old_operation"
        ),
        {"old_operation": old_v21_report.operation_id},
    ).scalar_one() != db.execute(
        text(
            "SELECT input_manifest_hash FROM sec_financial_parse_runs "
            "WHERE operation_id=:new_operation"
        ),
        {"new_operation": links[2][0]},
    ).scalar_one()
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_financial_parse_runs parse "
            "JOIN sec_financial_parse_run_artifacts link "
            "ON link.parse_run_id=parse.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE parse.parser_version='xbrl-lineage-v2.3' "
            "AND artifact.filename='aapl-20150627.xml' "
            "AND artifact.state='retained'"
        )
    ).scalar_one() == 1
    assert db.execute(
        text("SELECT count(*) FROM sec_acceptance_report_readiness")
    ).scalar_one() == 0


def test_cli_failed_current_parser_without_provenance_delta_is_idempotent(
    db, tmp_path, monkeypatch
):
    run_id = "gold-failed-no-provenance-delta"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_failed_no_delta",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    _claim_acceptance_attempt(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        attempt_id=attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="before",
        attempt_id=attempt["id"],
    )
    stock = Stock(ticker="AAPL", exchange="US", company_name="Apple Inc.")
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2015, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="failed no-delta acceptance recovery fixture",
    )
    class MissingStatementInstanceClient(FakeEdgarClient):
        def __init__(self):
            super().__init__()
            self.instance_filename = "aapl-20150627.xml"
            self.instance_url = _canonical_artifact_url(
                CIK, "0000320193-26-000079", self.instance_filename
            )
            self.instance_content = (
                b'<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" '
                b'xmlns:dei="http://xbrl.sec.gov/dei/2025">'
                b'<xbrli:context id="I"><xbrli:entity><xbrli:identifier '
                b'scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>'
                b'</xbrli:entity><xbrli:period><xbrli:instant>2026-06-27</xbrli:instant>'
                b'</xbrli:period></xbrli:context><dei:DocumentFiscalYearFocus '
                b'contextRef="I">2026</dei:DocumentFiscalYearFocus></xbrli:xbrl>'
            )
            index_url = next(
                url for url in self.responses if url.endswith("/index.json")
            )
            payload = json.loads(self.responses[index_url])
            payload["directory"]["item"].append(
                {
                    "name": self.instance_filename,
                    "type": "text.gif",
                    "size": len(self.instance_content),
                    "description": "XBRL INSTANCE DOCUMENT",
                }
            )
            self.responses[index_url] = json.dumps(payload).encode()
            self.responses[self.instance_url] = self.instance_content

    source_client = MissingStatementInstanceClient()
    original_retain_item = financial_ingestion._retain_item
    monkeypatch.setattr(
        financial_ingestion,
        "_retain_item",
        lambda item, primary_document, referenced_statement_names=None: (
            False
            if item.get("name") == source_client.instance_filename
            else original_retain_item(
                item, primary_document, referenced_statement_names
            )
        ),
    )
    old_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=source_client,
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2",
    )
    monkeypatch.setattr(
        financial_ingestion, "_retain_item", original_retain_item
    )
    link_acceptance_operation(
        db,
        attempt_id=attempt["id"],
        operation_id=old_report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=old_report.operation_id
    )
    db.commit()
    current_attempt = attempt
    replay = financial_ingestion.build_retained_financial_replay_client(
        db,
        stock_id=stock.id,
        operation_ids=(old_report.operation_id,),
        storage_root=tmp_path,
        upstream_factory=lambda: source_client,
    )
    with replay:
        report = ingest_latest_financial_filings(
            db,
            stock_id=stock.id,
            client=replay,
            storage_root=tmp_path,
            max_filings=1,
            now=datetime(2026, 8, 28, 1, 30, tzinfo=timezone.utc),
            parser_version=financial_ingestion.PARSER_V2,
        )
    link_acceptance_operation(
        db,
        attempt_id=current_attempt["id"],
        operation_id=report.operation_id,
        operation_ordinal=2,
        operation_role="continuation",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=report.operation_id)
    db.commit()
    assert replay.external_requests == [source_client.instance_url]
    assert db.execute(
        text(
            "SELECT status FROM sec_financial_parse_runs "
            "WHERE operation_id=:operation"
        ),
        {"operation": report.operation_id},
    ).scalar_one() == "failed"
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_financial_parse_runs parse "
            "JOIN sec_financial_parse_run_artifacts link ON link.parse_run_id=parse.id "
            "JOIN sec_filing_artifacts artifact ON artifact.id=link.artifact_id "
            "WHERE parse.operation_id=:operation AND artifact.filename=:filename"
        ),
        {
            "operation": report.operation_id,
            "filename": source_client.instance_filename,
        },
    ).scalar_one() == 1

    _release_test_completion_leases(db)
    session_factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(financial_cli, "SessionLocal", session_factory)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda _run: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    monkeypatch.setattr(financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path))
    monkeypatch.setattr(
        financial_cli,
        "_utc_now",
        lambda: datetime(2026, 8, 28, 2, tzinfo=timezone.utc),
    )

    class ForbiddenUpstream:
        constructions = 0

        def __init__(self):
            type(self).constructions += 1
            pytest.fail("no-delta recovery constructed an upstream client")

    monkeypatch.setattr(financial_cli, "EdgarClient", ForbiddenUpstream)
    arguments = [
        "ingest-gold-case",
        "--case-id",
        case_id,
        "--acceptance-run-id",
        run_id,
        "--acceptance-pass",
        "1",
        "--report-json",
        str(reports_root / "pass-1" / f"{case_id}.json"),
    ]
    operation_count = db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one()
    parse_count = db.execute(
        text("SELECT count(*) FROM sec_financial_parse_runs")
    ).scalar_one()
    first = CliRunner().invoke(financial_cli.app, arguments)
    second = CliRunner().invoke(financial_cli.app, arguments)

    assert first.exit_code == second.exit_code == 1
    assert "retained_recovery_no_provenance_delta" in first.output
    assert "retained_recovery_no_provenance_delta" in second.output
    assert ForbiddenUpstream.constructions == 0
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one() == operation_count
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_parse_runs")
    ).scalar_one() == parse_count
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_operation_links link "
            "JOIN sec_acceptance_case_attempts attempt ON attempt.id=link.attempt_id "
            "WHERE attempt.run_id=:run AND link.operation_role<>'recovered'"
        ),
        {"run": run_id},
    ).scalar_one() == 2


def test_cli_appends_v23_after_failed_v22_from_retained_inputs_without_sec_fetch(
    db, tmp_path, monkeypatch
):
    run_id = "gold-v23-retained-recovery"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_v23_retained_recovery",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    _claim_acceptance_attempt(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        attempt_id=attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="before",
        attempt_id=attempt["id"],
    )
    stock = Stock(ticker="AAPL", exchange="US", company_name="Apple Inc.")
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2015, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="failed v2.2 retained recovery fixture",
    )
    db.commit()

    canonical_resolver = financial_ingestion.parse_generated_statement_occurrences

    def reject_v22(*_args, **_kwargs):
        raise financial_ingestion.StatementAuthorityParseError(
            "ambiguous_label_resource"
        )

    monkeypatch.setattr(
        financial_ingestion, "parse_generated_statement_occurrences", reject_v22
    )
    failed_report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=GeneratedStatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
        parser_version="xbrl-lineage-v2.2",
    )
    link_acceptance_operation(
        db,
        attempt_id=attempt["id"],
        operation_id=failed_report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(
        db, operation_id=failed_report.operation_id
    )
    db.commit()
    failed_run = db.execute(
        text(
            "SELECT id,input_manifest_hash,status,error_detail "
            "FROM sec_financial_parse_runs WHERE operation_id=:operation"
        ),
        {"operation": failed_report.operation_id},
    ).one()
    assert failed_run.status == "failed"
    assert "ambiguous_label_resource" in failed_run.error_detail

    monkeypatch.setattr(
        financial_ingestion,
        "parse_generated_statement_occurrences",
        canonical_resolver,
    )
    _release_test_completion_leases(db)
    monkeypatch.setattr(
        financial_cli, "SessionLocal", sessionmaker(bind=db.get_bind())
    )
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda _run: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    monkeypatch.setattr(
        financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path)
    )
    monkeypatch.setattr(
        financial_cli,
        "_utc_now",
        lambda: datetime(2026, 8, 28, 2, tzinfo=timezone.utc),
    )

    class ForbiddenUpstream:
        constructions = 0

        def __init__(self):
            type(self).constructions += 1
            pytest.fail("retained v2.3 recovery constructed an SEC client")

    monkeypatch.setattr(financial_cli, "EdgarClient", ForbiddenUpstream)
    report_path = reports_root / "pass-1" / f"{case_id}.json"
    arguments = [
        "ingest-gold-case",
        "--case-id",
        case_id,
        "--acceptance-run-id",
        run_id,
        "--acceptance-pass",
        "1",
        "--report-json",
        str(report_path),
    ]
    result = CliRunner().invoke(financial_cli.app, arguments)

    assert result.exit_code == 2, result.output
    assert report_path.exists()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["publication_run_id"]
    assert ForbiddenUpstream.constructions == 0
    runs = db.execute(
        text(
            "SELECT id,parser_version,status,input_manifest_hash,error_detail "
            "FROM sec_financial_parse_runs ORDER BY id"
        )
    ).all()
    assert [
        (run.parser_version, run.status, run.input_manifest_hash) for run in runs
    ] == [
        ("xbrl-lineage-v2.2", "failed", failed_run.input_manifest_hash),
        ("xbrl-lineage-v2.3", "succeeded", failed_run.input_manifest_hash),
    ]
    assert runs[0].id == failed_run.id
    assert runs[0].error_detail == failed_run.error_detail
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one() == 2
    assert db.execute(
        text("SELECT count(*) FROM sec_metric_publication_runs")
    ).scalar_one() == 1
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_operation_links "
            "WHERE attempt_id=:attempt"
        ),
        {"attempt": attempt["id"]},
    ).scalar_one() == 2

    successful_operation_id = db.execute(
        text(
            "SELECT operation_id FROM sec_financial_parse_runs "
            "WHERE parser_version='xbrl-lineage-v2.3' AND status='succeeded'"
        )
    ).scalar_one()
    completed_replay = financial_ingestion.build_retained_financial_replay_client(
        db,
        stock_id=stock.id,
        operation_ids=(successful_operation_id,),
        storage_root=tmp_path,
        upstream_factory=ForbiddenUpstream,
        target_parser_version=financial_ingestion.PARSER_V2,
    )
    assert completed_replay.has_reparse_provenance_delta is False
    assert completed_replay.external_requests == []
    assert ForbiddenUpstream.constructions == 0

@pytest.mark.parametrize(
    ("wrong_case", "wrong_pass"),
    (("wrong-primary", 1), ("checkpoint-primary", 2)),
)
def test_recovered_operation_link_rejects_cross_case_or_pass_authority(
    db, tmp_path, wrong_case, wrong_pass
):
    request = _request(
        db,
        tmp_path,
        ticker=f"WRONG{wrong_pass}",
        acceptance_scope=("gold-wrong-scope", "checkpoint-primary", 1),
    )
    operation_id = acceptance_operation_authority(
        db,
        run_id="gold-wrong-scope",
        case_id="checkpoint-primary",
        acceptance_pass=1,
    )["creation_operation_ids"][0]
    wrong_attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-wrong-scope",
        case_id=wrong_case,
        acceptance_pass=wrong_pass,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-wrong-scope",
        case_id=wrong_case,
        acceptance_pass=wrong_pass,
        attempt_id=wrong_attempt["id"],
    )

    with pytest.raises(DBAPIError, match="same-case creation authority"):
        link_acceptance_operation(
            db,
            attempt_id=wrong_attempt["id"],
            operation_id=operation_id,
            operation_ordinal=1,
            operation_role="recovered",
        )
    db.rollback()
    assert request.stock_id > 0


def test_failed_operation_is_atomically_classified_by_database_terminal_result(
    db, tmp_path
):
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id="gold-failed-link",
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="7" * 64,
        database_name="valuepilot_acceptance_failed_link",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db,
        run_id="gold-failed-link",
        case_id="failed-primary",
        acceptance_pass=1,
    )
    _claim_acceptance_attempt(
        db,
        run_id="gold-failed-link",
        case_id="failed-primary",
        acceptance_pass=1,
        attempt_id=attempt["id"],
    )
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-failed-link",
        case_id="failed-primary",
        acceptance_pass=1,
        phase="before",
        attempt_id=attempt["id"],
    )
    stock = Stock(ticker="FAILED", exchange="US", company_name="Failed Operation")
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="failed acceptance operation fixture",
    )
    db.commit()
    report = ingest_latest_financial_filings(
        db,
        stock_id=stock.id,
        client=ToggleInitialMainOutageClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 1, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    link_acceptance_operation(
        db,
        attempt_id=attempt["id"],
        operation_id=report.operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()

    authority = acceptance_operation_authority(
        db,
        run_id="gold-failed-link",
        case_id="failed-primary",
        acceptance_pass=1,
    )
    assert authority["links"][0]["operation_role"] == "failed"


def test_acquisition_audit_rejects_finalized_unlinked_operation_in_case_window(
    db, tmp_path
):
    request = _request(
        db,
        tmp_path,
        ticker="UNLINKED",
        acceptance_scope=("gold-unlinked", "unlinked-primary", 1),
    )
    authority = acceptance_operation_authority(
        db,
        run_id="gold-unlinked",
        case_id="unlinked-primary",
        acceptance_pass=1,
    )
    linked_operation_id = authority["creation_operation_ids"][0]
    attempt_id = int(authority["attempts"][0]["id"])
    unlinked = ingest_latest_financial_filings(
        db,
        stock_id=request.stock_id,
        client=StatementAuthorityClient(),
        storage_root=tmp_path,
        max_filings=1,
        now=datetime(2026, 8, 28, 4, tzinfo=timezone.utc),
        parser_version=financial_ingestion.PARSER_V2,
    )
    db.commit()
    finalize_sec_financial_ingestion_operation(db, operation_id=unlinked.operation_id)
    db.commit()
    record_acceptance_evidence_checkpoint(
        db,
        run_id="gold-unlinked",
        case_id="unlinked-primary",
        acceptance_pass=1,
        phase="after",
        attempt_id=attempt_id,
        operation_id=linked_operation_id,
    )
    linked_reports = linked_acceptance_ingestion_reports(
        db,
        run_id="gold-unlinked",
        case_id="unlinked-primary",
        acceptance_pass=1,
        current_reports=(),
    )
    available_at = db.execute(
        text(
            "SELECT available_at FROM sec_financial_lineage_availabilities "
            "WHERE operation_id=:operation"
        ),
        {"operation": linked_operation_id},
    ).scalar_one()
    payload = case_report_payload(
        build_case_report(
            db,
            run_id="gold-unlinked",
            case_id="unlinked-primary",
            filing_selection_as_of=datetime(2026, 8, 30, tzinfo=timezone.utc),
            expected_completed_fiscal_years=(2026,),
            ingestion_report=linked_reports[-1],
            evidence_available_at=available_at,
            acceptance_pass=1,
            ingestion_reports=linked_reports,
        )
    )

    with pytest.raises(ValueError, match="unlinked or cross-case"):
        _schema_v2_acquisition_audit(
            db,
            report=payload,
            case_id="unlinked-primary",
            identity=SimpleNamespace(id=request.issuer_identity_id),
        )


def test_runtime_before_rejects_dirty_database_and_after_requires_24x2(db, tmp_path):
    stock = Stock(ticker="DIRTY", exchange="US", company_name="Dirty Baseline")
    db.add(stock)
    db.commit()
    instance = "11111111-1111-4111-8111-111111111111"
    with pytest.raises(DBAPIError, match="clean acceptance baseline"):
        persist_rate_guard_snapshot(
            db,
            run_id="gold-dirty-before",
            phase="before",
            configured_route="https://rate-guard.example.test",
            expected_instance_id=instance,
            observed_instance_id=instance,
            fetch_mode="rate_guard",
            fallback_enabled=False,
            fallback_url=None,
            metrics={"rate_per_sec": 1.0},
            manifest_digest="8" * 64,
            database_name="valuepilot_acceptance_dirty_before",
            storage_root=tmp_path,
        )
    db.rollback()


def _complete_24x2_runtime_authority(db, tmp_path):
    instance = "11111111-1111-4111-8111-111111111111"
    common = {
        "run_id": "gold-runtime-window",
        "configured_route": "https://rate-guard.example.test",
        "expected_instance_id": instance,
        "observed_instance_id": instance,
        "fetch_mode": "rate_guard",
        "fallback_enabled": False,
        "fallback_url": None,
        "manifest_digest": "9" * 64,
        "database_name": "valuepilot_acceptance_runtime_window",
        "storage_root": tmp_path,
    }
    before = persist_rate_guard_snapshot(
        db,
        phase="before",
        metrics={"rate_per_sec": 1.0, "total_request_count": 2},
        **common,
    )
    stock = Stock(ticker="WINDOW", exchange="US", company_name="Runtime Window")
    db.add(stock)
    db.flush()
    register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik=CIK,
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 8, 28, tzinfo=timezone.utc),
        review_reason="runtime checkpoint lifecycle fixture",
    )
    db.commit()
    for acceptance_pass in (1, 2):
        for case_index in range(24):
            case_id = f"runtime-{case_index:02d}"
            attempt = begin_acceptance_case_attempt(
                db,
                run_id=common["run_id"],
                case_id=case_id,
                acceptance_pass=acceptance_pass,
            )
            _claim_acceptance_attempt(
                db,
                run_id=common["run_id"],
                case_id=case_id,
                acceptance_pass=acceptance_pass,
                attempt_id=attempt["id"],
            )
            record_acceptance_evidence_checkpoint(
                db,
                run_id=common["run_id"],
                case_id=case_id,
                acceptance_pass=acceptance_pass,
                phase="before",
                attempt_id=attempt["id"],
            )
            report = ingest_latest_financial_filings(
                db,
                stock_id=stock.id,
                client=StatementAuthorityClient(),
                storage_root=tmp_path,
                max_filings=1,
                now=datetime(2026, 8, 28, tzinfo=timezone.utc)
                + timedelta(minutes=acceptance_pass * 100 + case_index),
                parser_version=financial_ingestion.PARSER_V2,
            )
            link_acceptance_operation(
                db,
                attempt_id=attempt["id"],
                operation_id=report.operation_id,
                operation_ordinal=1,
                operation_role="main",
            )
            db.commit()
            finalize_sec_financial_ingestion_operation(
                db, operation_id=report.operation_id
            )
            db.commit()
            record_acceptance_evidence_checkpoint(
                db,
                run_id=common["run_id"],
                case_id=case_id,
                acceptance_pass=acceptance_pass,
                phase="after",
                attempt_id=attempt["id"],
                operation_id=report.operation_id,
            )
            mark_acceptance_report_ready(
                db,
                run_id=common["run_id"],
                case_id=case_id,
                acceptance_pass=acceptance_pass,
                attempt_id=attempt["id"],
                operation_id=report.operation_id,
                report_sha256=hashlib.sha256(
                    f"{case_id}:{acceptance_pass}".encode()
                ).hexdigest(),
            )
            if acceptance_pass == 1 and case_index == 0:
                with pytest.raises(DBAPIError, match="24x2 audited report-ready"):
                    persist_rate_guard_snapshot(
                        db,
                        phase="after",
                        metrics={"rate_per_sec": 1.0, "total_request_count": 3},
                        **common,
                    )
                db.rollback()
    after = persist_rate_guard_snapshot(
        db,
        phase="after",
        metrics={"rate_per_sec": 1.0, "total_request_count": 7},
        **common,
    )
    return common, before, after


def test_runtime_after_is_exact_db_and_storage_checkpoint(db, tmp_path):
    common, _before, after = _complete_24x2_runtime_authority(db, tmp_path)
    payload = build_runtime_snapshot(
        db,
        run_id=common["run_id"],
        database_name=common["database_name"],
        storage_root=tmp_path,
        rate_guard_authority=after,
    )
    assert audit_runtime_snapshot_rate_guard(
        db,
        payload=payload,
        run_id=common["run_id"],
        phase="after",
        storage_root=tmp_path,
        verify_current=True,
    ) == after

    extra = tmp_path / "financial" / "post-after-mutation.bin"
    extra.parent.mkdir(parents=True, exist_ok=True)
    extra.write_bytes(b"mutation")
    with pytest.raises(ValueError, match="retained storage changed"):
        audit_runtime_snapshot_rate_guard(
            db,
            payload=payload,
            run_id=common["run_id"],
            phase="after",
            storage_root=tmp_path,
            verify_current=True,
        )
    extra.unlink()
    db.add(Stock(ticker="POST", exchange="US", company_name="Post Snapshot"))
    db.commit()
    with pytest.raises(ValueError, match="database changed"):
        audit_runtime_snapshot_rate_guard(
            db,
            payload=payload,
            run_id=common["run_id"],
            phase="after",
            storage_root=tmp_path,
            verify_current=True,
        )


@pytest.mark.parametrize(
    "mutation_kind",
    (None, "retained_storage", "database"),
)
def test_real_isolated_cli_acceptance_audit_writes_valid_aggregate(
    db, tmp_path, monkeypatch, mutation_kind
):
    run_id = "gold-cli-audit"
    reports_root = tmp_path / "reports"
    reports_root.mkdir()
    (reports_root / "runtime-before.json").write_text("{}", encoding="utf-8")
    (reports_root / "runtime-after.json").write_text("{}", encoding="utf-8")
    manifest_bytes = financial_cli.MANIFEST_PATH.read_bytes()
    manifest = financial_cli.yaml.safe_load(manifest_bytes)
    manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
    route = "https://rate-guard.example.test"
    instance = "11111111-1111-4111-8111-111111111111"
    config_digest = rate_guard_configuration_digest(
        configured_route=route,
        expected_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
    )
    proof = {
        "configured_route": route,
        "expected_instance_id": instance,
        "fetch_mode": "rate_guard",
        "fallback_enabled": False,
        "fallback_url": None,
        "config_digest": config_digest,
        "manifest_digest": manifest_digest,
    }
    zero_metrics = {
        "rate_per_sec": 1.0,
        "total_request_count": 0,
        "total_403_count": 0,
        "total_429_count": 0,
        "total_503_count": 0,
        "cache_hits": 0,
        "cache_misses": 0,
    }
    after_metrics = {**zero_metrics, "total_request_count": 11, "cache_misses": 11}
    retained_after = retained_storage_authority(tmp_path)
    baseline_counts = {
        str(key): int(value)
        for key, value in dict(
            db.execute(text("SELECT sec_acceptance_runtime_counts()" )).scalar_one()
        ).items()
    }
    db.rollback()
    total_published = sum(
        21 * len(locked_case_contract(manifest, case)[1])
        for case in manifest["cases"]
    )
    authorities = {
        "before": {
            "schema_version": 2,
            "run_id": run_id,
            "database": "valuepilot_acceptance_cli_audit",
            "metric_facts": 0,
            "lineage_counts": {
                "mapping_versions": 1,
                "mapping_rules": 21,
                "mapping_rule_concepts": 21,
                "method_policy_versions": 1,
            },
            "source_path_proof": proof,
            "rate_guard": {
                "instance_id": instance,
                "url": route,
                "expected_instance_id": instance,
                "metrics": zero_metrics,
            },
        },
        "after": {
            "schema_version": 2,
            "run_id": run_id,
            "database": "valuepilot_acceptance_cli_audit",
            "metric_facts": total_published,
            "lineage_counts": {
                "mapping_versions": 1,
                "mapping_rules": 21,
                "mapping_rule_concepts": 21,
                "method_policy_versions": 1,
            },
            "source_path_proof": proof,
            "retained_storage": retained_after,
            "rate_guard": {
                "instance_id": instance,
                "url": route,
                "expected_instance_id": instance,
                "metrics": after_metrics,
            },
        },
    }

    class FakeRateGuardClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def verify_identity(self):
            return instance

        def metrics(self, _source):
            return after_metrics

    session_factory = sessionmaker(bind=db.get_bind())
    monkeypatch.setattr(financial_cli, "SessionLocal", session_factory)
    monkeypatch.setattr(financial_cli, "RateGuardClient", FakeRateGuardClient)
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda _run: SimpleNamespace(
            reports_root=reports_root,
            storage_root=tmp_path,
            database_name="valuepilot_acceptance_cli_audit",
        ),
    )
    monkeypatch.setattr(settings, "RATE_GUARD_URL", route)
    monkeypatch.setattr(settings, "RATE_GUARD_EXPECTED_INSTANCE_ID", instance)
    monkeypatch.setattr(settings, "EDGAR_FETCH_MODE", "rate_guard")
    monkeypatch.setattr(settings, "RATE_GUARD_ALLOW_LOCAL_FALLBACK", False)
    monkeypatch.setattr(settings, "RATE_GUARD_FALLBACK_URL", None)

    runtime_audits = []

    def audit_runtime(_db, *, payload, phase, **kwargs):
        assert payload == {}
        verify_current = bool(kwargs.get("verify_current"))
        runtime_audits.append((phase, verify_current))
        if verify_current:
            current_counts = {
                str(key): int(value)
                for key, value in dict(
                    _db.execute(
                        text("SELECT sec_acceptance_runtime_counts()")
                    ).scalar_one()
                ).items()
            }
            if current_counts != baseline_counts:
                raise ValueError("database changed after durable runtime checkpoint")
            if retained_storage_authority(tmp_path) != retained_after:
                raise ValueError(
                    "retained storage changed after durable runtime checkpoint"
                )
        return authorities[phase]

    monkeypatch.setattr(
        financial_cli, "audit_runtime_snapshot_rate_guard", audit_runtime
    )

    audited_case_count = 0

    def audit_case(_db, *, case, manifest: dict, **_kwargs):
        nonlocal audited_case_count
        audited_case_count += 1
        if audited_case_count == len(manifest["cases"]):
            if mutation_kind == "retained_storage":
                changed = b"changed after durable after scan"
                changed_digest = hashlib.sha256(changed).hexdigest()
                changed_path = (
                    tmp_path / "financial" / changed_digest[:2] / changed_digest
                )
                changed_path.parent.mkdir(parents=True)
                changed_path.write_bytes(changed)
            elif mutation_kind == "database":
                concurrent = session_factory()
                try:
                    concurrent.add(
                        Stock(
                            ticker="CONCURRENT",
                            exchange="US",
                            company_name="Concurrent Mutation",
                        )
                    )
                    concurrent.commit()
                finally:
                    concurrent.close()
        _cutoff, years = locked_case_contract(manifest, case)
        denominator = 21 * len(years)
        outcomes = {
            "metric_denominator": 21,
            "issuer_year_metric_denominator": denominator,
            "published_count": denominator,
            "typed_gap_count": 0,
            "missing_count": 0,
            "coverage_count": denominator,
        }
        return {
            "case_id": str(case["case_id"]),
            "ticker": str(case["primary_listing"]["ticker"]),
            "cik": str(case["cik"]),
            "expected_completed_fiscal_years": list(years),
            "covered_completed_fiscal_years": list(years),
            "pass_1": {
                "typed_gaps": [],
                "typed_failures": [],
                "mapping_version_id": "sec-us-gaap-v1",
                "method_policy_version_id": "sec-method-gate-v1",
                "publication_requested_cutoff": "2026-09-01T12:00:00+00:00",
                "metric_outcomes": outcomes,
            },
            "pass_2": {"typed_gaps": [], "typed_failures": []},
            "metric_outcomes": outcomes,
            "idempotency_delta": {"idempotent": True},
            "retained_integrity": {"checked": 1, "failed": 0, "bytes": 1},
            "duplicates": {
                "filings": 0,
                "artifacts": 0,
                "parse_runs": 0,
                "raw_facts": 0,
                "current_sec_slots": 0,
            },
        }

    monkeypatch.setattr(financial_cli, "build_case_database_audit", audit_case)
    for acceptance_pass in (1, 2):
        destination = reports_root / f"pass-{acceptance_pass}"
        destination.mkdir()
        for case in manifest["cases"]:
            (destination / f"{case['case_id']}.json").write_text(
                json.dumps({"acceptance_pass": acceptance_pass}), encoding="utf-8"
            )
    existing_aggregate = None
    if mutation_kind == "database":
        existing_aggregate = b'{"existing_authority":true}\n'
        (reports_root / "aggregate.json").write_bytes(existing_aggregate)

    result = CliRunner().invoke(
        financial_cli.app,
        ["acceptance-audit", "--acceptance-run-id", run_id],
    )

    if mutation_kind is not None:
        assert result.exit_code == 1
        assert "changed after durable runtime checkpoint" in result.output
        if existing_aggregate is None:
            assert not (reports_root / "aggregate.json").exists()
        else:
            assert (reports_root / "aggregate.json").read_bytes() == existing_aggregate
        assert runtime_audits == [
            ("before", False),
            ("after", True),
            ("after", True),
        ]
        return
    assert result.exit_code == 0, result.output
    assert runtime_audits == [
        ("before", False),
        ("after", True),
        ("after", True),
    ]
    aggregate = json.loads((reports_root / "aggregate.json").read_text())
    financial_cli.validate_aggregate_payload(aggregate)
    assert aggregate["case_count"] == 24
    assert aggregate["metric_facts_after"] == total_published
    assert aggregate["shared_observed_window_delta"]["requests"] == 11
    assert (reports_root / "aggregate.txt").is_file()

def test_forged_expected_result_is_zero_write_rejected(db,tmp_path):
    from app.services.sec_financial_mapping import MappingResult
    request=_request(db,tmp_path,ticker="FORGE")
    forged=PublicationRequest(request.stock_id,request.issuer_identity_id,request.mapping_version_id,request.requested_cutoff,request.amendment_policy,request.sources,MappingResult((),(),0))
    with pytest.raises(SecPublicationError,match="differs from database authority"): publish_sec_mapping_result(db,forged)
    db.rollback(); assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0

def test_source_metadata_and_pit_are_exact_zero_write_checks(db,tmp_path):
    request=_request(db,tmp_path,ticker="PIT"); source=request.sources[0]
    forged=VerifiedPublicationSource(source.parse_run_id,source.filing_id,source.accession_no,source.parser_version,"0"*64,source.available_at)
    for bad in (PublicationRequest(request.stock_id,request.issuer_identity_id,request.mapping_version_id,request.requested_cutoff,request.amendment_policy,(forged,)),
                PublicationRequest(request.stock_id,request.issuer_identity_id,request.mapping_version_id,source.available_at-timedelta(microseconds=1),request.amendment_policy,request.sources)):
        with pytest.raises(SecPublicationError,match="finalized exact"): publish_sec_mapping_result(db,bad)
    db.rollback(); assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0

def test_mapping_known_and_effective_cutoff_fail_before_write(db,tmp_path):
    request=_request(db,tmp_path,ticker="MAPLATE")
    early=PublicationRequest(request.stock_id,request.issuer_identity_id,request.mapping_version_id,
        datetime(2026,8,30,tzinfo=timezone.utc),request.amendment_policy,request.sources)
    with pytest.raises(SecPublicationError,match="mapping version is unavailable"):
        publish_sec_mapping_result(db,early)
    db.rollback(); assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0

def test_truncated_database_mapping_is_rejected_before_lock_or_write(db,tmp_path,monkeypatch):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker="TRUNC")
    actual=service._rebuild_mapping_result(db,request)
    monkeypatch.setattr(service,"_rebuild_mapping_result",lambda _db,_request: type(actual)(actual.candidates,actual.dispositions,513))
    before=db.execute(text("""SELECT (SELECT count(*) FROM sec_metric_publication_runs),
      (SELECT count(*) FROM sec_metric_publication_run_sources),(SELECT count(*) FROM sec_metric_publication_audits),
      (SELECT count(*) FROM metric_facts WHERE source_type='sec')""")).one()
    with pytest.raises(SecPublicationError,match="exceeded bounded"):
        publish_sec_mapping_result(db,request)
    db.rollback()
    after=db.execute(text("""SELECT (SELECT count(*) FROM sec_metric_publication_runs),
      (SELECT count(*) FROM sec_metric_publication_run_sources),(SELECT count(*) FROM sec_metric_publication_audits),
      (SELECT count(*) FROM metric_facts WHERE source_type='sec')""")).one()
    assert after==before

def test_runtime_concept_priority_drift_cannot_change_database_mapping(db,tmp_path,monkeypatch):
    import app.services.sec_metric_publication as service
    import app.services.sec_financial_mapping as mapping_module
    from dataclasses import replace
    request=_request(db,tmp_path,ticker="DBMAP")
    baseline=publish_sec_mapping_result(db,request); db.commit()
    original=mapping_module.canonical_sec_mapping_v1()
    revenue=original.rules[0]
    drifted=replace(original,rules=(replace(revenue,concepts=tuple(reversed(revenue.concepts))),)+original.rules[1:])
    monkeypatch.setattr(mapping_module,"canonical_sec_mapping_v1",lambda:drifted)
    replay=publish_sec_mapping_result(db,request); db.commit()
    assert replay.replayed and replay.run_id==baseline.run_id and replay.fact_ids==baseline.fact_ids

def test_slotless_audit_is_append_only(db,tmp_path):
    receipt=publish_sec_mapping_result(db,_request(db,tmp_path,ticker="AUDIT")); db.commit()
    audit_id=db.execute(text("SELECT id FROM sec_metric_publication_audits WHERE publication_run_id=:run LIMIT 1"),{"run":receipt.run_id}).scalar_one()
    for statement in ("UPDATE sec_metric_publication_audits SET detail='forged' WHERE id=:id","DELETE FROM sec_metric_publication_audits WHERE id=:id","TRUNCATE sec_metric_publication_audits"):
        with pytest.raises(DBAPIError),db.begin_nested(): db.execute(text(statement),{"id":audit_id})

def test_slot_aware_unresolved_has_normalized_occurrence_authority(db,tmp_path):
    request=_request(db,tmp_path,ticker="UNRES",normalize=False)
    receipt=publish_sec_mapping_result(db,request); db.commit()
    row=db.execute(text("""SELECT p.id,p.reason_code,p.locator_json,p.audit_json,ui.input_ordinal,ui.raw_fact_id,
      ui.statement_authority_id,ui.normalization_id,a.statement_sha256,a.occurrence_semantic_sha256
      FROM sec_metric_publications p JOIN sec_metric_publication_unresolved_inputs ui ON ui.publication_id=p.id
      JOIN sec_statement_fact_authorities a ON a.id=ui.statement_authority_id
      WHERE p.publication_run_id=:run AND p.status='unresolved' ORDER BY ui.input_ordinal LIMIT 1"""),{"run":receipt.run_id}).mappings().one()
    evidence=row.locator_json["ordered_input_occurrences"][0]
    assert row.reason_code=="unresolved_value" and row.normalization_id is None
    assert evidence["raw_fact_id"]==row.raw_fact_id and evidence["statement_authority_id"]==row.statement_authority_id
    assert evidence["statement_sha256"]==row.statement_sha256 and evidence["occurrence_semantic_sha256"]==row.occurrence_semantic_sha256
    assert row.audit_json["ordered_input_occurrences"]==row.locator_json["ordered_input_occurrences"]
    assert row.audit_json["raw_fact_ids"]==[row.raw_fact_id]
    assert row.audit_json["parse_run_ids"]==[evidence["parse_run_id"]]
    assert row.audit_json["normalization_ids"]==[None]
    assert row.audit_json["statement_authority_ids"]==[row.statement_authority_id]


@pytest.mark.parametrize("forged_value", ["1", True, 1.0, None, -1])
def test_direct_occurrence_numeric_json_types_fail_deferred_and_rollback(db,tmp_path,monkeypatch,forged_value):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker=f"TYPE{str(forged_value).replace('-','N')[:4]}")
    original=json.dumps
    numeric_fields=(
        "raw_fact_id","parse_run_id","statement_authority_id","statement_report_reference_id",
        "statement_artifact_id","filing_summary_artifact_id","report_artifact_id","report_ordinal",
        "occurrence_ordinal","row_ordinal","column_ordinal","normalization_id",
    )
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    for field in numeric_fields:
        def forged(obj,*args,_field=field,**kwargs):
            if isinstance(obj,dict) and obj.get("statement_authority_id") is not None and _field in obj:
                obj={**obj,_field:forged_value}
            return original(obj,*args,**kwargs)
        monkeypatch.setattr(service.json,"dumps",forged)
        with pytest.raises(DBAPIError):
            publish_sec_mapping_result(db,request)
            db.commit()
        db.rollback()
        assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
        assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current


@pytest.mark.parametrize(("field","forged_value"), [
    ("statement_sha256",1),("occurrence_semantic_sha256",False),
    ("filing_summary_sha256",None),("report_sha256",1),
    ("occurrence_fact_id",{}),("locator_json","not-an-object"),
    ("evidence_locator_json",[]),
])
def test_direct_occurrence_non_numeric_json_types_fail_deferred_and_rollback(db,tmp_path,monkeypatch,field,forged_value):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker=f"SHAPE{field[:3]}{len(str(forged_value))}")
    original=json.dumps
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    def forged(obj,*args,**kwargs):
        if isinstance(obj,dict) and obj.get("statement_authority_id") is not None and field in obj:
            obj={**obj,field:forged_value}
        return original(obj,*args,**kwargs)
    monkeypatch.setattr(service.json,"dumps",forged)
    with pytest.raises(DBAPIError):
        publish_sec_mapping_result(db,request)
        db.commit()
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
    assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current


def test_unresolved_normalization_wrong_json_nullability_fails_and_rolls_back(db,tmp_path,monkeypatch):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker="UNORMTYPE",normalize=False)
    original=json.dumps
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    def forged(obj,*args,**kwargs):
        if isinstance(obj,dict) and isinstance(obj.get("ordered_input_occurrences"),list):
            obj={**obj,"ordered_input_occurrences":[
                {**item,"normalization_id":1} if item.get("normalization_id") is None else item
                for item in obj["ordered_input_occurrences"]
            ]}
        return original(obj,*args,**kwargs)
    monkeypatch.setattr(service.json,"dumps",forged)
    with pytest.raises(DBAPIError):
        publish_sec_mapping_result(db,request)
        db.commit()
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
    assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current


@pytest.mark.parametrize("forged_value", ["1", True, 1.0, None, -1])
def test_unresolved_occurrence_numeric_json_types_fail_deferred_and_rollback(db,tmp_path,monkeypatch,forged_value):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker=f"UTYPE{str(forged_value).replace('-','N')[:4]}",normalize=False)
    original=json.dumps
    numeric_fields=(
        "raw_fact_id","parse_run_id","statement_authority_id","statement_report_reference_id",
        "statement_artifact_id","filing_summary_artifact_id","report_artifact_id","report_ordinal",
        "occurrence_ordinal","row_ordinal","column_ordinal",
    )
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    for field in numeric_fields:
        def forged(obj,*args,_field=field,**kwargs):
            if isinstance(obj,dict) and isinstance(obj.get("ordered_input_occurrences"),list):
                obj={**obj,"ordered_input_occurrences":[
                    {**item,_field:forged_value} for item in obj["ordered_input_occurrences"]
                ]}
            return original(obj,*args,**kwargs)
        monkeypatch.setattr(service.json,"dumps",forged)
        with pytest.raises(DBAPIError):
            publish_sec_mapping_result(db,request)
            db.commit()
        db.rollback()
        assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
        assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current


@pytest.mark.parametrize(("field","forged_value"), [
    ("statement_sha256",1),("occurrence_semantic_sha256",False),
    ("filing_summary_sha256",None),("report_sha256",1),
    ("occurrence_fact_id",{}),("locator_json","not-an-object"),
    ("evidence_locator_json",[]),
])
def test_unresolved_occurrence_non_numeric_json_types_fail_deferred_and_rollback(db,tmp_path,monkeypatch,field,forged_value):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker=f"USHAPE{field[:2]}{len(str(forged_value))}",normalize=False)
    original=json.dumps
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    def forged(obj,*args,**kwargs):
        if isinstance(obj,dict) and isinstance(obj.get("ordered_input_occurrences"),list):
            obj={**obj,"ordered_input_occurrences":[
                {**item,field:forged_value} for item in obj["ordered_input_occurrences"]
            ]}
        return original(obj,*args,**kwargs)
    monkeypatch.setattr(service.json,"dumps",forged)
    with pytest.raises(DBAPIError):
        publish_sec_mapping_result(db,request)
        db.commit()
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
    assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current


@pytest.mark.parametrize("forged_value", ["1", 1.0, -1, False])
def test_unresolved_null_normalization_rejects_non_null_json_types(db,tmp_path,monkeypatch,forged_value):
    import app.services.sec_metric_publication as service
    request=_request(db,tmp_path,ticker=f"UNORM{str(forged_value).replace('-','N')[:4]}",normalize=False)
    original=json.dumps
    before_current=db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()
    def forged(obj,*args,**kwargs):
        if isinstance(obj,dict) and isinstance(obj.get("ordered_input_occurrences"),list):
            obj={**obj,"ordered_input_occurrences":[
                {**item,"normalization_id":forged_value} for item in obj["ordered_input_occurrences"]
            ]}
        return original(obj,*args,**kwargs)
    monkeypatch.setattr(service.json,"dumps",forged)
    with pytest.raises(DBAPIError):
        publish_sec_mapping_result(db,request)
        db.commit()
    db.rollback()
    assert db.execute(text("SELECT count(*) FROM sec_metric_publication_runs")).scalar_one()==0
    assert db.execute(text("SELECT count(*) FROM metric_facts WHERE source_type='sec' AND is_current")).scalar_one()==before_current

def test_stock_lock_serializes_exact_replay(isolated_engine,tmp_path):
    Session=sessionmaker(bind=isolated_engine)
    with Session() as seed: request=_request(seed,tmp_path,ticker="LOCK")
    blocker=Session(); acquire_sec_financial_stock_lock(blocker,stock_id=request.stock_id)
    barrier=threading.Barrier(3); receipts=[]; errors=[]
    def worker():
        session=Session()
        try: barrier.wait(timeout=5); receipts.append(publish_sec_mapping_result(session,request)); session.commit()
        except BaseException as exc: session.rollback(); errors.append(exc)
        finally: session.close()
    threads=[threading.Thread(target=worker),threading.Thread(target=worker)]
    [thread.start() for thread in threads]; barrier.wait(timeout=5); blocker.commit()
    [thread.join(timeout=15) for thread in threads]; blocker.close()
    assert not errors and sorted(item.replayed for item in receipts)==[False,True]


def test_sec_recovery_stock_lock_rollback_releases_and_different_stock_proceeds(
    isolated_engine,
):
    Session = sessionmaker(bind=isolated_engine)
    blocker = Session()
    acquire_sec_financial_stock_lock(blocker, stock_id=91_001)
    same_acquired = threading.Event()
    other_acquired = threading.Event()
    errors: list[BaseException] = []

    def acquire(stock_id: int, acquired: threading.Event) -> None:
        session = Session()
        try:
            acquire_sec_financial_stock_lock(session, stock_id=stock_id)
            acquired.set()
            session.rollback()
        except BaseException as exc:
            errors.append(exc)
        finally:
            session.close()

    same = threading.Thread(target=acquire, args=(91_001, same_acquired))
    other = threading.Thread(target=acquire, args=(91_002, other_acquired))
    same.start()
    other.start()
    other.join(timeout=5)

    assert other_acquired.is_set()
    assert not same_acquired.is_set()
    blocker.rollback()
    blocker.close()
    same.join(timeout=5)
    assert same_acquired.is_set()
    assert errors == []


@pytest.mark.parametrize("owner_end", ["release", "disconnect"])
def test_acceptance_completion_claim_is_nonblocking_append_only_and_crash_recoverable(
    db, tmp_path, isolated_engine, owner_end
):
    run_id = "gold-completion-claim"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_completion_claim",
        storage_root=tmp_path,
    )
    first_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    append_acceptance_completion_claim(owner, attempt_id=first_attempt["id"])

    Session = sessionmaker(bind=isolated_engine)
    contender_session = Session()
    try:
        assert acquire_acceptance_completion_lease(
            contender_session, run_id=run_id, case_id=case_id, acceptance_pass=1
        ) is None
    finally:
        contender_session.close()
    other_session = Session()
    try:
        other_case = acquire_acceptance_completion_lease(
            other_session,
            run_id=run_id,
            case_id="msft-primary",
            acceptance_pass=1,
        )
        assert other_case is not None
        other_case.release()
    finally:
        other_session.close()

    second_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    successor_started = threading.Event()
    successor_committed = threading.Event()
    successor_errors: list[BaseException] = []

    def direct_successor_insert() -> None:
        connection = isolated_engine.connect()
        try:
            successor_started.set()
            connection.execute(
                text(
                    "INSERT INTO sec_acceptance_case_completion_claims "
                    "(run_id,case_id,acceptance_pass,attempt_id,generation,"
                    "claimed_at,created_at,created_txid) VALUES "
                    "(:run,:case,1,:attempt,1,clock_timestamp(),"
                    "clock_timestamp(),txid_current())"
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": second_attempt["id"],
                },
            )
            connection.commit()
            successor_committed.set()
        except BaseException as exc:
            connection.rollback()
            successor_errors.append(exc)
        finally:
            connection.close()

    direct_successor = threading.Thread(target=direct_successor_insert)
    direct_successor.start()
    assert successor_started.wait(timeout=5)
    direct_successor.join(timeout=10)
    assert not direct_successor.is_alive()
    assert len(successor_errors) == 1
    assert "active session lease" in str(successor_errors[0])
    assert not successor_committed.is_set()

    if owner_end == "release":
        owner.release()
    else:
        owner.abandon_for_test()
    successor = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert successor is not None
    assert successor.attempt_id == first_attempt["id"]
    try:
        claims = db.execute(
            text(
                "SELECT generation,attempt_id,previous_claim_id "
                "FROM sec_acceptance_case_completion_claims "
                "WHERE run_id=:run AND case_id=:case ORDER BY generation"
            ),
            {"run": run_id, "case": case_id},
        ).all()
        assert [(row.generation, row.attempt_id) for row in claims] == [
            (1, first_attempt["id"]),
            (2, first_attempt["id"]),
        ]
        assert claims[0].previous_claim_id is None
        assert claims[1].previous_claim_id is not None

        with pytest.raises(DBAPIError, match="active completion owner"):
            db.execute(
                text(
                    "INSERT INTO sec_acceptance_evidence_checkpoints "
                    "(run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,"
                    "evidence_counts,captured_at,created_at,created_txid) VALUES "
                    "(:run,:case,1,'after',:attempt,:operation,'{}'::jsonb,"
                    "clock_timestamp(),clock_timestamp(),txid_current())"
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": second_attempt["id"],
                    "operation": "11111111-1111-4111-8111-111111111111",
                },
            )
        db.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            db.execute(
                text(
                    "UPDATE sec_acceptance_case_completion_claims "
                    "SET generation=generation+1 WHERE id=:id"
                ),
                {"id": successor.claim_id},
            )
        db.rollback()
    finally:
        successor.release()


def test_fresh_completion_attempt_claim_and_before_are_one_transaction(
    db, tmp_path
):
    run_id = "gold-fresh-completion"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_fresh_completion",
        storage_root=tmp_path,
    )
    db.rollback()
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    try:
        attempt, before = initialize_acceptance_case_attempt(owner)
        rows = db.execute(
            text(
                """SELECT attempt.created_txid AS attempt_txid,
                          claim.created_txid AS claim_txid,
                          checkpoint.created_txid AS checkpoint_txid,
                          attempt.attempted_at,claim.claimed_at,checkpoint.captured_at
                   FROM sec_acceptance_case_attempts attempt
                   JOIN sec_acceptance_case_completion_claims claim
                     ON claim.attempt_id=attempt.id
                   JOIN sec_acceptance_evidence_checkpoints checkpoint
                     ON checkpoint.attempt_id=attempt.id AND checkpoint.phase='before'
                   WHERE attempt.id=:attempt"""
            ),
            {"attempt": attempt["id"]},
        ).mappings().one()
        assert rows.attempt_txid == rows.claim_txid == rows.checkpoint_txid
        assert rows.attempted_at <= rows.claimed_at <= rows.captured_at
        assert before["attempt_id"] == attempt["id"] == owner.attempt_id
        assert before["operation_id"] is None
    finally:
        owner.release()

    recovered = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert recovered is not None
    try:
        assert recovered.attempt_id == attempt["id"]
        assert db.execute(
            text(
                "SELECT count(*) FROM sec_acceptance_case_attempts "
                "WHERE run_id=:run AND case_id=:case"
            ),
            {"run": run_id, "case": case_id},
        ).scalar_one() == 1
        assert db.execute(
            text(
                "SELECT count(*) FROM sec_acceptance_evidence_checkpoints "
                "WHERE run_id=:run AND case_id=:case AND phase='before'"
            ),
            {"run": run_id, "case": case_id},
        ).scalar_one() == 1
    finally:
        recovered.release()


def test_fresh_completion_bootstrap_failure_rolls_back_all_authority(db, tmp_path):
    run_id = "gold-fresh-rollback"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="f" * 64,
        database_name="valuepilot_acceptance_gold_fresh_rollback",
        storage_root=tmp_path,
    )
    db.rollback()
    db.execute(
        text(
            """CREATE FUNCTION fail_fresh_before_for_test()
               RETURNS trigger LANGUAGE plpgsql AS $$
               BEGIN RAISE EXCEPTION 'fresh before test failure'; END $$;
               CREATE TRIGGER fail_fresh_before_for_test
               BEFORE INSERT ON sec_acceptance_evidence_checkpoints
               FOR EACH ROW EXECUTE FUNCTION fail_fresh_before_for_test()"""
        )
    )
    db.commit()
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    try:
        with pytest.raises(DBAPIError, match="fresh before test failure"):
            initialize_acceptance_case_attempt(owner)
        assert owner.attempt_id is None
        counts = db.execute(
            text(
                """SELECT
                     (SELECT count(*) FROM sec_acceptance_case_attempts
                       WHERE run_id=:run) AS attempts,
                     (SELECT count(*) FROM sec_acceptance_case_completion_claims
                       WHERE run_id=:run) AS claims,
                     (SELECT count(*) FROM sec_acceptance_evidence_checkpoints
                       WHERE run_id=:run) AS checkpoints"""
            ),
            {"run": run_id},
        ).one()
        assert tuple(counts) == (0, 0, 0)
    finally:
        owner.release()


def test_cli_fresh_case_atomically_stamps_completion_before_any_operation(
    db, tmp_path, isolated_engine, monkeypatch
):
    run_id = "gold-fresh-cli"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    reports_root = tmp_path / "reports"
    report_path = reports_root / "pass-1" / f"{case_id}.json"
    report_path.parent.mkdir(parents=True)
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="a" * 64,
        database_name="valuepilot_acceptance_gold_fresh_cli",
        storage_root=tmp_path,
    )
    db.rollback()
    monkeypatch.setattr(
        financial_cli, "SessionLocal", sessionmaker(bind=isolated_engine)
    )
    monkeypatch.setattr(
        financial_cli,
        "preflight_configured_acceptance_runtime",
        lambda _run: SimpleNamespace(
            run_id=run_id,
            reports_root=reports_root,
            storage_root=tmp_path,
        ),
    )
    monkeypatch.setattr(
        financial_cli.settings, "EDGAR_RAW_STORAGE_DIR", str(tmp_path)
    )
    monkeypatch.setattr(
        financial_cli,
        "_recover_completed_gold_case_report",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        financial_cli,
        "recoverable_bound_acceptance_attempt",
        lambda *_args, **_kwargs: None,
    )

    def fail_after_durable_before(*_args, **_kwargs):
        raise RuntimeError("stop after durable fresh completion bootstrap")

    monkeypatch.setattr(
        financial_cli, "_resolve_gold_case_stock", fail_after_durable_before
    )

    class ForbiddenEdgarClient:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("fresh completion bootstrap reached SEC client construction")

    monkeypatch.setattr(financial_cli, "EdgarClient", ForbiddenEdgarClient)
    arguments = [
        "ingest-gold-case",
        "--case-id",
        case_id,
        "--acceptance-run-id",
        run_id,
        "--acceptance-pass",
        "1",
        "--report-json",
        str(report_path),
    ]
    first = CliRunner().invoke(financial_cli.app, arguments)
    assert first.exit_code == 1
    assert "stop after durable fresh completion bootstrap" in first.output
    authority = db.execute(
        text(
            """SELECT attempt.id,attempt.created_txid AS attempt_txid,
                      claim.created_txid AS claim_txid,
                      checkpoint.created_txid AS checkpoint_txid
               FROM sec_acceptance_case_attempts attempt
               JOIN sec_acceptance_case_completion_claims claim
                 ON claim.attempt_id=attempt.id
               JOIN sec_acceptance_evidence_checkpoints checkpoint
                 ON checkpoint.attempt_id=attempt.id AND checkpoint.phase='before'
               WHERE attempt.run_id=:run AND attempt.case_id=:case"""
        ),
        {"run": run_id, "case": case_id},
    ).mappings().one()
    assert authority.attempt_txid == authority.claim_txid == authority.checkpoint_txid
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one() == 0
    db.rollback()

    second = CliRunner().invoke(financial_cli.app, arguments)
    assert second.exit_code == 1
    assert "stop after durable fresh completion bootstrap" in second.output
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_case_attempts "
            "WHERE run_id=:run AND case_id=:case"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 1
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_case_completion_claims "
            "WHERE run_id=:run AND case_id=:case"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 2
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_evidence_checkpoints "
            "WHERE run_id=:run AND case_id=:case AND phase='before'"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 1
    assert db.execute(
        text("SELECT count(*) FROM sec_financial_ingestion_operations")
    ).scalar_one() == 0


def test_acceptance_completion_lock_key_is_canonical_for_utf8_case_and_pass(db):
    row = db.execute(
        text(
            "SELECT sec_acceptance_completion_lock_namespace() AS namespace,"
            "sec_acceptance_completion_lock_local(:run,:case,1::smallint) AS exact_key,"
            "sec_acceptance_completion_lock_local(:run,:case,1::smallint) AS replay_key,"
            "sec_acceptance_completion_lock_local(:lower_run,:case,1::smallint) AS case_key,"
            "sec_acceptance_completion_lock_local(:run,:case,2::smallint) AS pass_key"
        ),
        {
            "run": "FT04-Δ-雪",
            "lower_run": "ft04-δ-雪",
            "case": "AAPL-É-primary",
        },
    ).mappings().one()
    assert row.namespace == 1448296515
    assert row.exact_key == row.replay_key
    assert row.exact_key != row.case_key
    assert row.exact_key != row.pass_key


def test_completion_claim_owner_identity_is_database_stamped(db, tmp_path):
    run_id = "gold-owner-stamp"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_owner_stamp",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    try:
        with pytest.raises(DBAPIError, match="database stamped"):
            owner._connection.execute(
                text(
                    """INSERT INTO sec_acceptance_case_completion_claims
                         (run_id,case_id,acceptance_pass,attempt_id,generation,
                          owner_backend_pid,owner_backend_start,
                          owner_session_token_hash,claimed_at,created_at,created_txid)
                       VALUES (:run,:case,1,:attempt,1,1,'2000-01-01Z',:hash,
                               clock_timestamp(),clock_timestamp(),txid_current())"""
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": attempt["id"],
                    "hash": "0" * 32,
                },
            )
        owner._connection.rollback()
        append_acceptance_completion_claim(owner, attempt_id=attempt["id"])
        stamped = owner._connection.execute(
            text(
                """SELECT owner_backend_pid,owner_backend_start,
                          owner_session_token_hash,pg_backend_pid() AS current_pid,
                          current_setting(
                            'valuepilot.sec_acceptance_completion_owner_token',true
                          ) AS session_token
                   FROM sec_acceptance_case_completion_claims WHERE id=:claim"""
            ),
            {"claim": owner.claim_id},
        ).mappings().one()
        assert stamped.owner_backend_pid == stamped.current_pid
        assert stamped.owner_backend_start is not None
        assert stamped.session_token
        assert stamped.owner_session_token_hash != "0" * 32
        assert owner._connection.execute(
            text("SELECT md5(:token)"), {"token": stamped.session_token}
        ).scalar_one() == stamped.owner_session_token_hash
    finally:
        owner.release()


def test_acceptance_authority_writes_require_a_completion_claim(db, tmp_path):
    run_id = "gold-no-completion-claim"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_no_claim",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )

    statements = (
        (
            "sec_acceptance_operation_links",
            """INSERT INTO sec_acceptance_operation_links
                 (attempt_id,operation_id,operation_ordinal,operation_role,
                  linked_at,created_at,created_txid)
               VALUES (:attempt,'11111111-1111-4111-8111-111111111111',1,'main',
                       clock_timestamp(),clock_timestamp(),txid_current())""",
        ),
        (
            "sec_acceptance_publication_bindings",
            """INSERT INTO sec_acceptance_publication_bindings
                 (attempt_id,requested_cutoff,source_set_sha256,
                  ordered_source_identities,mapping_version_id,amendment_policy,
                  expected_publication_run_id,publication_run_id,bound_at,
                  created_at,created_txid)
               VALUES (:attempt,clock_timestamp(),:digest,'[]'::jsonb,'missing',
                       'latest-known-v1',NULL,
                       '11111111-1111-4111-8111-111111111111',clock_timestamp(),
                       clock_timestamp(),txid_current())""",
        ),
        (
            "sec_acceptance_evidence_checkpoints",
            """INSERT INTO sec_acceptance_evidence_checkpoints
                 (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                  evidence_counts,captured_at,created_at,created_txid)
               VALUES (:run,:case,1,'before',:attempt,NULL,'{}'::jsonb,
                       clock_timestamp(),clock_timestamp(),txid_current())""",
        ),
        (
            "sec_acceptance_evidence_checkpoints",
            """INSERT INTO sec_acceptance_evidence_checkpoints
                 (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                  evidence_counts,captured_at,created_at,created_txid)
               VALUES (:run,:case,1,'after',:attempt,
                       '11111111-1111-4111-8111-111111111111','{}'::jsonb,
                       clock_timestamp(),clock_timestamp(),txid_current())""",
        ),
    )
    for _table, statement in statements:
        with pytest.raises(DBAPIError, match="active completion owner"):
            db.execute(
                text(statement),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": attempt["id"],
                    "digest": "a" * 64,
                },
            )
        db.rollback()

    assert db.execute(
        text(
            "SELECT (SELECT count(*) FROM sec_acceptance_operation_links),"
            "(SELECT count(*) FROM sec_acceptance_publication_bindings),"
            "(SELECT count(*) FROM sec_acceptance_evidence_checkpoints)"
        )
    ).one() == (0, 0, 0)


@pytest.mark.parametrize("owner_end", ["release", "disconnect"])
def test_inactive_completion_claim_cannot_authorize_direct_writes(
    db, tmp_path, isolated_engine, owner_end
):
    run_id = "gold-disconnected-owner"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_disconnected_owner",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    append_acceptance_completion_claim(owner, attempt_id=attempt["id"])
    if owner_end == "release":
        owner.release()
    else:
        owner.abandon_for_test()

    statements = (
        """INSERT INTO sec_acceptance_evidence_checkpoints
             (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
              evidence_counts,captured_at,created_at,created_txid)
           VALUES (:run,:case,1,'before',:attempt,NULL,'{}'::jsonb,
                   clock_timestamp(),clock_timestamp(),txid_current())""",
        """INSERT INTO sec_acceptance_evidence_checkpoints
             (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
              evidence_counts,captured_at,created_at,created_txid)
           VALUES (:run,:case,1,'after',:attempt,
                   '11111111-1111-4111-8111-111111111111','{}'::jsonb,
                   clock_timestamp(),clock_timestamp(),txid_current())""",
        """INSERT INTO sec_acceptance_operation_links
             (attempt_id,operation_id,operation_ordinal,operation_role,
              linked_at,created_at,created_txid)
           VALUES (:attempt,'11111111-1111-4111-8111-111111111111',1,'main',
                   clock_timestamp(),clock_timestamp(),txid_current())""",
        """INSERT INTO sec_acceptance_publication_bindings
             (attempt_id,requested_cutoff,source_set_sha256,
              ordered_source_identities,mapping_version_id,amendment_policy,
              expected_publication_run_id,publication_run_id,bound_at,
              created_at,created_txid)
           VALUES (:attempt,clock_timestamp(),:digest,'[]'::jsonb,'missing',
                   'latest-known-v1',NULL,
                   '11111111-1111-4111-8111-111111111111',clock_timestamp(),
                   clock_timestamp(),txid_current())""",
    )
    for statement in statements:
        connection = isolated_engine.connect()
        try:
            with pytest.raises(DBAPIError, match="active completion owner"):
                connection.execute(
                    text(statement),
                    {
                        "run": run_id,
                        "case": case_id,
                        "attempt": attempt["id"],
                        "digest": "a" * 64,
                    },
                )
            connection.rollback()
        finally:
            connection.close()

    assert db.execute(
        text(
            "SELECT (SELECT count(*) FROM sec_acceptance_operation_links),"
            "(SELECT count(*) FROM sec_acceptance_publication_bindings),"
            "(SELECT count(*) FROM sec_acceptance_evidence_checkpoints)"
        )
    ).one() == (0, 0, 0)


def test_direct_before_checkpoint_cannot_preempt_live_completion_owner(
    db, tmp_path, isolated_engine
):
    run_id = "gold-before-owner-race"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_before_race",
        storage_root=tmp_path,
    )
    owner_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    contender_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    append_acceptance_completion_claim(owner, attempt_id=owner_attempt["id"])

    started = threading.Event()
    finished = threading.Event()
    errors: list[BaseException] = []

    def direct_before_insert() -> None:
        connection = isolated_engine.connect()
        try:
            started.set()
            connection.execute(
                text(
                    """INSERT INTO sec_acceptance_evidence_checkpoints
                         (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                          evidence_counts,captured_at,created_at,created_txid)
                       VALUES (:run,:case,1,'before',:attempt,NULL,'{}'::jsonb,
                               clock_timestamp(),clock_timestamp(),txid_current())"""
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": contender_attempt["id"],
                },
            )
            connection.commit()
        except BaseException as exc:
            connection.rollback()
            errors.append(exc)
        finally:
            finished.set()
            connection.close()

    contender = threading.Thread(target=direct_before_insert)
    contender.start()
    assert started.wait(timeout=5)
    assert not finished.wait(timeout=0.5)
    checkpoint = record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="before",
        attempt_id=owner_attempt["id"],
    )
    assert checkpoint["attempt_id"] == owner_attempt["id"]
    owner.release()
    contender.join(timeout=10)
    assert not contender.is_alive()
    assert len(errors) == 1
    assert "active completion owner" in str(errors[0])
    assert db.execute(
        text(
            "SELECT attempt_id FROM sec_acceptance_evidence_checkpoints "
            "WHERE run_id=:run AND case_id=:case AND phase='before'"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == owner_attempt["id"]


def test_checkpoint_exact_replay_rejects_forged_existing_authority(db, tmp_path):
    run_id = "gold-forged-before"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_forged_before",
        storage_root=tmp_path,
    )
    attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    _claim_acceptance_attempt(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        attempt_id=attempt["id"],
    )
    db.execute(text("ALTER TABLE sec_acceptance_evidence_checkpoints DISABLE TRIGGER USER"))
    try:
        db.execute(
            text(
                """INSERT INTO sec_acceptance_evidence_checkpoints
                     (run_id,case_id,acceptance_pass,phase,attempt_id,operation_id,
                      evidence_counts,captured_at,created_at,created_txid)
                   VALUES (:run,:case,1,'before',:attempt,NULL,'{}'::jsonb,
                           clock_timestamp(),clock_timestamp(),txid_current())"""
            ),
            {"run": run_id, "case": case_id, "attempt": attempt["id"]},
        )
        db.commit()
    finally:
        db.execute(
            text("ALTER TABLE sec_acceptance_evidence_checkpoints ENABLE TRIGGER USER")
        )
        db.commit()

    with pytest.raises(
        ValueError, match="checkpoint existing authority mismatch"
    ):
        record_acceptance_evidence_checkpoint(
            db,
            run_id=run_id,
            case_id=case_id,
            acceptance_pass=1,
            phase="before",
            attempt_id=attempt["id"],
        )


def test_direct_successor_rechecks_completed_status_after_live_owner_releases(
    db, tmp_path, isolated_engine
):
    run_id = "gold-claim-status-recheck"
    case_id = "aapl-primary"
    instance = "11111111-1111-4111-8111-111111111111"
    persist_rate_guard_snapshot(
        db,
        run_id=run_id,
        phase="before",
        configured_route="https://rate-guard.example.test",
        expected_instance_id=instance,
        observed_instance_id=instance,
        fetch_mode="rate_guard",
        fallback_enabled=False,
        fallback_url=None,
        metrics={"rate_per_sec": 1.0},
        manifest_digest="e" * 64,
        database_name="valuepilot_acceptance_gold_claim_status_recheck",
        storage_root=tmp_path,
    )
    owner_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    owner = acquire_acceptance_completion_lease(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    assert owner is not None
    append_acceptance_completion_claim(owner, attempt_id=owner_attempt["id"])

    stock = Stock(ticker="CLAIMSTATUS", exchange="US", company_name="Claim Status")
    db.add(stock)
    db.flush()
    identity = register_reviewed_sec_identity(
        db,
        stock_id=stock.id,
        cik="0000000199",
        effective_from=date(2020, 1, 1),
        known_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        review_reason="completion claim status recheck fixture",
    )
    db.commit()
    operation_id = "11111111-1111-4111-8111-111111111199"
    db.execute(
        text(
            "INSERT INTO sec_financial_ingestion_operations "
            "(id,issuer_identity_id,attempted_at) "
            "VALUES (:operation,:identity,clock_timestamp())"
        ),
        {"operation": operation_id, "identity": identity.id},
    )
    link_acceptance_operation(
        db,
        attempt_id=owner_attempt["id"],
        operation_id=operation_id,
        operation_ordinal=1,
        operation_role="main",
    )
    db.commit()
    successor_attempt = begin_acceptance_case_attempt(
        db, run_id=run_id, case_id=case_id, acceptance_pass=1
    )
    unleased = isolated_engine.connect()
    try:
        with pytest.raises(DBAPIError, match="active session lease"):
            unleased.execute(
                text(
                    "INSERT INTO sec_acceptance_case_completion_claims "
                    "(run_id,case_id,acceptance_pass,attempt_id,generation,"
                    "claimed_at,created_at,created_txid) VALUES "
                    "(:run,:case,1,:attempt,1,clock_timestamp(),"
                    "clock_timestamp(),txid_current())"
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": successor_attempt["id"],
                },
            )
        unleased.rollback()
    finally:
        unleased.close()

    record_acceptance_evidence_checkpoint(
        db,
        run_id=run_id,
        case_id=case_id,
        acceptance_pass=1,
        phase="after",
        attempt_id=owner_attempt["id"],
        operation_id=operation_id,
    )
    owner.release()

    leased_successor = isolated_engine.connect()
    try:
        leased_successor.execute(
            text(
                "SELECT pg_advisory_lock("
                "sec_acceptance_completion_lock_namespace(),"
                "sec_acceptance_completion_lock_local("
                ":run,:case,CAST(1 AS smallint)))"
            ),
            {"run": run_id, "case": case_id},
        )
        with pytest.raises(
            DBAPIError, match="completion takeover must retain durable attempt authority"
        ):
            leased_successor.execute(
                text(
                    "INSERT INTO sec_acceptance_case_completion_claims "
                    "(run_id,case_id,acceptance_pass,attempt_id,generation,"
                    "claimed_at,created_at,created_txid) VALUES "
                    "(:run,:case,1,:attempt,1,clock_timestamp(),"
                    "clock_timestamp(),txid_current())"
                ),
                {
                    "run": run_id,
                    "case": case_id,
                    "attempt": successor_attempt["id"],
                },
            )
        leased_successor.rollback()
    finally:
        leased_successor.close()
    assert db.execute(
        text(
            "SELECT count(*) FROM sec_acceptance_case_completion_claims "
            "WHERE run_id=:run AND case_id=:case"
        ),
        {"run": run_id, "case": case_id},
    ).scalar_one() == 1
