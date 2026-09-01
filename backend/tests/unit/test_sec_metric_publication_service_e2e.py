"""Real isolated-PostgreSQL tests for canonical SEC publication authority."""
from __future__ import annotations
import hashlib, os, subprocess, threading
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker
from app.core.config import settings
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.sec_financial_ingestion import finalize_sec_financial_ingestion_operation, ingest_latest_financial_filings, register_reviewed_sec_identity
from app.services.sec_metric_publication import PublicationRequest, SecPublicationError, VerifiedPublicationSource, finalize_sec_publication, publish_sec_mapping_result
from test_sec_financial_lineage import (
    CIK,
    StatementAuthorityClient,
    SUBMISSIONS_URL,
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
    finally: session.close()

def _request(db,tmp_path,*,ticker="PUB",normalize=True):
    known=datetime(2026,8,27,12,tzinfo=timezone.utc)
    stock=Stock(ticker=ticker,exchange="US",company_name="Apple Inc."); db.add(stock); db.flush()
    identity=register_reviewed_sec_identity(db,stock_id=stock.id,cik=CIK,effective_from=date(1980,12,12),known_at=known,review_reason="publication fixture reviewed identity")
    db.commit()
    report=ingest_latest_financial_filings(db,stock_id=stock.id,client=StatementAuthorityClient(),storage_root=tmp_path,max_filings=1,now=known+timedelta(minutes=5),parser_version="xbrl-lineage-v2")
    db.commit(); finalize_sec_financial_ingestion_operation(db,operation_id=report.operation_id); db.commit()
    parse=db.execute(text("""SELECT pr.id,pr.filing_id,pr.parser_version,pr.input_manifest_hash,f.accession_no,a.available_at
      FROM sec_financial_parse_runs pr JOIN sec_financial_filings f ON f.id=pr.filing_id
      JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
      WHERE pr.status='succeeded' ORDER BY pr.id DESC LIMIT 1""")).mappings().one()
    rule=db.execute(text("SELECT id FROM sec_metric_mapping_rules WHERE mapping_version_id='sec-us-gaap-v1' AND rule_id='sec.revenue'")).scalar_one()
    raws=db.execute(text("""SELECT DISTINCT raw.id,raw.raw_value,raw.scale,raw.sign FROM sec_raw_xbrl_facts raw JOIN sec_statement_fact_authorities a ON a.raw_fact_id=raw.id
      WHERE raw.parse_run_id=:parse AND raw.concept LIKE '%RevenueFromContract%'
        AND (raw.transformation_format IS NOT NULL OR raw.raw_value NOT LIKE '%,%') ORDER BY raw.id"""),{"parse":parse.id}).all()
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
        parser_version="xbrl-lineage-v2",
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
        parser_version="xbrl-lineage-v2",
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
    restored_request = PublicationRequest(
        original.stock_id,
        original.issuer_identity_id,
        original.mapping_version_id,
        restored.available_at + timedelta(seconds=1),
        original.amendment_policy,
        (restored_source,),
    )
    restored_receipt = publish_sec_mapping_result(db, restored_request)
    db.commit()
    finalize_sec_publication(db, restored_receipt.run_id)
    db.commit()
    assert active_sec_run_unresolved_states(db, stock_id=original.stock_id) == []
    assert guard_sec_run_availability(
        db, stock_id=original.stock_id, facts=[same_cycle_sec]
    ) == [same_cycle_sec]

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
    blocker=Session(); blocker.execute(text("SELECT pg_advisory_xact_lock(:key)"),{"key":request.stock_id})
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
