from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
import pytest

from app.models.artifacts import PdfDocument
from app.models.extractions import MetricExtraction
from app.models.facts import MetricFact
from app.models.sec_financials import (
    SecFilingArtifact,
    SecFinancialFiling,
    SecFinancialParseRun,
    SecFinancialParseRunArtifact,
    SecMetricPublication,
    SecRawXbrlFact,
)
from app.services.sec_metric_publication import _load_rules, publish_sec_metric_facts
from app.services.sec_financial_ingestion import SecFinancialIngestionError
from app.services.metric_fact_visibility import visible_metric_fact_predicate
from app.services.research_cases import evidence_is_available
from app.services.research_workspace import build_research_workspace
from app.models.research import ResearchCase
from app.models.users import User
from tests.unit.test_sec_financial_lineage import _database_lineage_fixture


def _fact(
    *,
    run_id: int,
    artifact_id: int,
    ordinal: int,
    concept: str,
    raw_value: str,
    unit_measure: str,
    scale: int | None = None,
    dimensions: dict[str, str] | None = None,
    period_start: date = date(2026, 4, 1),
    period_end: date = date(2026, 6, 30),
) -> SecRawXbrlFact:
    return SecRawXbrlFact(
        parse_run_id=run_id,
        artifact_id=artifact_id,
        ordinal=ordinal,
        concept=concept,
        concept_namespace_uri="http://fasb.org/us-gaap/2025",
        context_id="D2026Q2",
        unit_id="fixture-unit",
        unit_measure=unit_measure,
        raw_value=raw_value,
        transformation_format="ixt:num-dot-decimal",
        decimals="-6" if scale else "2",
        scale=scale,
        is_nil=False,
        period_start=period_start,
        period_end=period_end,
        entity_identifier="0000000042",
        dimensions_json=dimensions or {},
        locator_json={
            "artifact_id": artifact_id,
            "element_id": f"fact-{ordinal}",
            "locator_type": "inline_xbrl_html",
            "nearby_text_snippet": f"fixture fact {ordinal}",
            "nearby_text_sha256": str(ordinal) * 64,
        },
    )


def test_sec_database_mapping_registry_matches_authoritative_spec(db_session) -> None:
    rules, policy = _load_rules("sec-us-gaap-v2")
    policy_known_at = datetime.fromisoformat(
        str(policy["known_at"]).replace("Z", "+00:00")
    )
    rows = db_session.execute(
        text(
            "SELECT concept, canonical_metric_key, value_kind, period_basis, known_at "
            "FROM sec_metric_mapping_registry "
            "WHERE mapping_version = 'sec-us-gaap-v2'"
        )
    ).mappings()

    assert {
        row["concept"]: (
            row["canonical_metric_key"],
            row["value_kind"],
            row["period_basis"],
            row["known_at"],
        )
        for row in rows
    } == {
        concept: (
            rule.metric_key,
            rule.value_kind,
            rule.period_basis,
            policy_known_at,
        )
        for concept, rule in rules.items()
    }


def test_sec_publication_is_canonical_traceable_fail_closed_and_idempotent(
    db_session,
) -> None:
    stock, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="PUB", cik="0000000042"
    )
    known_at = datetime(2026, 8, 27, 13, 0, tzinfo=timezone.utc)
    run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="d" * 64,
        status="succeeded",
        started_at=known_at,
        completed_at=known_at,
        known_at=known_at,
        fact_count=4,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=run.id,
            artifact_id=artifact.id,
            known_at=known_at,
        )
    )
    db_session.flush()
    db_session.add_all(
        [
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=1,
                concept="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
                raw_value="94,000",
                unit_measure="iso4217:USD",
                scale=6,
            ),
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=2,
                concept="us-gaap:EarningsPerShareDiluted",
                raw_value="1.50",
                unit_measure="iso4217:USD/xbrli:shares",
            ),
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=3,
                concept="issuer:InventedAdjustedEarnings",
                raw_value="999",
                unit_measure="iso4217:USD",
            ),
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=4,
                concept="us-gaap:Revenues",
                raw_value="12",
                unit_measure="iso4217:USD",
                dimensions={"us-gaap:StatementBusinessSegmentsAxis": "issuer:CloudMember"},
            ),
        ]
    )
    db_session.commit()
    cutoff = max(run.created_at, known_at) + timedelta(seconds=1)

    first = publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=cutoff,
        mapping_version="sec-us-gaap-v2",
    )
    second = publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=cutoff,
        mapping_version="sec-us-gaap-v2",
    )

    assert first.published_count == 2
    assert first.unresolved_count == 1
    assert first.rejected_count == 1
    assert second.created_count == 0
    facts = db_session.scalars(
        select(MetricFact)
        .where(MetricFact.stock_id == stock.id, MetricFact.source_type == "sec")
        .order_by(MetricFact.metric_key)
    ).all()
    assert [(row.metric_key, row.value_numeric) for row in facts] == [
        ("is.sales", 94_000_000_000.0),
        ("per_share.eps", 1.5),
    ]
    assert {row.metric_key: row.unit for row in facts} == {
        "is.sales": "USD",
        "per_share.eps": "USD_per_share",
    }
    assert all(row.user_id is None for row in facts)
    assert all(row.period_type == "Q" for row in facts)
    assert all(row.period_end_date == date(2026, 6, 30) for row in facts)
    for row in facts:
        assert row.value_json["fact_nature"] == "actual"
        assert row.value_json["source_role"] == "primary_as_filed"
        assert row.value_json["source_accession"] == filing.accession_no
        assert row.value_json["mapping_version"] == "sec-us-gaap-v2"
        assert row.value_json["raw_fact_id"] == row.source_ref_id
        assert row.value_json["locator"]["locator_type"] == "inline_xbrl_html"
        assert row.value_json["knowledge_at"]

    decisions = db_session.scalars(
        select(SecMetricPublication).order_by(SecMetricPublication.raw_fact_id)
    ).all()
    assert [row.status for row in decisions] == [
        "published",
        "published",
        "unresolved",
        "rejected",
    ]
    assert decisions[2].reason_code == "unmapped_concept"
    assert decisions[3].reason_code == "dimensions_not_supported"

    users = [User(email="sec-public-a@example.com"), User(email="sec-public-b@example.com")]
    db_session.add_all(users)
    db_session.commit()
    for user in users:
        visible = db_session.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock.id,
                MetricFact.is_current.is_(True),
                visible_metric_fact_predicate(
                    MetricFact,
                    user_id=user.id,
                ),
            )
        ).all()
        assert {row.metric_key for row in visible} == {"is.sales", "per_share.eps"}
        assert evidence_is_available(
            db_session,
            user_id=user.id,
            stock_id=stock.id,
            source_type="metric_fact",
            source_id=facts[0].id,
        ) is True

    case = ResearchCase(user_id=users[0].id, stock_id=stock.id, state="queued")
    db_session.add(case)
    db_session.commit()
    workspace = build_research_workspace(
        db_session,
        user_id=users[0].id,
        case_id=case.id,
        as_of=date.today(),
    )
    sales = next(
        item for item in workspace["fundamentals"]
        if item["metric_key"] == "is.sales"
    )
    provenance = sales["sec_provenance"]
    assert provenance["source_accession"] == filing.accession_no
    assert provenance["filing_form"] == filing.form_type
    assert provenance["artifact_id"] == artifact.id
    assert provenance["raw_fact_id"] == sales["source_ref_id"]
    assert provenance["parser_version"] == "inline-xbrl-v1"
    assert provenance["mapping_version"] == "sec-us-gaap-v2"
    assert provenance["knowledge_at"]
    assert provenance["context_id"] == "D2026Q2"
    assert provenance["dimensions_policy"] == "consolidated_only"
    assert provenance["dimensions"] == {}
    assert provenance["locator"]["locator_type"] == "inline_xbrl_html"

    reparsed_at = datetime.now(timezone.utc)
    reparsed_run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v2-drops-concepts",
        input_manifest_hash="7" * 64,
        status="succeeded",
        started_at=reparsed_at,
        completed_at=reparsed_at,
        known_at=reparsed_at,
        fact_count=1,
    )
    db_session.add(reparsed_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=reparsed_run.id,
            artifact_id=artifact.id,
            known_at=reparsed_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=reparsed_run.id,
            artifact_id=artifact.id,
            ordinal=1,
            concept="issuer:OnlyUnmappedConceptRemains",
            raw_value="1",
            unit_measure="iso4217:USD",
        )
    )
    db_session.commit()

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    assert db_session.scalars(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.source_type == "sec",
            MetricFact.is_current.is_(True),
        )
    ).all() == []


def test_sec_publication_rejects_mapping_not_known_at_cutoff(db_session) -> None:
    stock, _, _, _ = _database_lineage_fixture(
        db_session, ticker="MAPTIME", cik="0000000045"
    )
    with pytest.raises(SecFinancialIngestionError, match="mapping_not_known_at_cutoff"):
        publish_sec_metric_facts(
            db_session,
            stock_id=stock.id,
            cutoff=datetime(2026, 8, 27, 23, 59, tzinfo=timezone.utc),
            mapping_version="sec-us-gaap-v2",
        )


def test_sec_publication_rejects_currency_without_canonical_unit(db_session) -> None:
    stock, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="EURUNIT", cik="0000000047"
    )
    known_at = datetime.now(timezone.utc)
    run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="8" * 64,
        status="succeeded",
        started_at=known_at,
        completed_at=known_at,
        known_at=known_at,
        fact_count=1,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=run.id,
            artifact_id=artifact.id,
            known_at=known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=run.id,
            artifact_id=artifact.id,
            ordinal=1,
            concept="us-gaap:Revenues",
            raw_value="100",
            unit_measure="iso4217:EUR",
        )
    )
    db_session.commit()

    report = publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )

    assert report.published_count == 0
    assert report.rejected_count == 1
    publication = db_session.scalar(
        select(SecMetricPublication).where(
            SecMetricPublication.raw_fact_id.in_(
                select(SecRawXbrlFact.id).where(
                    SecRawXbrlFact.parse_run_id == run.id
                )
            )
        )
    )
    assert publication is not None
    assert publication.reason_code == "unsupported_currency"


def test_sec_publication_derives_discrete_quarter_only_from_same_cycle_ytd(
    db_session,
) -> None:
    stock, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="YTD", cik="0000000043"
    )
    known_at = datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc)
    run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="e" * 64,
        status="succeeded",
        started_at=known_at,
        completed_at=known_at,
        known_at=known_at,
        fact_count=2,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=run.id,
            artifact_id=artifact.id,
            known_at=known_at,
        )
    )
    db_session.flush()
    db_session.add_all(
        [
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=1,
                concept="us-gaap:Revenues",
                raw_value="600",
                unit_measure="iso4217:USD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30),
            ),
            _fact(
                run_id=run.id,
                artifact_id=artifact.id,
                ordinal=2,
                concept="us-gaap:Revenues",
                raw_value="1000",
                unit_measure="iso4217:USD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
            ),
        ]
    )
    db_session.commit()

    report = publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=max(run.created_at, known_at) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )

    assert report.created_count == 4
    assert report.published_count == 3
    assert report.rejected_count == 1
    quarter = db_session.scalar(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == date(2026, 9, 30),
            MetricFact.is_current.is_(True),
        )
    )
    assert quarter is not None
    assert quarter.value_numeric == 400.0
    assert quarter.value_json["derivation"] == "current_ytd_minus_prior_ytd"
    assert len(quarter.value_json["input_raw_fact_ids"]) == 2
    assert len(quarter.value_json["input_metric_fact_ids"]) == 2
    assert quarter.value_json["parser_version"] == "inline-xbrl-v1"
    assert quarter.value_json["context_id"] == "D2026Q2"
    assert quarter.value_json["dimensions_policy"] == "consolidated_only"
    assert quarter.value_json["dimensions"] == {}
    assert quarter.value_json["unit_measure"] == "iso4217:USD"
    assert quarter.value_json["decimals"] == "2"
    assert quarter.value_json["scale"] is None
    assert [
        item["metric_fact_id"] for item in quarter.value_json["input_provenance"]
    ] == quarter.value_json["input_metric_fact_ids"]
    assert [
        item["raw_fact_id"] for item in quarter.value_json["input_provenance"]
    ] == quarter.value_json["input_raw_fact_ids"]
    assert all(
        item["parser_version"] == "inline-xbrl-v1"
        for item in quarter.value_json["input_provenance"]
    )
    derived = db_session.scalars(
        select(SecMetricPublication)
        .where(SecMetricPublication.publication_role == "derived_discrete_quarter")
        .order_by(SecMetricPublication.raw_fact_id)
    ).all()
    assert [row.status for row in derived] == ["rejected", "published"]
    assert derived[0].reason_code == "prior_ytd_missing"

    reparsed_at = datetime.now(timezone.utc)
    reparsed_run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v2",
        input_manifest_hash="6" * 64,
        status="succeeded",
        started_at=reparsed_at,
        completed_at=reparsed_at,
        known_at=reparsed_at,
        fact_count=2,
    )
    db_session.add(reparsed_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=reparsed_run.id,
            artifact_id=artifact.id,
            known_at=reparsed_at,
        )
    )
    db_session.flush()
    db_session.add_all(
        [
            _fact(
                run_id=reparsed_run.id,
                artifact_id=artifact.id,
                ordinal=1,
                concept="us-gaap:Revenues",
                raw_value="700",
                unit_measure="iso4217:USD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 6, 30),
            ),
            _fact(
                run_id=reparsed_run.id,
                artifact_id=artifact.id,
                ordinal=2,
                concept="us-gaap:Revenues",
                raw_value="1200",
                unit_measure="iso4217:USD",
                period_start=date(2026, 1, 1),
                period_end=date(2026, 9, 30),
            ),
        ]
    )
    db_session.commit()

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    current_quarters = db_session.scalars(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == date(2026, 9, 30),
            MetricFact.is_current.is_(True),
        )
    ).all()
    assert len(current_quarters) == 1
    assert current_quarters[0].value_numeric == 500.0
    assert current_quarters[0].value_json["input_raw_fact_ids"][-1] in {
        raw.id
        for raw in db_session.scalars(
            select(SecRawXbrlFact).where(
                SecRawXbrlFact.parse_run_id == reparsed_run.id
            )
        )
    }


def test_sec_publication_does_not_assign_ten_q_period_semantics_to_six_k(
    db_session,
) -> None:
    stock, identity, _, _ = _database_lineage_fixture(
        db_session, ticker="SIXK", cik="0000000044"
    )
    known_at = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
    filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000000044-26-000002",
        form_type="6-K",
        is_amendment=False,
        filed_on=date(2026, 8, 1),
        report_date=date(2026, 6, 30),
        accepted_at=known_at,
        known_at=known_at,
        primary_document="six-k.htm",
        index_url="https://www.sec.gov/six-k/index.json",
        source_url="https://www.sec.gov/six-k/six-k.htm",
        submissions_source_url="https://data.sec.gov/submissions/CIK0000000044.json",
        discovery_payload_sha256="9" * 64,
    )
    db_session.add(filing)
    db_session.flush()
    artifact = SecFilingArtifact(
        filing_id=filing.id,
        sequence=1,
        filename="six-k.htm",
        source_url=filing.source_url,
        manifest_hash="8" * 64,
        state="retained",
        content_mime="text/html",
        sha256="7" * 64,
        byte_size=10,
        storage_key="financial/77/" + "7" * 64,
        fetched_at=known_at,
        known_at=known_at,
    )
    db_session.add(artifact)
    db_session.flush()
    run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="f" * 64,
        status="succeeded",
        started_at=known_at,
        completed_at=known_at,
        known_at=known_at,
        fact_count=1,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=run.id,
            artifact_id=artifact.id,
            known_at=known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=run.id,
            artifact_id=artifact.id,
            ordinal=1,
            concept="us-gaap:Revenues",
            raw_value="100",
            unit_measure="iso4217:USD",
        )
    )
    db_session.commit()

    report = publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=max(run.created_at, known_at) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )

    assert report.published_count == 0
    assert report.rejected_count == 1
    publication = db_session.scalar(
        select(SecMetricPublication).where(
            SecMetricPublication.raw_fact_id.in_(
                select(SecRawXbrlFact.id).where(
                    SecRawXbrlFact.parse_run_id == run.id
                )
            )
        )
    )
    assert publication is not None
    assert publication.reason_code == "unsupported_form_period"


def test_sec_publication_rederives_later_quarter_when_prior_ytd_is_amended(
    db_session,
) -> None:
    stock, identity, q2_filing, q2_artifact = _database_lineage_fixture(
        db_session, ticker="YTDAMD", cik="0000000048"
    )
    initial_known_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    q2_run = SecFinancialParseRun(
        filing_id=q2_filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="1" * 64,
        status="succeeded",
        started_at=initial_known_at,
        completed_at=initial_known_at,
        known_at=initial_known_at,
        fact_count=1,
    )
    db_session.add(q2_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=q2_run.id,
            artifact_id=q2_artifact.id,
            known_at=initial_known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=q2_run.id,
            artifact_id=q2_artifact.id,
            ordinal=1,
            concept="us-gaap:Revenues",
            raw_value="600",
            unit_measure="iso4217:USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
        )
    )

    q3_known_at = initial_known_at + timedelta(minutes=1)
    q3_filing = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000000048-26-000002",
        form_type="10-Q",
        is_amendment=False,
        filed_on=date(2026, 10, 30),
        report_date=date(2026, 9, 30),
        accepted_at=q3_known_at,
        known_at=q3_known_at,
        primary_document="q3.htm",
        index_url="https://www.sec.gov/ytd-amend/q3/index.json",
        source_url="https://www.sec.gov/ytd-amend/q3/q3.htm",
        submissions_source_url=q2_filing.submissions_source_url,
        discovery_payload_sha256="2" * 64,
    )
    db_session.add(q3_filing)
    db_session.flush()
    q3_artifact = SecFilingArtifact(
        filing_id=q3_filing.id,
        sequence=1,
        filename="q3.htm",
        source_url=q3_filing.source_url,
        manifest_hash="3" * 64,
        state="retained",
        content_mime="text/html",
        sha256="4" * 64,
        byte_size=10,
        storage_key="financial/48/" + "4" * 64,
        fetched_at=q3_known_at,
        known_at=q3_known_at,
    )
    db_session.add(q3_artifact)
    db_session.flush()
    q3_run = SecFinancialParseRun(
        filing_id=q3_filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="5" * 64,
        status="succeeded",
        started_at=q3_known_at,
        completed_at=q3_known_at,
        known_at=q3_known_at,
        fact_count=1,
    )
    db_session.add(q3_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=q3_run.id,
            artifact_id=q3_artifact.id,
            known_at=q3_known_at,
        )
    )
    db_session.flush()
    q3_raw = _fact(
        run_id=q3_run.id,
        artifact_id=q3_artifact.id,
        ordinal=1,
        concept="us-gaap:Revenues",
        raw_value="1000",
        unit_measure="iso4217:USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 9, 30),
    )
    db_session.add(q3_raw)
    db_session.commit()

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    original_q3 = db_session.scalar(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == date(2026, 9, 30),
            MetricFact.is_current.is_(True),
        )
    )
    assert original_q3 is not None
    assert original_q3.value_numeric == 400.0

    amendment_known_at = datetime.now(timezone.utc)
    amendment = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000000048-26-000003",
        form_type="10-Q/A",
        is_amendment=True,
        filed_on=amendment_known_at.date(),
        report_date=date(2026, 6, 30),
        accepted_at=amendment_known_at,
        known_at=amendment_known_at,
        primary_document="q2-amendment.htm",
        index_url="https://www.sec.gov/ytd-amend/q2a/index.json",
        source_url="https://www.sec.gov/ytd-amend/q2a/q2-amendment.htm",
        submissions_source_url=q2_filing.submissions_source_url,
        discovery_payload_sha256="6" * 64,
        amends_filing_id=q2_filing.id,
    )
    db_session.add(amendment)
    db_session.flush()
    amendment_artifact = SecFilingArtifact(
        filing_id=amendment.id,
        sequence=1,
        filename="q2-amendment.htm",
        source_url=amendment.source_url,
        manifest_hash="7" * 64,
        state="retained",
        content_mime="text/html",
        sha256="8" * 64,
        byte_size=10,
        storage_key="financial/48/" + "8" * 64,
        fetched_at=amendment_known_at,
        known_at=amendment_known_at,
    )
    db_session.add(amendment_artifact)
    db_session.flush()
    amendment_run = SecFinancialParseRun(
        filing_id=amendment.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="9" * 64,
        status="succeeded",
        started_at=amendment_known_at,
        completed_at=amendment_known_at,
        known_at=amendment_known_at,
        fact_count=1,
    )
    db_session.add(amendment_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=amendment_run.id,
            artifact_id=amendment_artifact.id,
            known_at=amendment_known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=amendment_run.id,
            artifact_id=amendment_artifact.id,
            ordinal=1,
            concept="us-gaap:Revenues",
            raw_value="700",
            unit_measure="iso4217:USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
        )
    )
    db_session.commit()

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )

    current_q3 = db_session.scalars(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == date(2026, 9, 30),
            MetricFact.is_current.is_(True),
        )
    ).all()
    assert len(current_q3) == 1
    assert current_q3[0].value_numeric == 300.0
    assert original_q3.is_current is False
    assert current_q3[0].value_json["input_metric_fact_ids"][0] != (
        original_q3.value_json["input_metric_fact_ids"][0]
    )
    assert datetime.fromisoformat(
        current_q3[0].value_json["knowledge_at"]
    ) >= amendment_known_at
    q3_derivations = db_session.scalars(
        select(SecMetricPublication).where(
            SecMetricPublication.raw_fact_id == q3_raw.id,
            SecMetricPublication.publication_role == "derived_discrete_quarter",
            SecMetricPublication.status == "published",
        )
    ).all()
    assert len(q3_derivations) == 2
    assert len({row.derivation_key for row in q3_derivations}) == 2

    omission_known_at = datetime.now(timezone.utc)
    omission_run = SecFinancialParseRun(
        filing_id=amendment.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v2-omits-prior-ytd",
        input_manifest_hash="a" * 64,
        status="succeeded",
        started_at=omission_known_at,
        completed_at=omission_known_at,
        known_at=omission_known_at,
        fact_count=1,
    )
    db_session.add(omission_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=omission_run.id,
            artifact_id=amendment_artifact.id,
            known_at=omission_known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=omission_run.id,
            artifact_id=amendment_artifact.id,
            ordinal=1,
            concept="issuer:OnlyUnmappedConceptRemains",
            raw_value="1",
            unit_measure="iso4217:USD",
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
        )
    )
    db_session.commit()

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    db_session.expire_all()

    assert db_session.scalars(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == date(2026, 9, 30),
            MetricFact.is_current.is_(True),
        )
    ).all() == []
    assert db_session.get(MetricFact, current_q3[0].id).is_current is False
    rejected = db_session.scalars(
        select(SecMetricPublication).where(
            SecMetricPublication.raw_fact_id == q3_raw.id,
            SecMetricPublication.publication_role == "derived_discrete_quarter",
            SecMetricPublication.status == "rejected",
            SecMetricPublication.reason_code == "prior_ytd_missing",
        )
    ).all()
    assert rejected


def test_sec_derived_fact_rejects_non_sec_input_lineage(db_session) -> None:
    stock, _, filing, artifact = _database_lineage_fixture(
        db_session, ticker="BADDER", cik="0000000143"
    )
    known_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="b" * 64,
        status="succeeded",
        started_at=known_at,
        completed_at=known_at,
        known_at=known_at,
        fact_count=1,
    )
    db_session.add(run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=run.id,
            artifact_id=artifact.id,
            known_at=known_at,
        )
    )
    current_raw = _fact(
        run_id=run.id,
        artifact_id=artifact.id,
        ordinal=1,
        concept="us-gaap:Revenues",
        raw_value="1000",
        unit_measure="iso4217:USD",
        period_start=date(2026, 1, 1),
        period_end=date(2026, 9, 30),
    )
    db_session.add(current_raw)
    db_session.commit()
    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    current_ytd = db_session.scalar(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.source_type == "sec",
            MetricFact.source_ref_id == current_raw.id,
            MetricFact.period_type == "YTD",
        )
    )
    assert current_ytd is not None
    attacker = User(email="derived-lineage-attacker@example.com")
    db_session.add(attacker)
    db_session.flush()
    attacker_document = PdfDocument(
        user_id=attacker.id,
        stock_id=stock.id,
        file_name="attacker-inputs.pdf",
        source="upload",
        file_storage_key="tests/sec-derived/attacker-inputs.pdf",
        parse_status="parsed",
    )
    db_session.add(attacker_document)
    db_session.flush()
    prior_extraction = MetricExtraction(
        user_id=attacker.id,
        document_id=attacker_document.id,
        page_number=1,
        field_key="is.sales.prior_ytd",
        raw_value_text="90",
        original_text_snippet="Prior YTD sales 90",
        parsed_value_json={"value": 90},
        parser_version="test-v1",
        parse_generation=attacker_document.current_parse_generation,
    )
    current_extraction = MetricExtraction(
        user_id=attacker.id,
        document_id=attacker_document.id,
        page_number=1,
        field_key="is.sales.current_ytd",
        raw_value_text="100",
        original_text_snippet="Current YTD sales 100",
        parsed_value_json={"value": 100},
        parser_version="test-v1",
        parse_generation=attacker_document.current_parse_generation,
    )
    db_session.add_all([prior_extraction, current_extraction])
    db_session.flush()
    manual_prior = MetricFact(
        user_id=attacker.id,
        stock_id=stock.id,
        metric_key="is.sales",
        value_numeric=90,
        value_json={"period_start": "2026-01-01"},
        unit="USD",
        currency="USD",
        period_type="YTD",
        period_end_date=date(2026, 6, 30),
        source_type="parsed",
        source_document_id=attacker_document.id,
        source_ref_id=prior_extraction.id,
        parse_generation=attacker_document.current_parse_generation,
        is_current=True,
    )
    manual_current = MetricFact(
        user_id=attacker.id,
        stock_id=stock.id,
        metric_key="is.sales",
        value_numeric=100,
        value_json={"period_start": "2026-01-01"},
        unit="USD",
        currency="USD",
        period_type="YTD",
        period_end_date=date(2026, 9, 30),
        source_type="parsed",
        source_document_id=attacker_document.id,
        source_ref_id=current_extraction.id,
        parse_generation=attacker_document.current_parse_generation,
        is_current=True,
    )
    db_session.add_all([manual_prior, manual_current])
    db_session.flush()
    forged_value_json = dict(current_ytd.value_json)
    forged_value_json.update(
        {
            "value_basis": "derived_discrete_quarter",
            "derivation": "current_ytd_minus_prior_ytd",
            "period_start": "2026-07-01",
            "input_metric_fact_ids": [manual_prior.id, manual_current.id],
            "input_raw_fact_ids": [manual_prior.source_ref_id, current_raw.id],
            "input_provenance": [{"forged": True}, {"forged": True}],
        }
    )
    forged = MetricFact(
        user_id=None,
        stock_id=stock.id,
        metric_key="is.sales",
        value_numeric=10,
        value_json=forged_value_json,
        unit="USD",
        currency="USD",
        period_type="Q",
        period_end_date=date(2026, 9, 30),
        as_of_date=known_at.date(),
        source_type="sec",
        source_ref_id=current_raw.id,
        is_current=True,
    )
    db_session.add(forged)
    db_session.flush()
    db_session.add(
        SecMetricPublication(
            raw_fact_id=current_raw.id,
            metric_fact_id=forged.id,
            mapping_version="sec-us-gaap-v2",
            publication_role="derived_discrete_quarter",
            derivation_key="f" * 64,
            status="published",
            canonical_metric_key="is.sales",
            canonical_unit="USD",
            period_type="Q",
            period_end_date=date(2026, 9, 30),
            knowledge_at=datetime.fromisoformat(
                current_ytd.value_json["knowledge_at"]
            ),
            decision_json={"filing_id": filing.id, "parse_run_id": run.id},
        )
    )

    with pytest.raises(DBAPIError, match="published direct input lineage"):
        db_session.flush()
        # The shared test session is wrapped in an outer transaction, so force
        # the deferred production-commit check at this boundary.
        db_session.execute(
            text(
                "SET CONSTRAINTS "
                "trg_metric_facts_sec_derived_input_lineage IMMEDIATE"
            )
        )
    db_session.rollback()


def test_sec_publication_uses_current_amendment_and_cannot_regress_to_historical_cutoff(
    db_session,
) -> None:
    stock, identity, filing, artifact = _database_lineage_fixture(
        db_session, ticker="AMEND", cik="0000000046"
    )
    now = datetime.now(timezone.utc)
    original_known_at = now - timedelta(minutes=20)
    original_run = SecFinancialParseRun(
        filing_id=filing.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="1" * 64,
        status="succeeded",
        started_at=original_known_at,
        completed_at=original_known_at,
        known_at=original_known_at,
        fact_count=1,
    )
    db_session.add(original_run)
    db_session.flush()
    original_link = SecFinancialParseRunArtifact(
        parse_run_id=original_run.id,
        artifact_id=artifact.id,
        known_at=original_known_at,
    )
    db_session.add(original_link)
    db_session.flush()
    original_raw = _fact(
        run_id=original_run.id,
        artifact_id=artifact.id,
        ordinal=1,
        concept="us-gaap:Revenues",
        raw_value="100",
        unit_measure="iso4217:USD",
    )
    db_session.add(original_raw)
    db_session.commit()
    db_session.refresh(original_run)
    db_session.refresh(original_link)
    db_session.refresh(original_raw)
    stale_cutoff = max(
        original_run.created_at,
        original_link.created_at,
        original_raw.created_at,
    ) + timedelta(microseconds=1)
    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=stale_cutoff,
        mapping_version="sec-us-gaap-v2",
    )

    amendment_known_at = stale_cutoff + timedelta(microseconds=1)
    amendment = SecFinancialFiling(
        issuer_identity_id=identity.id,
        accession_no="0000000046-26-000002",
        form_type="10-Q/A",
        is_amendment=True,
        filed_on=now.date(),
        report_date=filing.report_date,
        accepted_at=amendment_known_at,
        known_at=amendment_known_at,
        primary_document="amendment.htm",
        index_url="https://www.sec.gov/amendment/index.json",
        source_url="https://www.sec.gov/amendment/amendment.htm",
        submissions_source_url=filing.submissions_source_url,
        discovery_payload_sha256="2" * 64,
        amends_filing_id=filing.id,
    )
    db_session.add(amendment)
    db_session.flush()
    amendment_artifact = SecFilingArtifact(
        filing_id=amendment.id,
        sequence=1,
        filename="amendment.htm",
        source_url=amendment.source_url,
        manifest_hash="3" * 64,
        state="retained",
        content_mime="text/html",
        sha256="4" * 64,
        byte_size=10,
        storage_key="financial/44/" + "4" * 64,
        fetched_at=amendment_known_at,
        known_at=amendment_known_at,
    )
    db_session.add(amendment_artifact)
    db_session.flush()
    amendment_run = SecFinancialParseRun(
        filing_id=amendment.id,
        parser_name="fixture",
        parser_version="inline-xbrl-v1",
        input_manifest_hash="5" * 64,
        status="succeeded",
        started_at=amendment_known_at,
        completed_at=amendment_known_at,
        known_at=amendment_known_at,
        fact_count=1,
    )
    db_session.add(amendment_run)
    db_session.flush()
    db_session.add(
        SecFinancialParseRunArtifact(
            parse_run_id=amendment_run.id,
            artifact_id=amendment_artifact.id,
            known_at=amendment_known_at,
        )
    )
    db_session.flush()
    db_session.add(
        _fact(
            run_id=amendment_run.id,
            artifact_id=amendment_artifact.id,
            ordinal=1,
            concept="us-gaap:Revenues",
            raw_value="120",
            unit_measure="iso4217:USD",
        )
    )
    db_session.commit()

    with pytest.raises(
        SecFinancialIngestionError, match="historical_publication_not_allowed"
    ):
        publish_sec_metric_facts(
            db_session,
            stock_id=stock.id,
            cutoff=stale_cutoff,
            mapping_version="sec-us-gaap-v2",
        )

    publish_sec_metric_facts(
        db_session,
        stock_id=stock.id,
        cutoff=datetime.now(timezone.utc) + timedelta(seconds=1),
        mapping_version="sec-us-gaap-v2",
    )
    current = db_session.scalar(
        select(MetricFact).where(
            MetricFact.stock_id == stock.id,
            MetricFact.metric_key == "is.sales",
            MetricFact.period_type == "Q",
            MetricFact.period_end_date == filing.report_date,
            MetricFact.is_current.is_(True),
        )
    )
    assert current is not None
    assert current.value_numeric == 120.0
    assert current.value_json["source_accession"] == amendment.accession_no
