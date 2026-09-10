"""Raw SEC lineage must never become a second product fundamentals store."""

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SANCTIONED = {
    APP_ROOT / "models" / "sec_financials.py",
    # Publication schema and service own exact raw-input lineage; neither is a
    # product fundamentals read path.
    APP_ROOT / "models" / "sec_publication.py",
    APP_ROOT / "services" / "sec_financial_ingestion.py",
    APP_ROOT / "services" / "sec_metric_publication.py",
    # Canonical availability resolves a published fact's retained input cycle
    # only to enforce typed amendment unavailability.
    APP_ROOT / "services" / "canonical_financials.py",
    # S2's authenticated evidence resolver reads retained lexical text by the
    # selected publication input's immutable IDs. Canonical values still come
    # from metric_facts, not raw facts or numeric normalizations.
    APP_ROOT / "services" / "sec_financial_evidence.py",
    APP_ROOT / "cli" / "sec_financials.py",
    # Step D acceptance audits lineage counts and duplicate identities only;
    # it does not read fact values or expose a product query path.
    APP_ROOT / "acceptance" / "sec_gold_audit.py",
    APP_ROOT / "acceptance" / "sec_gold_publication.py",
    APP_ROOT / "acceptance" / "sec_gold_report.py",
}
RAW_TOKENS = ("SecRawXbrlFact", "sec_raw_xbrl_facts")


def test_product_modules_do_not_read_raw_sec_financial_facts() -> None:
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path in SANCTIONED or "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        if any(token in source for token in RAW_TOKENS):
            violations.append(str(path.relative_to(APP_ROOT)))

    assert violations == [], (
        "raw SEC XBRL is lineage only; product consumers must use metric_facts. "
        f"Direct owners: {violations}"
    )


def test_sec_evidence_exception_is_exact_lineage_not_a_numeric_fact_store() -> None:
    source = (APP_ROOT / "services" / "sec_financial_evidence.py").read_text(encoding="utf-8")
    assert "f.value_numeric" in source
    assert "LEFT JOIN metric_facts f ON f.id=p.metric_fact_id" in source
    assert "f.source_ref_id=p.id" in source
    assert "WHERE raw.id=:raw" in source
    assert "n.id=:normalization AND n.raw_fact_id=raw.id" in source
    assert "rs.publication_run_id=:run AND rs.parse_run_id=raw.parse_run_id" in source
    assert "a.id=:authority AND a.raw_fact_id=:raw AND a.parse_run_id=:parse" in source
    assert "MAX_EVIDENCE_INPUTS" in source and "MAX_EVIDENCE_DEPTH" in source
    # Supplemental architectural scan; behavior/API tests independently check
    # access, identity, complete inputs, exact values and typed failures.
    for forbidden in ("raw.value_numeric", "n.value_numeric", "normalized_value", "SELECT raw.*"):
        assert forbidden not in source
