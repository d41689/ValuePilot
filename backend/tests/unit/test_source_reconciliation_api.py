from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.artifacts import PdfDocument, ValueLineParseRun
from app.models.facts import Formula, MetricFact
from app.models.stocks import Stock
from app.services.formula_engine import FormulaEngine
from app.services.ingestion_service import IngestionService
from app.services.dcf_inputs import load_canonical_dcf_fact_universe
from app.services.manual_metric_correction import (
    ManualMetricCorrectionError,
    create_manual_metric_correction,
)
from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    build_source_reconciliation_report_from_facts,
    guard_reconciled_source_selection,
)
from app.services import source_reconciliation
from app.services.canonical_financials import CanonicalSourceConflictError


def _document(*, user_id: int, stock_id: int, suffix: str = "") -> PdfDocument:
    return PdfDocument(
        user_id=user_id,
        stock_id=stock_id,
        file_name=f"report{suffix}.pdf",
        source="value_line",
        file_storage_key=f"private/storage/report{suffix}.pdf",
        report_date=date(2026, 1, 9),
        parse_status="parsed",
        parser_version="value-line-v1",
        identity_needs_review=False,
    )


def _parsed_fact(
    *,
    user_id: int,
    stock_id: int,
    document_id: int,
    metric_key: str = "is.net_income",
    value: int = 100,
) -> MetricFact:
    return MetricFact(
        user_id=user_id,
        stock_id=stock_id,
        metric_key=metric_key,
        value_numeric=value,
        value_json={
            "fact_nature": "actual",
            "mapping_id": "is.net_income.fy",
            "source_mapping_version": "value-line-spec-v2",
            "definition_basis": "adjusted",
            "period_start_date": "2025-01-01",
            "duration_days": 365,
            "fiscal_year": 2025,
            "dimensions_identity": "empty",
        },
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="parsed",
        source_document_id=document_id,
        is_current=True,
    )


def _assert_safe(value):
    if isinstance(value, dict):
        forbidden = {
            "file_storage_key",
            "storage_key",
            "storage_path",
            "raw_text",
            "original_text_snippet",
        }
        assert not (forbidden & set(value))
        for nested in value.values():
            _assert_safe(nested)
    elif isinstance(value, list):
        for nested in value:
            _assert_safe(nested)
    elif isinstance(value, str):
        assert "private/storage" not in value
        assert not value.startswith("file://")


def test_authenticated_reconciliation_is_tenant_safe_and_bounded(
    client, db_session, user_factory, auth_headers
):
    owner = user_factory("reconcile-owner@example.com")
    other = user_factory("reconcile-other@example.com")
    stock = Stock(ticker="RECON", exchange="NYSE", company_name="Reconcile Co")
    db_session.add(stock)
    db_session.flush()
    owner_doc = _document(user_id=owner.id, stock_id=stock.id)
    other_doc = _document(user_id=other.id, stock_id=stock.id, suffix="-other")
    db_session.add_all([owner_doc, other_doc])
    db_session.flush()
    owner_fact = _parsed_fact(
        user_id=owner.id,
        stock_id=stock.id,
        document_id=owner_doc.id,
    )
    other_fact = _parsed_fact(
        user_id=other.id,
        stock_id=stock.id,
        document_id=other_doc.id,
        value=999,
    )
    owner_run = ValueLineParseRun(
        user_id=owner.id,
        document_id=owner_doc.id,
        parser_version="value-line-v1",
        source_mapping_version=IngestionService(
            db_session
        ).mapping_spec.source_mapping_version,
        status="running",
    )
    db_session.add(owner_run)
    db_session.flush()
    owner_fact.value_line_parse_run_id = owner_run.id
    db_session.add_all([owner_fact, other_fact])
    db_session.flush()
    owner_run.status = "succeeded"
    db_session.flush()
    manual = MetricFact(
        user_id=owner.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=95,
        value_json={
            "fact_nature": "manual",
            "corrects_fact_id": owner_fact.id,
            "definition_basis": "adjusted",
            "period_start_date": "2025-01-01",
            "duration_days": 365,
            "fiscal_year": 2025,
            "dimensions_identity": "empty",
        },
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add(manual)
    db_session.commit()

    response = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(owner),
        params=[("metric_key", "is.net_income")],
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["point_in_time_status"] == "verified_from_available_authority"
    assert payload["status"] == "complete"
    assert payload["policy_version"] == "financial-source-reconciliation-v1"
    assert payload["requesting_user_id"] == owner.id
    assert payload["canonical_definition_version"] == (
        "canonical-financial-definitions-v1"
    )
    assert len(payload["mapping_policy_sha256"]) == 64
    assert payload["eligible_fact_ids"] == [owner_fact.id, manual.id]
    returned_fact_ids = {
        candidate["fact_id"]
        for item in payload["items"]
        for candidate in item["inputs"]
    } | {row["fact_id"] for row in payload["excluded"]}
    assert other_fact.id not in returned_fact_ids
    assert payload["items"][0]["status"] == "expected_definition_difference"
    assert payload["items"][0]["reason_code"] == "explicit_manual_correction"
    _assert_safe(payload)

    facts_response = client.get(
        f"/api/v1/stocks/{stock.id}/facts",
        headers=auth_headers(owner),
    )
    assert facts_response.status_code == 200, facts_response.text
    facts_payload = facts_response.json()
    assert not any(
        row.get("status") == "published" and row.get("metric_key") == "is.net_income"
        for row in facts_payload
    )
    blocked = next(
        row
        for row in facts_payload
        if row.get("metric_key") == "is.net_income"
        and row.get("status") == "unavailable"
    )
    assert blocked["reason_code"] == "source_conflict"
    assert blocked["source_types"] == ["manual", "parsed"]

    anonymous = client.get(f"/api/v1/stocks/{stock.id}/source-reconciliation")
    assert anonymous.status_code == 401
    too_many = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(owner),
        params=[("metric_key", f"metric.{index}") for index in range(51)],
    )
    assert too_many.status_code == 422
    invalid_key = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(owner),
        params=[("metric_key", "is.net_income;drop")],
    )
    assert invalid_key.status_code == 422


def test_deployed_mapping_must_match_database_approved_policy(
    db_session, user_factory, monkeypatch
):
    user = user_factory("reconcile-policy-drift@example.com")
    stock = Stock(ticker="RDRIFT", exchange="NYSE", company_name="Policy Drift")
    db_session.add(stock)
    db_session.flush()
    fact = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="is.net_income",
        value_numeric=100,
        value_json={"fact_nature": "manual"},
        unit="USD",
        currency="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="manual",
        is_current=True,
    )
    db_session.add(fact)
    db_session.flush()
    deployed = source_reconciliation._resolved_mapping_spec()
    unapproved_digest = "0" * 64
    monkeypatch.setattr(
        source_reconciliation,
        "_resolved_mapping_spec",
        lambda: SimpleNamespace(
            spec=deployed.spec,
            mapping_policy_sha256=unapproved_digest,
            source_mapping_version=f"value-line-resolved-v2:{unapproved_digest}",
        ),
    )
    cutoff = datetime.now(timezone.utc)

    report = build_source_reconciliation_report_from_facts(
        db_session,
        facts=[fact],
        user_id=user.id,
        stock_id=stock.id,
        knowledge_cutoff=cutoff,
    )

    assert report["status"] == "unavailable"
    assert report["consumer_gate_status"] == "blocked"
    assert report["reason_code"] == "unapproved_deployed_mapping_policy"
    assert report["mapping_policy_sha256"] is None
    assert report["eligible_fact_ids"] == []
    with pytest.raises(CanonicalReconciliationError) as error:
        guard_reconciled_source_selection(
            [fact],
            consumer="policy-drift-test",
            knowledge_cutoff=cutoff,
            session=db_session,
            user_id=user.id,
        )
    assert error.value.blocking_items[0]["reason_code"] == "mapping_policy_unavailable"


def test_reconciliation_mapping_resolution_observes_warm_process_policy_drift(
    monkeypatch,
):
    """A warm worker must not retain an approved policy after files change."""

    resolver = source_reconciliation._resolved_mapping_spec
    clear_cache = getattr(resolver, "cache_clear", None)
    if clear_cache is not None:
        clear_cache()
    approved = SimpleNamespace(mapping_policy_sha256="a" * 64)
    drifted = SimpleNamespace(mapping_policy_sha256="b" * 64)
    calls = iter((approved, drifted))
    monkeypatch.setattr(
        source_reconciliation.MappingSpec,
        "load",
        lambda *_args, **_kwargs: next(calls),
    )
    try:
        assert resolver().mapping_policy_sha256 == "a" * 64
        assert resolver().mapping_policy_sha256 == "b" * 64
    finally:
        if clear_cache is not None:
            clear_cache()


def test_ingested_owner_earnings_becomes_unavailable_when_input_is_superseded(
    db_session, user_factory
):
    user = user_factory("owner-earnings-lineage@example.com")
    stock = Stock(ticker="OEL", exchange="NYSE", company_name="Owner Earnings Lineage")
    db_session.add(stock)
    db_session.flush()
    document = _document(user_id=user.id, stock_id=stock.id, suffix="-oe")
    db_session.add(document)
    db_session.flush()
    inputs = [
        _parsed_fact(
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            metric_key="per_share.eps",
            value=5,
        ),
        _parsed_fact(
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            metric_key="per_share.capital_spending",
            value=2,
        ),
        _parsed_fact(
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            metric_key="is.depreciation",
            value=10,
        ),
        _parsed_fact(
            user_id=user.id,
            stock_id=stock.id,
            document_id=document.id,
            metric_key="equity.shares_outstanding",
            value=20,
        ),
    ]
    for monetary_input in inputs[:3]:
        monetary_input.currency = "USD"
    inputs[-1].unit = "shares"
    inputs[-1].currency = None
    db_session.add_all(inputs)
    db_session.flush()

    created = IngestionService(db_session)._persist_owner_earnings_facts(
        user_id=user.id,
        stock_id=stock.id,
        report_date=date(2026, 1, 9),
    )
    oeps = next(fact for fact in created if fact.metric_key == "owners_earnings_per_share")
    assert oeps.source_type == "calculated"
    assert {row["fact_id"] for row in oeps.value_json["inputs"]} == {
        fact.id for fact in inputs
    }

    inputs[0].is_current = False
    db_session.flush()
    replacement = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        metric_key="per_share.eps",
        value=6,
    )
    db_session.add(replacement)
    db_session.flush()

    with pytest.raises(CanonicalReconciliationError) as error:
        load_canonical_dcf_fact_universe(
            db_session,
            stock_id=stock.id,
            user_id=user.id,
            evaluated_at=datetime.now(timezone.utc) + timedelta(seconds=1),
            effective_as_of=date(2026, 1, 9),
        )
    assert {
        item["reason_code"] for item in error.value.blocking_items
    } == {"derived_lineage_superseded"}


def test_failed_correction_validation_cannot_demote_current_manual_fact(
    db_session, user_factory
):
    user = user_factory("correction-atomicity@example.com")
    stock = Stock(ticker="MCAT", exchange="NYSE", company_name="Manual Atomicity")
    db_session.add(stock)
    db_session.flush()
    document = _document(user_id=user.id, stock_id=stock.id, suffix="-manual")
    db_session.add(document)
    db_session.flush()
    parsed = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
    )
    current_manual = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key=parsed.metric_key,
        value_numeric=101,
        value_json={
            "correction": True,
            "corrected_from_fact_id": 123,
            "source_fact_id": 123,
            "source_extraction_id": 456,
        },
        unit="USD",
        currency="USD",
        period_type=parsed.period_type,
        period_end_date=parsed.period_end_date,
        source_type="manual",
        is_current=True,
    )
    db_session.add_all([parsed, current_manual])
    db_session.flush()
    manual_id = current_manual.id

    with pytest.raises(ManualMetricCorrectionError) as error:
        create_manual_metric_correction(
            db_session,
            user_id=user.id,
            source_fact=parsed,
            raw_value="102",
        )
    assert error.value.code == "correction_lineage_unavailable"

    # A non-HTTP caller may catch the typed validation error and commit other
    # work. Validation must therefore be side-effect free without relying on
    # endpoint rollback behavior.
    db_session.commit()
    db_session.expire_all()
    assert db_session.get(MetricFact, manual_id).is_current is True


def test_reconciliation_excludes_post_cutoff_and_revoked_source_authority(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("reconcile-cutoff@example.com")
    stock = Stock(ticker="RCUT", exchange="NYSE", company_name="Cutoff Co")
    db_session.add(stock)
    db_session.flush()
    valid_doc = _document(user_id=user.id, stock_id=stock.id)
    revoked_doc = _document(user_id=user.id, stock_id=stock.id, suffix="-revoked")
    revoked_doc.parse_status = "failed"
    db_session.add_all([valid_doc, revoked_doc])
    db_session.flush()
    mapping_version = IngestionService(
        db_session
    ).mapping_spec.source_mapping_version
    valid_run = ValueLineParseRun(
        user_id=user.id,
        document_id=valid_doc.id,
        parser_version="value-line-v1",
        source_mapping_version=mapping_version,
        status="running",
    )
    revoked_run = ValueLineParseRun(
        user_id=user.id,
        document_id=revoked_doc.id,
        parser_version="value-line-v1",
        source_mapping_version=mapping_version,
        status="running",
    )
    db_session.add_all([valid_run, revoked_run])
    db_session.flush()
    valid = _parsed_fact(
        user_id=user.id, stock_id=stock.id, document_id=valid_doc.id
    )
    post_cutoff = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=valid_doc.id,
        metric_key="bs.total_assets",
    )
    revoked = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=revoked_doc.id,
        metric_key="bs.total_equity",
    )
    retired = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=valid_doc.id,
        metric_key="bs.total_liabilities",
    )
    retired.value_json = {**retired.value_json, "authorization_state": "retired"}
    valid.value_line_parse_run_id = valid_run.id
    post_cutoff.value_line_parse_run_id = valid_run.id
    retired.value_line_parse_run_id = valid_run.id
    revoked.value_line_parse_run_id = revoked_run.id
    future_known_at = datetime.now(timezone.utc) + timedelta(hours=1)
    post_cutoff.created_at = future_known_at
    post_cutoff.updated_at = future_known_at
    db_session.add_all([valid, post_cutoff, revoked, retired])
    db_session.flush()
    valid_run.status = "succeeded"
    revoked_run.status = "succeeded"
    db_session.flush()
    cutoff = datetime.now(timezone.utc)
    db_session.commit()

    response = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(user),
        params={"knowledge_cutoff": cutoff.isoformat()},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["point_in_time_status"] == "historical_current_projection_unverifiable"
    assert payload["status"] == "partial"
    assert payload["consumer_gate_status"] == "blocked"
    assert valid.id in payload["eligible_fact_ids"]
    reasons = {row["fact_id"]: row["reason_code"] for row in payload["excluded"]}
    assert reasons[post_cutoff.id] == "fact_known_after_cutoff"
    assert reasons[revoked.id] == "source_unauthorized"
    assert reasons[retired.id] == "source_retired"

    future = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(user),
        params={
            "knowledge_cutoff": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat()
        },
    )
    assert future.status_code == 422
    assert future.json()["detail"]["code"] == "future_knowledge_cutoff"


def test_formula_selected_source_cannot_bypass_missing_derived_lineage(
    db_session, user_factory
):
    user = user_factory("reconcile-formula@example.com")
    stock = Stock(ticker="RFML", exchange="NYSE", company_name="Formula Guard Co")
    db_session.add(stock)
    db_session.flush()
    document = _document(user_id=user.id, stock_id=stock.id)
    db_session.add(document)
    db_session.flush()
    parsed = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        metric_key="input_metric",
    )
    calculated = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="input_metric",
        value_numeric=130,
        value_json={
            "fact_nature": "derived_actual",
            "calculation_version": "test-v1",
            "period_start_date": "2025-01-01",
            "duration_days": 365,
            "dimensions_identity": "empty",
        },
        unit="USD",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="calculated",
        is_current=True,
    )
    formula = Formula(
        user_id=user.id,
        name="Guarded result",
        expression="input_metric + 1",
        dependencies_json=["input_metric"],
    )
    db_session.add_all([parsed, calculated, formula])
    db_session.commit()

    with pytest.raises(CanonicalReconciliationError) as raised:
        FormulaEngine(db_session).run_formula(
            formula.id,
            stock.id,
            user.id,
            selected_source_type="parsed",
        )

    assert raised.value.blocking_items[0]["reason_code"] == "derived_lineage_unavailable"


def test_formula_persists_exact_input_lineage_for_replay(db_session, user_factory):
    user = user_factory("reconcile-formula-lineage@example.com")
    stock = Stock(ticker="RLIN", exchange="NYSE", company_name="Lineage Co")
    db_session.add(stock)
    db_session.flush()
    source = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="source_metric",
        value_numeric=10,
        value_json={
            "fact_nature": "manual",
            "manual_role": "original_input",
        },
        source_type="manual",
        is_current=True,
    )
    formula = Formula(
        user_id=user.id,
        name="Lineage result",
        expression="source_metric + 1",
        dependencies_json=["source_metric"],
    )
    db_session.add_all([source, formula])
    db_session.commit()

    run = FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)

    output = db_session.query(MetricFact).filter_by(source_ref_id=run.id).one()
    assert output.value_json["fact_nature"] == "derived_actual"
    assert output.value_json["calculation_version"] == "formula-engine-v1"
    assert output.value_json["inputs"] == [
        {
            "fact_id": source.id,
            "metric_key": "source_metric",
            "source_type": "manual",
        }
    ]


def test_later_same_slot_competitor_invalidates_preexisting_calculated_output(
    db_session, user_factory
):
    baseline_known_at = datetime.now(timezone.utc) - timedelta(minutes=2)
    competing_known_at = baseline_known_at + timedelta(minutes=1)
    historical_cutoff = baseline_known_at + timedelta(seconds=30)
    user = user_factory("reconcile-late-competitor@example.com")
    stock = Stock(ticker="RLATE", exchange="NYSE", company_name="Late Source Co")
    db_session.add(stock)
    db_session.flush()
    document = _document(user_id=user.id, stock_id=stock.id)
    document.upload_time = baseline_known_at
    db_session.add(document)
    db_session.flush()
    original = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=document.id,
        metric_key="is.net_income",
        value=100,
    )
    original.created_at = baseline_known_at
    original.updated_at = baseline_known_at
    db_session.add(original)
    db_session.flush()
    output = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="score.piotroski.total",
        value_numeric=7,
        value_json={
            "fact_nature": "derived_actual",
            "calculation_version": "piotroski-v1",
            "definition_basis": "derived",
            "period_start_date": "2025-01-01",
            "duration_days": 365,
            "fiscal_year": 2025,
            "dimensions_identity": "empty",
            "inputs": [{"fact_id": original.id, "metric_key": original.metric_key}],
        },
        unit="score",
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type="calculated",
        is_current=True,
        created_at=baseline_known_at,
        updated_at=baseline_known_at,
    )
    db_session.add(output)
    db_session.commit()

    assert guard_reconciled_source_selection(
        [output],
        consumer="stock_pool_piotroski_display",
        knowledge_cutoff=datetime.now(timezone.utc),
        session=db_session,
        user_id=user.id,
    ) == [output]

    competing_document = _document(
        user_id=user.id, stock_id=stock.id, suffix="-late"
    )
    competing_document.upload_time = competing_known_at
    db_session.add(competing_document)
    db_session.flush()
    competing = _parsed_fact(
        user_id=user.id,
        stock_id=stock.id,
        document_id=competing_document.id,
        metric_key="is.net_income",
        value=140,
    )
    competing.value_json = {
        **competing.value_json,
        "mapping_id": "is.net_income.alternate",
    }
    competing.created_at = competing_known_at
    competing.updated_at = competing_known_at
    db_session.add(competing)
    db_session.commit()

    try:
        historical_selection = guard_reconciled_source_selection(
            [output],
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=historical_cutoff,
            session=db_session,
            user_id=user.id,
        )
    except CanonicalReconciliationError as exc:
        pytest.fail(
            "historical selection unexpectedly blocked: "
            f"{exc.blocking_items}"
        )
    assert historical_selection == [output]

    with pytest.raises(CanonicalSourceConflictError):
        guard_reconciled_source_selection(
            [output],
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=datetime.now(timezone.utc),
            session=db_session,
            user_id=user.id,
        )

    original.is_current = False
    db_session.commit()
    with pytest.raises(CanonicalReconciliationError) as exc_info:
        guard_reconciled_source_selection(
            [output],
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=datetime.now(timezone.utc),
            session=db_session,
            user_id=user.id,
        )
    assert {
        item["reason_code"] for item in exc_info.value.blocking_items
    } == {"derived_lineage_superseded"}


def test_formula_never_overwrites_periods_in_dependency_dictionary(
    db_session, user_factory
):
    user = user_factory("reconcile-formula-periods@example.com")
    stock = Stock(ticker="RPER", exchange="NYSE", company_name="Period Guard Co")
    db_session.add(stock)
    db_session.flush()
    facts = [
        MetricFact(
            user_id=user.id,
            stock_id=stock.id,
            metric_key="period_metric",
            value_numeric=value,
            value_json={
                "fact_nature": "manual",
                "manual_role": "original_input",
            },
            unit="USD",
            period_type="FY",
            period_end_date=period_end,
            source_type="manual",
            is_current=True,
        )
        for value, period_end in (
            (10, date(2024, 12, 31)),
            (99, date(2025, 12, 31)),
        )
    ]
    formula = Formula(
        user_id=user.id,
        name="No overwrite",
        expression="period_metric + 1",
        dependencies_json=["period_metric"],
    )
    db_session.add_all([*facts, formula])
    db_session.commit()

    with pytest.raises(CanonicalReconciliationError) as raised:
        FormulaEngine(db_session).run_formula(formula.id, stock.id, user.id)

    assert (
        raised.value.blocking_items[0]["reason_code"]
        == "formula_period_selection_required"
    )


def test_consumer_guard_rejects_cyclic_and_cross_stock_derived_lineage(
    db_session, user_factory
):
    user = user_factory("reconcile-lineage-boundary@example.com")
    stocks = [
        Stock(ticker="RLCA", exchange="NYSE", company_name="Lineage A"),
        Stock(ticker="RLCB", exchange="NYSE", company_name="Lineage B"),
    ]
    db_session.add_all(stocks)
    db_session.flush()
    first = MetricFact(
        user_id=user.id,
        stock_id=stocks[0].id,
        metric_key="derived.first",
        value_numeric=1,
        value_json={
            "fact_nature": "derived_actual",
            "calculation_version": "test-v1",
            "inputs": [],
        },
        source_type="calculated",
        is_current=True,
    )
    second = MetricFact(
        user_id=user.id,
        stock_id=stocks[0].id,
        metric_key="derived.second",
        value_numeric=2,
        value_json={
            "fact_nature": "derived_actual",
            "calculation_version": "test-v1",
            "inputs": [],
        },
        source_type="calculated",
        is_current=True,
    )
    foreign = MetricFact(
        user_id=user.id,
        stock_id=stocks[1].id,
        metric_key="input.foreign",
        value_numeric=3,
        value_json={"manual_role": "original_input"},
        source_type="manual",
        is_current=True,
    )
    db_session.add_all([first, second, foreign])
    db_session.flush()
    first.value_json = {
        **first.value_json,
        "inputs": [{"fact_id": second.id}],
    }
    second.value_json = {
        **second.value_json,
        "inputs": [{"fact_id": first.id}],
    }
    db_session.commit()

    with pytest.raises(CanonicalReconciliationError) as cycle:
        guard_reconciled_source_selection(
            [first],
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=datetime.now(timezone.utc),
            session=db_session,
            user_id=user.id,
        )
    assert cycle.value.blocking_items[0]["reason_code"] == (
        "lineage_cycle_detected"
    )

    first.value_json = {
        **first.value_json,
        "inputs": [{"fact_id": foreign.id}],
    }
    db_session.commit()
    with pytest.raises(CanonicalReconciliationError) as cross_stock:
        guard_reconciled_source_selection(
            [first],
            consumer="stock_pool_piotroski_display",
            knowledge_cutoff=datetime.now(timezone.utc),
            session=db_session,
            user_id=user.id,
        )
    assert cross_stock.value.blocking_items[0]["reason_code"] == (
        "cross_stock_lineage_reference"
    )


def test_original_manual_input_passthrough_still_respects_knowledge_cutoff(
    db_session, user_factory
):
    user = user_factory("manual-input-cutoff@example.com")
    stock = Stock(ticker="MANPIT", exchange="NYSE", company_name="Manual PIT")
    db_session.add(stock)
    db_session.flush()
    cutoff = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    future_input = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="manual.assumption",
        value_numeric=1,
        value_json={"manual_role": "original_input"},
        unit="ratio",
        period_type="AS_OF",
        period_end_date=date(2026, 9, 4),
        source_type="manual",
        is_current=True,
        created_at=cutoff + timedelta(seconds=1),
        updated_at=cutoff + timedelta(seconds=1),
    )
    db_session.add(future_input)
    db_session.commit()

    guarded = guard_reconciled_source_selection(
        [future_input],
        consumer="formula",
        knowledge_cutoff=cutoff,
        session=db_session,
        user_id=user.id,
    )

    assert guarded == []


def test_user_valuation_is_not_reconciled_as_a_financial_manual_correction(
    client, db_session, user_factory, auth_headers
):
    user = user_factory("reconcile-valuation-boundary@example.com")
    stock = Stock(ticker="RVAL", exchange="NYSE", company_name="Valuation Boundary")
    db_session.add(stock)
    db_session.flush()
    document = _document(user_id=user.id, stock_id=stock.id)
    db_session.add(document)
    db_session.flush()
    valuation = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="val.fair_value",
        value_numeric=80,
        value_json={"user_authored": True},
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 9, 4),
        source_type="manual",
        is_current=True,
    )
    reference = MetricFact(
        user_id=user.id,
        stock_id=stock.id,
        metric_key="target.price_18m.mid",
        value_numeric=100,
        value_json={
            "fact_nature": "estimate",
            "mapping_id": "target.price_18m.mid",
            "definition_basis": "adjusted",
            "dimensions_identity": "empty",
        },
        unit="USD",
        currency="USD",
        period_type="AS_OF",
        period_end_date=date(2026, 9, 4),
        source_type="parsed",
        source_document_id=document.id,
        is_current=True,
    )
    db_session.add_all([valuation, reference])
    db_session.commit()

    response = client.get(
        f"/api/v1/stocks/{stock.id}/source-reconciliation",
        headers=auth_headers(user),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert valuation.id not in payload["eligible_fact_ids"]
    assert any(
        row["fact_id"] == valuation.id
        and row["reason_code"] == "user_authored_valuation_out_of_scope"
        for row in payload["excluded"]
    )
    assert all(
        item["metric_key"] != "val.fair_value" for item in payload["items"]
    )
    assert any(
        item["metric_key"] == "target.price_18m.mid" for item in payload["items"]
    )
