import ast
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services.calculated_metrics.piotroski_f_score import build_piotroski_f_score_facts
from app.services.calculated_metrics.value_line_ratios import build_value_line_ratio_facts
from app.services.canonical_financials import (
    CanonicalUnavailableError,
    CanonicalSourceConflictError,
    guard_sec_run_availability,
    guard_source_selection,
)


def _fact(metric_key: str, value: int, source_type: str):
    return SimpleNamespace(
        id=value,
        metric_key=metric_key,
        value_numeric=value,
        value_json={"fact_nature": "actual"},
        period_type="FY",
        period_end_date=date(2025, 12, 31),
        source_type=source_type,
        source_document_id=None,
    )


def test_source_guard_requires_explicit_selection_for_multiple_roles():
    facts = [_fact("is.net_income", 10, "sec"), _fact("bs.total_assets", 20, "parsed")]

    with pytest.raises(CanonicalSourceConflictError) as raised:
        guard_source_selection(facts, consumer="formula")

    assert raised.value.code == "source_conflict"
    assert raised.value.source_types == ("parsed", "sec")
    assert guard_source_selection(facts, consumer="formula", selected_source_type="sec") == [facts[0]]


def test_ratio_and_piotroski_primitives_fail_closed_on_mixed_sources():
    facts = [_fact("is.net_income", 10, "sec"), _fact("bs.total_assets", 20, "parsed")]

    with pytest.raises(CanonicalSourceConflictError):
        build_value_line_ratio_facts(facts)
    with pytest.raises(CanonicalSourceConflictError):
        build_piotroski_f_score_facts(facts, roic_decisions_by_period={})


def test_source_guard_uses_only_the_facts_canonical_source_role():
    parsed = _fact("is.net_income", 10, "parsed")
    correction = _fact("bs.total_assets", 20, "manual")
    correction.source_document_id = 91
    correction.value_json = {"correction": True, "source_types": ["parsed"]}

    with pytest.raises(CanonicalSourceConflictError) as raised:
        guard_source_selection([parsed, correction], consumer="ratio")

    assert raised.value.source_types == ("manual", "parsed")
    assert guard_source_selection(
        [parsed, correction], consumer="ratio", selected_source_type="manual"
    ) == [correction]


def test_selected_sec_does_not_include_calculated_lineage_from_sec():
    calculated = _fact("returns.roa", 10, "calculated")
    calculated.value_json = {"source_types": ["sec"]}

    assert guard_source_selection(
        [calculated], consumer="ratio", selected_source_type="sec"
    ) == []
    assert guard_source_selection(
        [calculated], consumer="ratio", selected_source_type="calculated"
    ) == [calculated]


def test_sec_amendment_availability_is_bounded_to_selected_cycle(monkeypatch):
    failed_cycle = date(2025, 9, 30)
    state = {
        "status": "unresolved",
        "reason_code": "unresolved_amendment_parse_failure",
        "period_end_date": failed_cycle,
        "source_type": "sec",
        "filing_cycle": {"base_form": "10-Q", "report_date": failed_cycle},
    }
    monkeypatch.setattr(
        "app.services.canonical_financials.active_sec_run_unresolved_states",
        lambda _session, *, stock_id, knowledge_cutoff=None: [state],
    )
    old_sec = _fact("is.net_income", 1, "sec")
    old_sec.period_end_date = date(2022, 12, 31)
    old_sec.source_ref_id = 11
    failed_sec = _fact("is.net_income", 2, "sec")
    failed_sec.period_end_date = failed_cycle
    failed_sec.source_ref_id = 12
    parsed = _fact("is.net_income", 3, "parsed")
    manual = _fact("is.net_income", 4, "manual")
    monkeypatch.setattr(
        "app.services.canonical_financials.sec_fact_filing_cycles",
        lambda _session, *, facts: {
            11: {("10-K", date(2022, 12, 31))},
            12: {("10-Q", failed_cycle)},
        },
    )

    assert guard_sec_run_availability(object(), stock_id=7, facts=[old_sec]) == [old_sec]
    assert guard_sec_run_availability(object(), stock_id=7, facts=[parsed, manual]) == [
        parsed,
        manual,
    ]
    with pytest.raises(CanonicalUnavailableError) as raised:
        guard_sec_run_availability(object(), stock_id=7, facts=[failed_sec])
    assert raised.value.state["period_end_date"] == failed_cycle

    monkeypatch.setattr(
        "app.services.canonical_financials.active_sec_run_unresolved_states",
        lambda _session, *, stock_id, knowledge_cutoff=None: [],
    )
    assert guard_sec_run_availability(object(), stock_id=7, facts=[failed_sec]) == [failed_sec]


def test_sec_amendment_cycle_uses_base_form_not_period_end_date(monkeypatch):
    report_date = date(2025, 9, 30)
    state = {
        "status": "unresolved",
        "reason_code": "unresolved_amendment_parse_failure",
        "period_end_date": report_date,
        "source_type": "sec",
        "filing_cycle": {"base_form": "10-Q", "report_date": report_date},
    }
    monkeypatch.setattr(
        "app.services.canonical_financials.active_sec_run_unresolved_states",
        lambda _session, *, stock_id, knowledge_cutoff=None: [state],
    )
    ten_k = _fact("is.net_income", 1, "sec")
    ten_k.period_end_date = report_date
    ten_k.source_ref_id = 21
    ten_q = _fact("is.net_income", 2, "sec")
    ten_q.period_end_date = report_date
    ten_q.source_ref_id = 22
    monkeypatch.setattr(
        "app.services.canonical_financials.sec_fact_filing_cycles",
        lambda _session, *, facts: {
            21: {("10-K", report_date)},
            22: {("10-Q", report_date)},
        },
    )

    assert guard_sec_run_availability(object(), stock_id=7, facts=[ten_k]) == [ten_k]
    with pytest.raises(CanonicalUnavailableError):
        guard_sec_run_availability(object(), stock_id=7, facts=[ten_q])


@pytest.mark.parametrize("transition", ["amendment", "retirement"])
def test_sec_availability_uses_cutoff_before_later_authority_transition(
    monkeypatch, transition
):
    evaluated_at = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    transition_at = evaluated_at + timedelta(minutes=1)
    state = {
        "status": "unresolved",
        "reason_code": "unresolved_amendment_parse_failure",
        "period_end_date": date(2025, 9, 30),
        "source_type": "sec",
        "filing_cycle": {"base_form": "10-Q", "report_date": date(2025, 9, 30)},
    }

    def states_at_cutoff(_session, *, stock_id, knowledge_cutoff=None):
        assert stock_id == 7
        if transition == "amendment":
            return [state] if knowledge_cutoff >= transition_at else []
        return [state] if knowledge_cutoff < transition_at else []

    monkeypatch.setattr(
        "app.services.canonical_financials.active_sec_run_unresolved_states",
        states_at_cutoff,
    )
    sec_fact = _fact("is.net_income", 2, "sec")
    sec_fact.source_ref_id = 12
    monkeypatch.setattr(
        "app.services.canonical_financials.sec_fact_filing_cycles",
        lambda _session, *, facts: {
            12: {("10-Q", date(2025, 9, 30))},
        },
    )

    if transition == "amendment":
        assert guard_sec_run_availability(
            object(), stock_id=7, facts=[sec_fact], knowledge_cutoff=evaluated_at
        ) == [sec_fact]
        with pytest.raises(CanonicalUnavailableError):
            guard_sec_run_availability(
                object(), stock_id=7, facts=[sec_fact], knowledge_cutoff=transition_at
            )
    else:
        with pytest.raises(CanonicalUnavailableError):
            guard_sec_run_availability(
                object(), stock_id=7, facts=[sec_fact], knowledge_cutoff=evaluated_at
            )
        assert guard_sec_run_availability(
            object(), stock_id=7, facts=[sec_fact], knowledge_cutoff=transition_at
        ) == [sec_fact]


def test_all_production_sec_availability_callers_pass_a_cutoff():
    missing: list[str] = []
    for path in Path("app").rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if function_name != "guard_sec_run_availability":
                continue
            if not any(item.arg == "knowledge_cutoff" for item in node.keywords):
                missing.append(f"{path}:{node.lineno}")

    assert missing == []


def test_method_gate_consumers_do_not_capture_independent_app_clocks():
    guarded_paths = (
        Path("app/api/v1/endpoints/stocks.py"),
        Path("app/services/calculated_metrics/piotroski_f_score.py"),
        Path("app/services/calculated_metrics/value_line_ratios.py"),
        Path("app/services/dcf_inputs.py"),
        Path("app/services/formula_engine.py"),
        Path("app/services/oracles_lens/dashboard.py"),
        Path("app/services/screener_service.py"),
    )
    violations: list[str] = []
    for path in guarded_paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = ast.unparse(node.func)
            if function_name in {"datetime.now", "date.today"}:
                violations.append(f"{path}:{node.lineno}:{function_name}")
            if (
                function_name == "dcf_evaluation_clock"
                and not node.args
                and not node.keywords
            ):
                violations.append(f"{path}:{node.lineno}:unbound DCF clock")

    assert violations == []
