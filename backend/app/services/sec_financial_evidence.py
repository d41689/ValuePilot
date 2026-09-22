"""Bounded, currently authorized evidence for immutable SEC publications.

Queryable values come only from metric_facts. Retained occurrence authority is
read by exact IDs; this module neither parses artifacts nor fetches documents.
"""
from __future__ import annotations

from html import unescape
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.evaluation_snapshot import EvaluationSnapshot, database_evaluation_snapshot

MAX_EVIDENCE_INPUTS = 32
MAX_EVIDENCE_DEPTH = 8
MAX_LOCATOR_BYTES = 262144


class EvidenceUnavailable(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _visible(aliases: tuple[str, ...]) -> str:
    # Identifiers are module-owned constants, never request data.
    return " AND ".join(
        f"({alias}.created_txid=txid_current() OR txid_visible_in_snapshot("
        f"{alias}.created_txid, CAST(:snapshot AS txid_snapshot))) AND {alias}.created_at<=:cutoff"
        for alias in aliases
    )


def _params(snapshot: EvaluationSnapshot, **values) -> dict:
    return {"snapshot": snapshot.visibility_snapshot, "cutoff": snapshot.cutoff, **values}


def authorized_publication(session: Session, *, stock_id: int, publication_id: int,
                           snapshot: EvaluationSnapshot, lock_authority: bool = False) -> dict | None:
    row = session.execute(text("""
        SELECT p.id, p.status, p.metric_fact_id, p.publication_run_id,
               p.locator_json, p.derivation_kind, p.context_id,
               p.metric_key, p.unit, p.currency, p.period_type, p.period_basis,
               p.period_start_date, p.period_end_date, p.fiscal_year,
               p.fiscal_quarter_ordinal, p.source_role, p.fact_nature,
               f.value_numeric, f.is_current
        FROM sec_metric_publications p
        JOIN sec_metric_publication_runs r ON r.id=p.publication_run_id AND r.stock_id=p.stock_id
        JOIN sec_metric_publication_availabilities a ON a.publication_run_id=r.id
        JOIN sec_metric_mapping_versions v ON v.id=r.mapping_version_id
        JOIN sec_metric_mapping_rules rule ON rule.id=p.mapping_rule_id AND rule.mapping_version_id=v.id
        LEFT JOIN metric_facts f ON f.id=p.metric_fact_id AND f.stock_id=p.stock_id
          AND f.source_type='sec' AND f.user_id IS NULL AND f.source_ref_id=p.id
          AND f.metric_key=p.metric_key AND f.period_type=p.period_type
          AND f.period_end_date=p.period_end_date
        WHERE p.id=:publication AND p.stock_id=:stock AND r.status='succeeded'
          AND v.status='approved' AND v.known_at<=:cutoff AND v.effective_from<=:cutoff
          AND (v.retired_at IS NULL OR v.retired_at>:cutoff)
          AND p.known_at<=:cutoff AND a.available_at<=:cutoff
          AND (a.finalized_txid=txid_current() OR txid_visible_in_snapshot(
              a.finalized_txid, CAST(:snapshot AS txid_snapshot)))
          AND (p.status<>'published' OR f.id IS NOT NULL)
          AND octet_length(p.locator_json::text)<=:locator_bound
          AND """ + _visible(("p", "r", "v", "rule"))
        + (" FOR SHARE OF v" if lock_authority else "")),
        _params(snapshot, publication=publication_id, stock=stock_id, locator_bound=MAX_LOCATOR_BYTES),
    ).mappings().first()
    return dict(row) if row else None


def _inputs(session: Session, publication: dict, snapshot: EvaluationSnapshot) -> list[dict]:
    rows = session.execute(text("""
        SELECT i.*, """ + _visible(("i",)) + """ AS visible
        FROM sec_metric_publication_inputs i WHERE i.publication_id=:publication
        ORDER BY i.input_ordinal LIMIT :bound
    """), _params(snapshot, publication=publication["id"], bound=MAX_EVIDENCE_INPUTS + 1)).mappings().all()
    if len(rows) > MAX_EVIDENCE_INPUTS:
        raise EvidenceUnavailable("evidence_input_bound_exceeded")
    if not rows or any(not row.visible for row in rows):
        raise EvidenceUnavailable("evidence_inputs_unavailable")
    return [dict(row) for row in rows]


def safe_evidence_text(value: Any, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 8000 or (required and not value.strip()):
        raise EvidenceUnavailable("evidence_text_unavailable")
    value = unescape(value)
    if (re.search(r"<[!/?a-zA-Z][^>]*>|(?:file|javascript):|/(?:Users|code|tmp)/|storage/", value)
            or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", value)):
        raise EvidenceUnavailable("unsafe_evidence_text")
    return value


def _raw_binding(session: Session, publication: dict, item: dict, snapshot: EvaluationSnapshot) -> dict:
    row = session.execute(text("""
        SELECT raw.id, raw.raw_value, raw.scale, raw.sign, raw.decimals,
               raw.unit_measure, raw.context_id, raw.parse_run_id,
               filing.accession_no, filing.form_type, filing.primary_document, issuer.cik
        FROM sec_raw_xbrl_facts raw
        JOIN sec_metric_publication_run_sources rs ON rs.id=:source
          AND rs.publication_run_id=:run AND rs.parse_run_id=raw.parse_run_id
        JOIN sec_raw_numeric_normalizations n ON n.id=:normalization AND n.raw_fact_id=raw.id
        JOIN sec_financial_filings filing ON filing.id=rs.filing_id
        JOIN sec_issuer_identities issuer ON issuer.id=filing.issuer_identity_id
        WHERE raw.id=:raw AND rs.source_available_at<=:cutoff
          AND filing.known_at<=:cutoff AND filing.created_at<=:cutoff AND """
        + _visible(("raw", "rs", "n"))),
        _params(snapshot, source=item["run_source_id"], run=publication["publication_run_id"],
                normalization=item["normalization_id"], raw=item["raw_fact_id"])).mappings().first()
    if row is None:
        raise EvidenceUnavailable("evidence_input_authority_unavailable")
    return dict(row)


def _statement(session: Session, publication: dict, item: dict, raw: dict,
               snapshot: EvaluationSnapshot) -> dict:
    from app.services.canonical_financials import _canonical_sec_url
    locator = publication["locator_json"]
    occurrences = locator.get("ordered_input_occurrences", [locator]) if isinstance(locator, dict) else []
    if not isinstance(occurrences, list) or len(occurrences) > MAX_EVIDENCE_INPUTS:
        raise EvidenceUnavailable("evidence_locator_unavailable")
    matches = [entry for entry in occurrences if isinstance(entry, dict)
               and entry.get("raw_fact_id") == raw["id"]
               and entry.get("parse_run_id") == raw["parse_run_id"]]
    if len(matches) != 1:
        raise EvidenceUnavailable("evidence_locator_unavailable")
    locator = matches[0]
    row = session.execute(text("""
        SELECT a.id, a.report_name, o.header_raw, o.header_date, o.locator_json,
               o.report_ordinal, o.row_ordinal, o.column_ordinal, o.occurrence_ordinal,
               o.context_id, o.concept, o.fact_id
        FROM sec_statement_fact_authorities a
        JOIN sec_statement_occurrence_evidence o ON o.id=a.statement_occurrence_id
          AND o.raw_fact_id=a.raw_fact_id AND o.parse_run_id=a.parse_run_id
          AND o.context_id=a.context_id
        JOIN sec_statement_report_references ref ON ref.id=a.statement_report_reference_id
          AND ref.id=o.statement_report_reference_id AND ref.parse_run_id=a.parse_run_id
          AND ref.report_sha256=a.statement_sha256 AND ref.report_sha256=o.report_sha256
        WHERE a.id=:authority AND a.raw_fact_id=:raw AND a.parse_run_id=:parse
          AND a.statement_report_reference_id=:reference AND a.statement_sha256=:sha
          AND a.occurrence_semantic_sha256=:semantic
          AND o.report_ordinal=:report AND o.occurrence_ordinal=:occurrence
          AND o.row_ordinal=:row AND o.column_ordinal=:column
          AND a.context_id=:context AND a.known_at<=:cutoff AND o.known_at<=:cutoff AND ref.known_at<=:cutoff
          AND octet_length(o.locator_json::text)<=:locator_bound AND """
        + _visible(("a", "o", "ref"))),
        _params(snapshot, authority=locator.get("statement_authority_id"), raw=raw["id"],
                parse=raw["parse_run_id"], reference=locator.get("statement_report_reference_id"),
                sha=locator.get("statement_sha256"), semantic=locator.get("occurrence_semantic_sha256"),
                report=locator.get("report_ordinal"), occurrence=locator.get("occurrence_ordinal"),
                row=locator.get("row_ordinal"), column=locator.get("column_ordinal"), context=raw["context_id"],
                locator_bound=MAX_LOCATOR_BYTES)).mappings().first()
    if row is None:
        raise EvidenceUnavailable("evidence_locator_unavailable")
    details = row.locator_json if isinstance(row.locator_json, dict) else {}
    return {
        "raw_fact_id": raw["id"], "statement_authority_id": row.id,
        "accession": safe_evidence_text(raw["accession_no"], required=True),
        "form": safe_evidence_text(raw["form_type"], required=True),
        "sec_url": _canonical_sec_url(cik=raw["cik"], accession=raw["accession_no"],
                                      primary_document=raw["primary_document"]),
        "raw_value": safe_evidence_text(raw["raw_value"], required=True),
        "display_value": safe_evidence_text(details.get("display_value")),
        "scale": raw["scale"], "sign": raw["sign"], "decimals": safe_evidence_text(raw["decimals"]),
        "unit_measure": safe_evidence_text(raw["unit_measure"]),
        "display_multiplier": safe_evidence_text(details.get("scale_multiplier")),
        "preferred_label_role": safe_evidence_text(details.get("preferred_label_role")),
        "report_name": safe_evidence_text(row.report_name, required=True),
        "row_label": safe_evidence_text(details.get("row_label"), required=True),
        "column_header": safe_evidence_text(row.header_raw, required=True),
        "header_date": row.header_date.isoformat(),
        "context_id": safe_evidence_text(row.context_id, required=True),
        "concept": safe_evidence_text(row.concept, required=True),
        "locator": {key: getattr(row, key) for key in
                    ("report_ordinal", "row_ordinal", "column_ordinal", "occurrence_ordinal")},
    }


def _graph(session: Session, *, stock_id: int, publication: dict, snapshot: EvaluationSnapshot,
           include_statements: bool, lock_authority: bool, path: tuple[int, ...] = (),
           budget: list[int] | None = None) -> list[dict]:
    if len(path) >= MAX_EVIDENCE_DEPTH or publication["id"] in path:
        raise EvidenceUnavailable("evidence_input_bound_exceeded")
    budget = budget if budget is not None else [MAX_EVIDENCE_INPUTS]
    result = []
    for item in _inputs(session, publication, snapshot):
        budget[0] -= 1
        if budget[0] < 0:
            raise EvidenceUnavailable("evidence_input_bound_exceeded")
        output = {"ordinal": item["input_ordinal"], "arithmetic_sign": item["arithmetic_sign"]}
        child_id = item["source_publication_id"]
        if child_id is not None:
            child = authorized_publication(session, stock_id=stock_id, publication_id=child_id,
                                           snapshot=snapshot, lock_authority=lock_authority)
            if child is None or child["status"] != "published":
                raise EvidenceUnavailable("evidence_input_authority_unavailable")
            output.update(publication_id=child_id, metric_fact_id=child["metric_fact_id"],
                          value_numeric_exact=format(child["value_numeric"], "f") if child["value_numeric"] is not None else None,
                          inputs=_graph(session, stock_id=stock_id, publication=child, snapshot=snapshot,
                                        include_statements=include_statements, lock_authority=lock_authority,
                                        path=(*path, publication["id"]), budget=budget))
        else:
            raw = _raw_binding(session, publication, item, snapshot)
            if include_statements:
                output["statement"] = _statement(session, publication, item, raw, snapshot)
        result.append(output)
    return result


def sec_fact_reference_available(session: Session, *, stock_id: int, fact_id: int,
                                 publication_id: int, lock_authority: bool = False) -> bool:
    snapshot = database_evaluation_snapshot(session)
    publication = authorized_publication(session, stock_id=stock_id, publication_id=publication_id,
                                         snapshot=snapshot, lock_authority=lock_authority)
    if publication is None or publication["status"] != "published" or publication["metric_fact_id"] != fact_id:
        return False
    try:
        _graph(session, stock_id=stock_id, publication=publication, snapshot=snapshot,
               include_statements=False, lock_authority=lock_authority)
    except EvidenceUnavailable:
        return False
    return True


def sec_reference_row(session: Session, *, stock_id: int, fact_id: int, publication_id: int) -> dict | None:
    """Current access projection for a recorded immutable ID, never persisted."""
    from app.schemas.financial_history import FinancialHistoryRow

    snapshot = database_evaluation_snapshot(session)
    row = authorized_publication(session, stock_id=stock_id, publication_id=publication_id, snapshot=snapshot)
    if row is None or row["metric_fact_id"] != fact_id or row["status"] != "published":
        return None
    return FinancialHistoryRow(
        row_kind="fact", row_key=f"fact:{fact_id}", status="available", fact_id=fact_id,
        publication_id=publication_id, metric_key=row["metric_key"],
        value_numeric_exact=format(row["value_numeric"], "f") if row["value_numeric"] is not None else None,
        unit=row["unit"], currency=row["currency"], period_type=row["period_type"],
        period_basis=row["period_basis"], period_start=row["period_start_date"], period_end=row["period_end_date"],
        fiscal_year=row["fiscal_year"], fiscal_quarter=row["fiscal_quarter_ordinal"],
        source_type="sec", source_role=row["source_role"], fact_nature=row["fact_nature"],
        evidence_capability="sec_statement",
    ).model_dump(mode="json")


def _unavailable_evidence(publication: dict, reason: str, metadata: dict | None = None) -> dict:
    """Retain response metadata, but never a partial input or numeric proof."""
    result = dict(metadata or {})
    result.update(publication_id=publication["id"], metric_fact_id=publication["metric_fact_id"],
                  status=publication["status"], evidence_state="unavailable", evidence_reason_code=reason,
                  value_numeric=None, value_numeric_exact=None, inputs=[], locator=None, filings=[])
    return result


def resolve_evidence(session: Session, *, stock_id: int, publication_id: int,
                     fact_id: int | None = None) -> dict | None:
    from app.services.canonical_financials import _legacy_sec_publication_evidence

    snapshot = database_evaluation_snapshot(session)
    publication = authorized_publication(session, stock_id=stock_id, publication_id=publication_id, snapshot=snapshot)
    if publication is None or (fact_id is not None and publication["metric_fact_id"] != fact_id):
        return None
    if publication["status"] != "published":
        result = _legacy_sec_publication_evidence(session, stock_id=stock_id, publication_id=publication_id)
        return _unavailable_evidence(publication, "publication_not_published", result)
    try:
        _graph(session, stock_id=stock_id, publication=publication, snapshot=snapshot,
               include_statements=False, lock_authority=False)
    except EvidenceUnavailable as error:
        return _unavailable_evidence(publication, error.code)
    result = _legacy_sec_publication_evidence(session, stock_id=stock_id, publication_id=publication_id)
    result.update(evidence_state="available", evidence_reason_code=None,
                  value_numeric_exact=format(publication["value_numeric"], "f") if publication["value_numeric"] is not None else None,
                  currentness="current" if publication["is_current"] else "superseded")
    try:
        inputs = _graph(session, stock_id=stock_id, publication=publication, snapshot=snapshot,
                        include_statements=True, lock_authority=False)
    except EvidenceUnavailable as error:
        return _unavailable_evidence(publication, error.code, result)
    for legacy, expanded in zip(result["inputs"], inputs, strict=True):
        legacy.update(expanded)
    return result
