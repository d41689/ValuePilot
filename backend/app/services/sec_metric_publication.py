"""PIT-safe SEC publication rebuilt exclusively from database authority."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.sec_financial_mapping import (
    ConceptRule, FilingCycleSourceAuthority, MappingResult, MappingRule,
    MappingRunAuthority, MappingSnapshot, MAX_MAPPING_DECISIONS,
    MAX_MAPPING_FACTS,
    RawFactSnapshot, TypedDisposition,
    map_sec_financial_snapshot, validate_sec_mapping_snapshot,
)
from app.services.sec_statement_authority import (
    StatementAuthoritySnapshot, authoritative_raw_fact_snapshot,
)
from app.services.sec_financial_locking import acquire_sec_financial_stock_lock
from app.services.sec_financial_ingestion import PARSER_V2


@dataclass(frozen=True)
class VerifiedPublicationSource:
    parse_run_id: int
    filing_id: int
    accession_no: str
    parser_version: str
    input_manifest_hash: str
    available_at: datetime


@dataclass(frozen=True)
class PublicationRequest:
    stock_id: int
    issuer_identity_id: int
    mapping_version_id: str
    requested_cutoff: datetime
    amendment_policy: str
    sources: tuple[VerifiedPublicationSource, ...]
    # Optional assertion for callers that independently ran the pure mapper.
    # It is never publication authority and must compare byte-for-byte with the
    # database-rebuilt result before the stock lock or any write.
    outcome: MappingResult | None = None


@dataclass(frozen=True)
class PublicationReceipt:
    run_id: str
    replayed: bool
    available: bool
    fact_ids: tuple[int, ...]


class SecPublicationError(RuntimeError):
    pass


SEC_PUBLICATION_V1_PARSER_VERSION = PARSER_V2
MAX_PUBLICATION_SOURCES = MAX_MAPPING_FACTS
MAX_PUBLICATION_DECISIONS = MAX_MAPPING_DECISIONS + MAX_PUBLICATION_SOURCES


def _validate_publication_request_bounds(request: PublicationRequest) -> None:
    parse_ids = tuple(source.parse_run_id for source in request.sources)
    filing_ids = tuple(source.filing_id for source in request.sources)
    if len(request.sources) > MAX_PUBLICATION_SOURCES:
        raise SecPublicationError("publication source set exceeds bounded contract")
    if len(parse_ids) != len(set(parse_ids)) or len(filing_ids) != len(set(filing_ids)):
        raise SecPublicationError("publication source set contains duplicate authority")


def _validate_derived_unavailable_slot(slot, raw_authorities) -> None:
    """Require the complete ordered two-input authority for a derived gap."""

    if (
        len(slot.raw_fact_ids) != 2
        or len(set(slot.raw_fact_ids)) != 2
        or len(slot.parse_run_ids) != 2
        or slot.period_type != "Q"
        or slot.period_basis != "duration"
        or slot.fiscal_quarter_ordinal not in {2, 3, 4}
        or slot.period_start is None
        or not 70 <= (slot.period_end - slot.period_start).days + 1 <= 110
        or len(raw_authorities) != 2
        or any(row.period_instant is not None for row in raw_authorities)
        or raw_authorities[0].period_end != slot.period_end
        or raw_authorities[1].period_end != slot.period_start - timedelta(days=1)
        or tuple(
            int(item["raw_fact_id"]) for item in slot.occurrence_authorities
        )
        != slot.raw_fact_ids
        or tuple(row.raw_fact_id for row in raw_authorities)
        != slot.raw_fact_ids
        or tuple(row.parse_run_id for row in raw_authorities)
        != slot.parse_run_ids
    ):
        raise SecPublicationError("derived unavailable slot evidence shape mismatch")


@dataclass(frozen=True)
class _ResolvedLatestKnownV1Authority:
    sources: tuple[VerifiedPublicationSource, ...]
    filing_cycles: tuple[FilingCycleSourceAuthority, ...]


def _resolve_latest_known_v1_authority(
    db: Session,
    *,
    stock_id: int,
    issuer_identity_id: int,
    requested_cutoff: datetime,
) -> _ResolvedLatestKnownV1Authority:
    """Resolve the complete V1 parse authority from durable filing lineage."""

    if requested_cutoff.tzinfo is None or requested_cutoff.utcoffset() is None:
        raise SecPublicationError("publication cutoff must be timezone-aware")
    rows = db.execute(
        text(
            """SELECT pr.id AS parse_run_id,pr.filing_id,pr.parser_version,
                      pr.input_manifest_hash,pr.status,pr.known_at AS parse_known_at,
                      pr.completed_at,f.accession_no,f.form_type,f.is_amendment,
                      f.report_date,f.accepted_at,f.known_at AS filing_known_at,
                      a.available_at
               FROM sec_financial_parse_runs pr
               JOIN sec_financial_filings f ON f.id=pr.filing_id
               JOIN sec_issuer_identities i ON i.id=f.issuer_identity_id
               JOIN sec_financial_lineage_availabilities a
                 ON a.operation_id=pr.operation_id
               WHERE f.issuer_identity_id=:issuer AND i.stock_id=:stock
                 AND f.report_date IS NOT NULL
                 AND f.accepted_at<=:cutoff AND f.known_at<=:cutoff
                 AND pr.completed_at<=:cutoff AND pr.known_at<=:cutoff
                 AND a.available_at<=:cutoff
                 AND pr.parser_version=:parser
                 AND (
                   pr.status='succeeded'
                   OR (
                     pr.status='failed' AND f.is_amendment
                     AND right(f.form_type,2)='/A' AND pr.fact_count=0
                     AND EXISTS (
                       SELECT 1 FROM sec_financial_accession_attempts attempt
                       WHERE attempt.parse_run_id=pr.id AND attempt.filing_id=f.id
                         AND attempt.outcome IN ('parse_failed','parse_reused_failed')
                     )
                     AND EXISTS (
                       SELECT 1 FROM sec_financial_acquisition_resolutions resolution
                       WHERE resolution.parse_run_id=pr.id
                         AND resolution.accession_no=f.accession_no
                         AND resolution.resolution_kind='parse_failed'
                     )
                   )
                 )
               ORDER BY f.id,pr.known_at,pr.completed_at,a.available_at,
                        pr.input_manifest_hash"""
        ),
        {
            "issuer": issuer_identity_id,
            "stock": stock_id,
            "cutoff": requested_cutoff,
            "parser": SEC_PUBLICATION_V1_PARSER_VERSION,
        },
    ).mappings().all()

    latest_by_filing: dict[int, object] = {}
    for row in rows:
        prior = latest_by_filing.get(row.filing_id)
        if prior is not None:
            prior_boundary = (
                prior.parse_known_at,
                prior.completed_at,
                prior.available_at,
            )
            row_boundary = (row.parse_known_at, row.completed_at, row.available_at)
            if row_boundary == prior_boundary:
                raise SecPublicationError(
                    "ambiguous latest parser authority for one filing"
                )
        latest_by_filing[row.filing_id] = row

    cycles: dict[tuple[str, date], list[object]] = {}
    for row in latest_by_filing.values():
        cycles.setdefault(
            (str(row.form_type).removesuffix("/A"), row.report_date), []
        ).append(row)

    selected = []
    for cycle in sorted(cycles, key=lambda item: (item[1], item[0])):
        members = cycles[cycle]
        originals = [row for row in members if not row.is_amendment]
        amendments = [row for row in members if row.is_amendment]
        filing_order = lambda row: (
            row.accepted_at,
            row.filing_known_at,
            row.available_at,
            row.accession_no,
            row.parse_known_at,
            row.input_manifest_hash,
        )
        if originals:
            selected.append(max(originals, key=filing_order))
        # Each amendment accession is independent retained authority.  A later
        # successful amendment can affect only the slots it proves; it cannot
        # classify the unknown scope of an earlier failed accession.  A later
        # successful parse of that same filing is selected above and replaces
        # its earlier failed parse authority.
        selected.extend(sorted(amendments, key=filing_order))

    selected.sort(
        key=lambda row: (
            row.report_date,
            str(row.form_type).removesuffix("/A"),
            bool(row.is_amendment),
            row.accepted_at,
            row.filing_known_at,
            row.available_at,
            row.accession_no,
            row.parse_known_at,
            row.input_manifest_hash,
        )
    )
    sources = tuple(
        VerifiedPublicationSource(
            int(row.parse_run_id),
            int(row.filing_id),
            str(row.accession_no),
            str(row.parser_version),
            str(row.input_manifest_hash),
            row.available_at,
        )
        for row in selected
    )
    filing_cycles = tuple(
        FilingCycleSourceAuthority(
            filing_authority_id=str(row.accession_no),
            parse_run_id=int(row.parse_run_id),
            base_form=str(row.form_type).removesuffix("/A"),
            report_date=row.report_date,
            accepted_at=row.accepted_at,
            is_amendment=bool(row.is_amendment),
            parse_status=str(row.status),
        )
        for row in selected
    )
    return _ResolvedLatestKnownV1Authority(sources, filing_cycles)


def resolve_latest_known_v1_sources(
    db: Session,
    *,
    stock_id: int,
    issuer_identity_id: int,
    requested_cutoff: datetime,
) -> tuple[VerifiedPublicationSource, ...]:
    """Return the complete canonical V1 source order for operator assertions."""

    return _resolve_latest_known_v1_authority(
        db,
        stock_id=stock_id,
        issuer_identity_id=issuer_identity_id,
        requested_cutoff=requested_cutoff,
    ).sources


def _load_mapping_snapshot(db: Session, mapping_version_id: str) -> MappingSnapshot:
    version = db.execute(text("""SELECT id,status,effective_from,known_at,spec_sha256,
        currency_registry_id,currency_serialization,currency_sha256
      FROM sec_metric_mapping_versions WHERE id=:id"""), {"id":mapping_version_id}).mappings().one_or_none()
    if version is None or version.status != "approved":
        raise SecPublicationError("approved mapping version unavailable")
    namespace_rows = db.execute(text("""SELECT authority,namespace_uri,ordinal,spec_sha256
      FROM sec_metric_mapping_version_namespaces WHERE mapping_version_id=:id
      ORDER BY authority,ordinal"""), {"id":mapping_version_id}).mappings().all()
    currency_rows = db.execute(text("""SELECT currency_code,ordinal,spec_sha256,registry_sha256
      FROM sec_metric_mapping_version_currencies WHERE mapping_version_id=:id ORDER BY ordinal"""),
      {"id":mapping_version_id}).mappings().all()
    rule_rows = db.execute(text("""SELECT id,rule_id,metric_key,priority,concept_namespace_authority,
        concept_local_name,target_unit,period_policy,metadata_json,spec_sha256
      FROM sec_metric_mapping_rules WHERE mapping_version_id=:id ORDER BY id"""),
      {"id":mapping_version_id}).mappings().all()
    concept_rows = db.execute(text("""SELECT c.mapping_rule_id,c.concept_ordinal,c.namespace_authority,c.local_name,c.spec_sha256
      FROM sec_metric_mapping_rule_concepts c JOIN sec_metric_mapping_rules r ON r.id=c.mapping_rule_id
      WHERE r.mapping_version_id=:id ORDER BY c.mapping_rule_id,c.concept_ordinal"""),{"id":mapping_version_id}).mappings().all()
    if not namespace_rows or not currency_rows or not rule_rows or any(
        row.spec_sha256 != version.spec_sha256 for row in (*namespace_rows,*currency_rows,*rule_rows)
    ):
        raise SecPublicationError("mapping registry digest/count mismatch")
    namespaces: dict[str,list[str]] = {}
    for row in namespace_rows:
        expected_ordinal = len(namespaces.setdefault(row.authority, [])) + 1
        if row.ordinal != expected_ordinal:
            raise SecPublicationError("mapping namespace ordering mismatch")
        namespaces[row.authority].append(row.namespace_uri)
    if [row.ordinal for row in currency_rows] != list(range(1,len(currency_rows)+1)):
        raise SecPublicationError("mapping currency ordering mismatch")
    currency_serialization = json.dumps([row.currency_code for row in currency_rows],separators=(",",":"))
    if (currency_serialization != version.currency_serialization
            or hashlib.sha256(currency_serialization.encode()).hexdigest() != version.currency_sha256
            or any(row.registry_sha256 != version.currency_sha256 for row in currency_rows)):
        raise SecPublicationError("mapping currency registry digest mismatch")
    concepts_by_rule: dict[int,list[object]] = {}
    for concept in concept_rows: concepts_by_rule.setdefault(concept.mapping_rule_id,[]).append(concept)
    rules=[]
    for row in rule_rows:
        ordered = tuple((row.metadata_json or {}).get("ordered_concepts") or ())
        persisted = concepts_by_rule.get(row.id,[])
        if row.priority != 1 or not ordered or ordered[0] != row.concept_local_name or [c.concept_ordinal for c in persisted] != list(range(1,len(persisted)+1)) or tuple(c.local_name for c in persisted) != ordered or any(c.spec_sha256 != version.spec_sha256 for c in persisted):
            raise SecPublicationError("mapping rule metadata/priority mismatch")
        concepts = tuple(ConceptRule(c.namespace_authority,c.local_name,c.concept_ordinal) for c in persisted)
        value_kind = "monetary" if row.target_unit == "currency" else row.target_unit
        rules.append(MappingRule(row.rule_id,row.metric_key,value_kind,row.period_policy,concepts))
    snapshot = MappingSnapshot(version.id,version.spec_sha256,version.known_at,version.effective_from,
        MappingProxyType({key:tuple(values) for key,values in namespaces.items()}),
        tuple(row.currency_code for row in currency_rows),tuple(rules))
    try: validate_sec_mapping_snapshot(snapshot)
    except ValueError as exc: raise SecPublicationError("database mapping snapshot mismatch") from exc
    return snapshot


def _canonical(value):
    if is_dataclass(value):
        return {field.name: _canonical(getattr(value, field.name)) for field in fields(value)}
    if isinstance(value, Mapping):
        return {str(key): _canonical(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (tuple, list)):
        return [_canonical(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise SecPublicationError("publication identity datetimes must be timezone-aware")
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return value


def _identity(request: PublicationRequest) -> tuple[str, str]:
    source_payload = _canonical(request.sources)
    source_digest = hashlib.sha256(json.dumps(source_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    replay = json.dumps(_canonical(request), sort_keys=True, separators=(",", ":"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, replay)), source_digest


def _rebuild_mapping_result(db: Session, request: PublicationRequest) -> MappingResult:
    _validate_publication_request_bounds(request)
    mapping = _load_mapping_snapshot(db, request.mapping_version_id)
    if mapping.known_at > request.requested_cutoff or mapping.effective_at > request.requested_cutoff:
        raise SecPublicationError("mapping version is unavailable at publication cutoff")
    if request.amendment_policy != "latest-known-v1":
        raise SecPublicationError("unsupported amendment policy")
    resolved = _resolve_latest_known_v1_authority(
        db,
        stock_id=request.stock_id,
        issuer_identity_id=request.issuer_identity_id,
        requested_cutoff=request.requested_cutoff,
    )
    if request.sources != resolved.sources:
        raise SecPublicationError(
            "complete ordered source authority differs from finalized exact request sources"
        )
    source_ids = tuple(source.parse_run_id for source in request.sources)
    selected_filing_ids = []
    failed_amendment_ids: list[int] = []
    for source in request.sources:
        row = db.execute(text("""SELECT pr.filing_id,f.accession_no,pr.parser_version,pr.input_manifest_hash,
              pr.status,pr.known_at,f.known_at AS filing_known_at,a.available_at,i.stock_id,f.issuer_identity_id
            FROM sec_financial_parse_runs pr JOIN sec_financial_filings f ON f.id=pr.filing_id
            JOIN sec_issuer_identities i ON i.id=f.issuer_identity_id
            JOIN sec_financial_lineage_availabilities a ON a.operation_id=pr.operation_id
            WHERE pr.id=:parse"""), {"parse": source.parse_run_id}).mappings().one_or_none()
        exact_failed_amendment = False
        if row is not None and row.status == "failed":
            exact_failed_amendment = db.execute(text("""SELECT EXISTS(
              SELECT 1 FROM sec_financial_parse_runs pr JOIN sec_financial_filings f ON f.id=pr.filing_id
              WHERE pr.id=:parse AND f.is_amendment AND right(f.form_type,2)='/A' AND pr.fact_count=0
                AND EXISTS (SELECT 1 FROM sec_financial_accession_attempts a WHERE a.parse_run_id=pr.id
                  AND a.filing_id=f.id AND a.outcome IN ('parse_failed','parse_reused_failed'))
                AND EXISTS (SELECT 1 FROM sec_financial_acquisition_resolutions r WHERE r.parse_run_id=pr.id
                  AND r.accession_no=f.accession_no AND r.resolution_kind='parse_failed'))"""),
              {"parse":source.parse_run_id}).scalar_one()
        if row is None or (row.status != "succeeded" and not exact_failed_amendment) or row.filing_id != source.filing_id or row.accession_no != source.accession_no \
                or row.parser_version != source.parser_version or row.input_manifest_hash != source.input_manifest_hash \
                or row.available_at != source.available_at or row.stock_id != request.stock_id \
                or row.issuer_identity_id != request.issuer_identity_id or max(row.known_at, row.filing_known_at, row.available_at) > request.requested_cutoff:
            raise SecPublicationError("selected source is outside finalized exact publication authority")
        if exact_failed_amendment:
            failed_amendment_ids.append(source.parse_run_id)
        selected_filing_ids.append(source.accession_no)
    rows = db.execute(text("""SELECT raw.id AS raw_fact_id,raw.parse_run_id,raw.concept_namespace_uri,
          CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END AS local_name,
          norm.id AS normalization_id,norm.normalized_value,raw.unit_numerator_json,raw.unit_denominator_json,
          raw.context_id,raw.dimensions_structured_json,f.form_type,raw.period_start,
          coalesce(raw.period_end,raw.period_instant) AS period_end,raw.is_nil,f.accession_no,
          greatest(pr.known_at,f.known_at,auth.known_at,coalesce(norm.created_at,auth.known_at)) AS known_at,
          auth.presentation_class,auth.statement_period_end,auth.fiscal_year,auth.fiscal_quarter_ordinal,
          auth.fiscal_year_start,auth.report_ordinal,auth.occurrence_ordinal
          ,auth.id AS statement_authority_id,auth.statement_report_reference_id,
          auth.statement_artifact_id,auth.statement_sha256,auth.occurrence_fact_id,
          auth.occurrence_semantic_sha256,auth.locator_json AS occurrence_locator_json,
          occ.row_ordinal,occ.column_ordinal,occ.locator_json AS evidence_locator_json,
          ref.filing_summary_artifact_id,ref.filing_summary_sha256,ref.report_artifact_id,ref.report_sha256
        FROM sec_raw_xbrl_facts raw
        JOIN sec_financial_parse_runs pr ON pr.id=raw.parse_run_id
        JOIN sec_financial_filings f ON f.id=pr.filing_id
        JOIN sec_statement_fact_authorities auth ON auth.raw_fact_id=raw.id AND auth.parse_run_id=raw.parse_run_id
        JOIN sec_statement_occurrence_evidence occ ON occ.id=auth.statement_occurrence_id
        JOIN sec_statement_report_references ref ON ref.id=auth.statement_report_reference_id
        LEFT JOIN LATERAL (SELECT n.* FROM sec_raw_numeric_normalizations n
          JOIN sec_metric_mapping_rules mr ON mr.id=n.mapping_rule_id
          WHERE n.raw_fact_id=raw.id AND n.mapping_version_id=:mapping
            AND mr.metadata_json->'ordered_concepts' ? CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END
          ORDER BY n.id LIMIT 1) norm ON true
        WHERE raw.parse_run_id=ANY(:parses)
        ORDER BY raw.id,auth.report_ordinal,auth.occurrence_ordinal"""),
        {"mapping": request.mapping_version_id, "parses": list(source_ids)}).mappings().all()
    by_raw: dict[int, list[object]] = {}
    for row in rows:
        by_raw.setdefault(row.raw_fact_id, []).append(row)
    if not by_raw and not failed_amendment_ids:
        raise SecPublicationError("selected source has no exact statement presentation authority")
    facts = []
    for raw_id in sorted(by_raw):
        first = by_raw[raw_id][0]
        base = RawFactSnapshot(
            first.raw_fact_id, first.parse_run_id, first.normalization_id,
            first.concept_namespace_uri, first.local_name, first.normalized_value,
            tuple(first.unit_numerator_json or ()), tuple(first.unit_denominator_json or ()),
            first.context_id or "", tuple(first.dimensions_structured_json or ()), first.form_type,
            first.period_start, first.period_end, first.statement_period_end, first.fiscal_year,
            first.fiscal_quarter_ordinal, first.fiscal_year_start, request.stock_id,
            first.accession_no, request.requested_cutoff, "unadapted", request.amendment_policy,
            first.known_at, first.is_nil,
            tuple({
                "statement_authority_id":row.statement_authority_id,
                "statement_report_reference_id":row.statement_report_reference_id,
                "statement_artifact_id":row.statement_artifact_id,
                "statement_sha256":row.statement_sha256,
                "filing_summary_artifact_id":row.filing_summary_artifact_id,
                "filing_summary_sha256":row.filing_summary_sha256,
                "report_artifact_id":row.report_artifact_id,
                "report_sha256":row.report_sha256,
                "occurrence_fact_id":row.occurrence_fact_id,
                "occurrence_semantic_sha256":row.occurrence_semantic_sha256,
                "report_ordinal":row.report_ordinal,"occurrence_ordinal":row.occurrence_ordinal,
                "row_ordinal":row.row_ordinal,"column_ordinal":row.column_ordinal,
                "locator_json":row.occurrence_locator_json,
                "evidence_locator_json":row.evidence_locator_json,
                "raw_fact_id":row.raw_fact_id,"parse_run_id":row.parse_run_id,
                "normalization_id":row.normalization_id,
            } for row in by_raw[raw_id]),
        )
        authorities = tuple(StatementAuthoritySnapshot(
            row.raw_fact_id, row.parse_run_id, row.context_id or "", row.presentation_class,
            row.statement_period_end, row.fiscal_year, row.fiscal_quarter_ordinal,
            row.fiscal_year_start, row.report_ordinal, row.occurrence_ordinal,
        ) for row in by_raw[raw_id])
        facts.append(authoritative_raw_fact_snapshot(base, authorities))
    authority = MappingRunAuthority(
        request.requested_cutoff,
        tuple(selected_filing_ids),
        request.amendment_policy,
        resolved.filing_cycles,
    )
    mapped = map_sec_financial_snapshot(mapping, facts, authority)
    if failed_amendment_ids:
        # No caller may invent affected slots for a raw-less failed amendment.
        # Without exact occurrence authority the only defensible result is a
        # run-level, slotless typed audit which cannot demote canonical truth.
        failed = tuple(
            TypedDisposition(
                "unresolved_amendment_parse_failure",
                (),
                None,
                detail="selected_failed_amendment_parse_run=" + str(parse_run_id),
            )
            for parse_run_id in failed_amendment_ids
        )
        mapped = MappingResult(
            mapped.candidates,
            mapped.dispositions + failed,
            mapped.truncated_decision_count,
        )
    if len(mapped.candidates) + len(mapped.dispositions) > MAX_PUBLICATION_DECISIONS:
        raise SecPublicationError("mapping decision audit exceeds bounded contract")
    return mapped


def publish_sec_mapping_result(db: Session, request: PublicationRequest) -> PublicationReceipt:
    """Rebuild and write canonical truth atomically; finalize visibility later."""
    if not request.sources or request.requested_cutoff.tzinfo is None:
        raise SecPublicationError("explicit ordered sources and aware cutoff are required")
    # Authority resolution, exact replay identity, and current-slot writes must
    # observe one serial stock snapshot.  Lineage availability finalization
    # takes this identical transaction lock before exposing a new source.
    acquire_sec_financial_stock_lock(db, stock_id=request.stock_id)
    outcome = _rebuild_mapping_result(db, request)
    if request.outcome is not None and request.outcome != outcome:
        raise SecPublicationError("expected mapping result differs from database authority")
    if outcome.truncated_decision_count:
        raise SecPublicationError("mapping decision audit exceeded bounded publication contract")
    authoritative_request = PublicationRequest(
        request.stock_id, request.issuer_identity_id, request.mapping_version_id,
        request.requested_cutoff, request.amendment_policy, request.sources, outcome,
    )
    run_id, source_digest = _identity(authoritative_request)
    rules = {row.rule_id: row for row in db.execute(text("SELECT id,rule_id,metric_key,target_unit,period_policy FROM sec_metric_mapping_rules WHERE mapping_version_id=:v"), {"v": request.mapping_version_id}).mappings()}
    if not rules:
        raise SecPublicationError("approved mapping rules unavailable")
    referenced_rule_ids = {item.mapping_rule_id for item in outcome.candidates}
    referenced_rule_ids.update(item.mapping_rule_id for item in outcome.dispositions if item.mapping_rule_id is not None)
    if not referenced_rule_ids <= rules.keys():
        raise SecPublicationError("publication outcome references an unregistered mapping rule")
    publishable = sorted(outcome.candidates, key=lambda candidate: (candidate.derivation_kind != "direct", candidate.metric_key, candidate.period_end, candidate.raw_fact_ids))
    unresolved = [item for item in outcome.dispositions if item.slot is not None]
    audits = [item for item in outcome.dispositions if item.slot is None]
    selected_parse_ids = {source.parse_run_id for source in request.sources}
    for candidate in publishable:
        if candidate.stock_id != request.stock_id or candidate.publication_cutoff != request.requested_cutoff or not set(candidate.parse_run_ids) <= selected_parse_ids:
            raise SecPublicationError("candidate outside selected publication authority")
    for item in unresolved:
        slot = item.slot
        rule = rules.get(slot.mapping_rule_id)
        if (rule is None or slot.stock_id != request.stock_id or slot.metric_key != rule.metric_key
                or slot.publication_cutoff != request.requested_cutoff or not set(slot.parse_run_ids) <= selected_parse_ids):
            raise SecPublicationError("unavailable slot outside selected publication authority")
        if True:
            if not slot.raw_fact_ids or item.raw_fact_ids != slot.raw_fact_ids:
                raise SecPublicationError("raw-backed unavailable slot requires exact raw evidence")
            derived_unavailable = (
                len(slot.raw_fact_ids) == 2
                and (
                    item.reason.startswith("unresolved_derived_")
                    or item.reason == "unresolved_value"
                )
            )
            raw_parse_ids: set[int] = set()
            ordered_raw_authority = []
            for raw_id in slot.raw_fact_ids:
                raw_authority = db.execute(text("""SELECT raw.id AS raw_fact_id,raw.parse_run_id,raw.period_start,
                    coalesce(raw.period_end,raw.period_instant) AS period_end,raw.period_instant,
                    raw.context_id,raw.dimensions_structured_json,raw.unit_numerator_json,raw.unit_denominator_json,
                    f.form_type,f.report_date
                  FROM sec_raw_xbrl_facts raw
                  JOIN sec_financial_parse_runs pr ON pr.id=raw.parse_run_id
                  JOIN sec_financial_filings f ON f.id=pr.filing_id
                  JOIN sec_issuer_identities i ON i.id=f.issuer_identity_id
                  WHERE raw.id=:raw AND raw.parse_run_id=ANY(:parses) AND i.stock_id=:stock
                    AND pr.known_at<=:cutoff AND f.known_at<=:cutoff
                    AND (:derived OR (
                      raw.context_id IS NOT DISTINCT FROM :context
                      AND raw.period_start IS NOT DISTINCT FROM :pstart
                      AND coalesce(raw.period_end,raw.period_instant)=:pend))
                    AND EXISTS (SELECT 1 FROM sec_metric_mapping_rules rule
                      JOIN sec_metric_mapping_version_namespaces ns ON ns.mapping_version_id=rule.mapping_version_id
                       AND ns.authority=rule.concept_namespace_authority AND ns.namespace_uri=raw.concept_namespace_uri
                      WHERE rule.id=:rule AND rule.mapping_version_id=:mapping
                       AND rule.metadata_json->'ordered_concepts' ? CASE WHEN strpos(raw.concept,':')>0 THEN split_part(raw.concept,':',2) ELSE raw.concept END)"""),
                  {"raw": raw_id, "parses": list(selected_parse_ids), "stock": request.stock_id, "context": slot.context_id,
                   "pstart": slot.period_start, "pend": slot.period_end, "rule": rule.id, "mapping": request.mapping_version_id,
                   "cutoff": request.requested_cutoff,
                   "derived": derived_unavailable}).mappings().one_or_none()
                if raw_authority is None:
                    raise SecPublicationError("unavailable slot raw evidence outside selected authority")
                raw_parse_ids.add(raw_authority.parse_run_id)
                ordered_raw_authority.append(raw_authority)
                if derived_unavailable:
                    continue
                raw_dimensions = raw_authority.dimensions_structured_json or []
                if _canonical(raw_dimensions) != _canonical(slot.dimensions):
                    raise SecPublicationError("unavailable slot dimensions outside exact raw authority")
                is_instant = raw_authority.period_instant is not None
                if slot.period_basis != ("instant" if is_instant else "duration"):
                    raise SecPublicationError("unavailable slot period basis outside exact raw authority")
                days = None if is_instant else (slot.period_end - slot.period_start).days + 1
                if raw_authority.form_type in ("10-K", "10-K/A", "20-F", "20-F/A"):
                    period_shape_ok = slot.period_type == "FY" and slot.fiscal_quarter_ordinal is None and (is_instant or 300 <= days <= 380)
                elif raw_authority.form_type in ("10-Q", "10-Q/A"):
                    instant_shape_ok = is_instant and ((slot.period_end == raw_authority.report_date and slot.period_type == "Q" and slot.fiscal_quarter_ordinal is not None) or
                        (slot.period_end < raw_authority.report_date and slot.period_type == "FY" and slot.fiscal_quarter_ordinal is None))
                    period_shape_ok = (instant_shape_ok or
                        (not is_instant and slot.period_type == "Q" and 70 <= days <= 110) or
                        (not is_instant and slot.period_type == "YTD" and slot.fiscal_quarter_ordinal == 2 and 150 <= days <= 210) or
                        (not is_instant and slot.period_type == "YTD" and slot.fiscal_quarter_ordinal == 3 and 240 <= days <= 300))
                else:
                    period_shape_ok = False
                if not period_shape_ok or slot.fiscal_year != slot.period_end.year:
                    raise SecPublicationError("unavailable slot fiscal period outside exact filing authority")
                numerator = raw_authority.unit_numerator_json or []
                denominator = raw_authority.unit_denominator_json or []
                if rule.target_unit in ("currency", "currency_per_share"):
                    unit_shape_ok = len(numerator) == 1 and numerator[0].get("namespace_uri") == "http://www.xbrl.org/2003/iso4217"
                    unit_shape_ok = unit_shape_ok and ((rule.target_unit == "currency" and not denominator) or
                        (rule.target_unit == "currency_per_share" and len(denominator) == 1 and denominator[0].get("namespace_uri") == "http://www.xbrl.org/2003/instance" and denominator[0].get("local_name") == "shares"))
                    currency_ok = unit_shape_ok and db.execute(text("""SELECT 1 FROM sec_metric_mapping_version_currencies
                      WHERE mapping_version_id=:mapping AND currency_code=:currency"""),
                      {"mapping": request.mapping_version_id, "currency": numerator[0].get("local_name")}).scalar_one_or_none() is not None
                else:
                    unit_shape_ok = len(numerator) == 1 and numerator[0].get("namespace_uri") == "http://www.xbrl.org/2003/instance" and numerator[0].get("local_name") == "shares" and not denominator
                    currency_ok = unit_shape_ok
                if item.reason == "unresolved_unit":
                    reason_matches_unit = not unit_shape_ok
                elif item.reason == "unresolved_currency":
                    reason_matches_unit = rule.target_unit in ("currency", "currency_per_share") and unit_shape_ok and not currency_ok
                else:
                    reason_matches_unit = unit_shape_ok and currency_ok
                if not reason_matches_unit:
                    raise SecPublicationError("unavailable slot unit outside exact raw authority")
            if derived_unavailable:
                _validate_derived_unavailable_slot(
                    slot, tuple(ordered_raw_authority)
                )
            if raw_parse_ids != set(slot.parse_run_ids):
                raise SecPublicationError("unavailable slot parse set outside exact raw authority")
    existing = db.execute(text("SELECT status FROM sec_metric_publication_runs WHERE id=:id FOR UPDATE"), {"id": run_id}).scalar_one_or_none()
    if existing is not None:
        if existing != "succeeded":
            raise SecPublicationError("existing publication run is not succeeded")
        available = db.execute(text("SELECT 1 FROM sec_metric_publication_availabilities WHERE publication_run_id=:id"), {"id": run_id}).scalar_one_or_none() is not None
        facts = tuple(db.execute(text("SELECT metric_fact_id FROM sec_metric_publications WHERE publication_run_id=:id AND metric_fact_id IS NOT NULL ORDER BY decision_ordinal"), {"id": run_id}).scalars())
        return PublicationReceipt(run_id, True, available, facts)

    db.execute(text("""INSERT INTO sec_metric_publication_runs
      (id,stock_id,issuer_identity_id,mapping_version_id,requested_cutoff,amendment_policy,source_set_sha256,status,published_count,unresolved_count,rejected_count)
      VALUES (:id,:stock,:issuer,:mapping,:cutoff,:policy,:digest,'succeeded',:published,:unresolved,:rejected)"""),
      {"id":run_id,"stock":request.stock_id,"issuer":request.issuer_identity_id,"mapping":request.mapping_version_id,
       "cutoff":request.requested_cutoff,"policy":request.amendment_policy,"digest":source_digest,
       "published":len(publishable),"unresolved":len(unresolved),"rejected":len(audits)})
    first_rule_id = next(iter(rules.values())).id
    source_ids: dict[int, int] = {}
    for ordinal, source in enumerate(request.sources, 1):
        source_id = db.execute(text("SELECT nextval('sec_metric_publication_run_sources_id_seq')")).scalar_one()
        db.execute(text("""INSERT INTO sec_metric_publication_run_sources
          (id,publication_run_id,mapping_rule_id,source_ordinal,parse_run_id,filing_id,accession_no,parser_version,input_manifest_hash,source_available_at)
          VALUES (:id,:run,:rule,:ordinal,:parse,:filing,:accession,:parser,:manifest,:available)"""),
          {"id":source_id,"run":run_id,"rule":first_rule_id,"ordinal":ordinal,"parse":source.parse_run_id,"filing":source.filing_id,
           "accession":source.accession_no,"parser":source.parser_version,"manifest":source.input_manifest_hash,"available":source.available_at})
        source_ids[source.parse_run_id] = source_id
    direct_by_raw: dict[int, int] = {}
    fact_ids: list[int] = []
    for ordinal, candidate in enumerate(publishable, 1):
        rule = rules[candidate.mapping_rule_id]
        decision_id = db.execute(text("SELECT nextval('sec_metric_publications_id_seq')")).scalar_one()
        fact_id = db.execute(text("SELECT nextval('metric_facts_id_seq')")).scalar_one()
        dimensions_hash = hashlib.sha256(b"[]").hexdigest()
        if not candidate.occurrence_authorities:
            raise SecPublicationError("candidate lacks exact statement occurrence provenance")
        locator_payload = candidate.occurrence_authorities[0] if candidate.derivation_kind == "direct" else {
            "derivation_kind":candidate.derivation_kind,
            "ordered_input_occurrences":list(candidate.occurrence_authorities),
        }
        audit_payload = {"ordered_input_occurrences":list(candidate.occurrence_authorities)}
        source_role = "primary_as_filed_actual" if candidate.derivation_kind == "direct" else "derived_actual"
        db.execute(text("""INSERT INTO sec_metric_publications
          (id,publication_run_id,mapping_rule_id,decision_ordinal,status,reason_code,stock_id,metric_key,period_type,period_end_date,fiscal_year,fiscal_quarter_ordinal,period_start_date,period_basis,value_numeric,unit,currency,source_role,fact_nature,derivation_kind,context_id,dimensions_policy,dimensions_sha256,locator_json,audit_json,metric_fact_id)
          VALUES (:id,:run,:rule,:ordinal,'published','published',:stock,:metric,:ptype,:pend,:fy,:fq,:pstart,:basis,:value,:unit,:currency,:role,:nature,:derivation,:context,'empty_only_v1',:dimensions,CAST(:locator AS jsonb),CAST(:audit AS jsonb),:fact)"""),
          {"id":decision_id,"run":run_id,"rule":rule.id,"ordinal":ordinal,"stock":request.stock_id,"metric":candidate.metric_key,
           "ptype":candidate.period_type,"pend":candidate.period_end,"fy":candidate.fiscal_year,"fq":candidate.fiscal_quarter_ordinal,
           "pstart":candidate.period_start,"basis":"instant" if candidate.period_start is None else "duration","value":candidate.value,
           "unit":candidate.unit,"currency":candidate.currency,"role":source_role,"nature":"actual" if candidate.derivation_kind=="direct" else "derived_actual",
           "derivation":candidate.derivation_kind,"context":candidate.context_id,"dimensions":dimensions_hash,
           "locator":json.dumps(locator_payload),"audit":json.dumps(audit_payload),"fact":fact_id})
        db.execute(text("""UPDATE metric_facts SET is_current=false
          WHERE source_type='sec' AND is_current=true AND stock_id=:stock AND metric_key=:metric
            AND period_type=:ptype AND period_end_date=:pend"""),
          {"stock":request.stock_id,"metric":candidate.metric_key,"ptype":candidate.period_type,"pend":candidate.period_end})
        db.execute(text("""INSERT INTO metric_facts
          (id,user_id,stock_id,metric_key,value_json,value_numeric,unit,currency,period,period_type,period_end_date,as_of_date,source_document_id,source_type,source_ref_id,is_current)
          VALUES (:id,NULL,:stock,:metric,:json,:value,:unit,:currency,:period,:ptype,:pend,:pend,NULL,'sec',:source,true)"""),
          {"id":fact_id,"stock":request.stock_id,"metric":candidate.metric_key,"json":json.dumps({"publication_run_id":run_id,"decision_id":decision_id,"source_role":source_role,"locator":locator_payload}),
           "value":candidate.value,"unit":candidate.unit,"currency":candidate.currency,"period":candidate.period_type,"ptype":candidate.period_type,"pend":candidate.period_end,"source":decision_id})
        if candidate.derivation_kind == "direct":
            raw_id, normalization_id, parse_id = candidate.raw_fact_ids[0], candidate.normalization_ids[0], candidate.parse_run_ids[0]
            db.execute(text("""INSERT INTO sec_metric_publication_inputs
              (publication_id,input_ordinal,input_role,run_source_id,raw_fact_id,normalization_id,arithmetic_sign)
              VALUES (:publication,1,'direct',:source,:raw,:normalization,1)"""),
              {"publication":decision_id,"source":source_ids[parse_id],"raw":raw_id,"normalization":normalization_id})
            direct_by_raw[raw_id] = decision_id
        else:
            for input_ordinal, (role, sign, raw_id) in enumerate((("left_operand",1,candidate.raw_fact_ids[0]),("right_operand",-1,candidate.raw_fact_ids[1])), 1):
                if raw_id not in direct_by_raw: raise SecPublicationError("derived input is not an earlier direct decision")
                db.execute(text("INSERT INTO sec_metric_publication_inputs (publication_id,input_ordinal,input_role,source_publication_id,arithmetic_sign) VALUES (:publication,:ordinal,:role,:source,:sign)"),
                           {"publication":decision_id,"ordinal":input_ordinal,"role":role,"source":direct_by_raw[raw_id],"sign":sign})
        fact_ids.append(fact_id)
    for offset, item in enumerate(unresolved, len(publishable) + 1):
        slot = item.slot
        rule = rules[slot.mapping_rule_id]
        dimensions_hash = hashlib.sha256(json.dumps(slot.dimensions, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
        db.execute(text("""UPDATE metric_facts SET is_current=false
          WHERE source_type='sec' AND is_current=true AND stock_id=:stock AND metric_key=:metric
            AND period_type=:ptype AND period_end_date=:pend"""),
          {"stock":slot.stock_id,"metric":slot.metric_key,"ptype":slot.period_type,"pend":slot.period_end})
        if not slot.occurrence_authorities:
            raise SecPublicationError("slot-aware unresolved decision lacks exact occurrence provenance")
        unresolved_locator={"ordered_input_occurrences":list(slot.occurrence_authorities)}
        decision_id=db.execute(text("SELECT nextval('sec_metric_publications_id_seq')")).scalar_one()
        db.execute(text("""INSERT INTO sec_metric_publications
          (id,publication_run_id,mapping_rule_id,decision_ordinal,status,reason_code,stock_id,metric_key,period_type,period_end_date,fiscal_year,fiscal_quarter_ordinal,period_start_date,period_basis,value_numeric,unit,currency,source_role,fact_nature,derivation_kind,context_id,dimensions_policy,dimensions_sha256,locator_json,audit_json)
          VALUES (:id,:run,:rule,:ordinal,'unresolved',:reason,:stock,:metric,:ptype,:pend,:fy,:fq,:pstart,:basis,NULL,NULL,NULL,'unresolved','actual','unresolved',:context,'empty_only_v1',:dimensions,CAST(:locator AS jsonb),CAST(:audit AS jsonb))"""),
          {"id":decision_id,"run":run_id,"rule":rule.id,"ordinal":offset,"reason":item.reason,"stock":slot.stock_id,"metric":slot.metric_key,
           "ptype":slot.period_type,"pend":slot.period_end,"fy":slot.fiscal_year,"fq":slot.fiscal_quarter_ordinal,
           "pstart":slot.period_start,"basis":slot.period_basis,"context":slot.context_id,"dimensions":dimensions_hash,
           "locator":json.dumps(unresolved_locator),"audit":json.dumps({
               "raw_fact_ids":[item["raw_fact_id"] for item in slot.occurrence_authorities],
               "parse_run_ids":[item["parse_run_id"] for item in slot.occurrence_authorities],
               "normalization_ids":[item.get("normalization_id") for item in slot.occurrence_authorities],
               "statement_authority_ids":[item["statement_authority_id"] for item in slot.occurrence_authorities],
               "cutoff":slot.publication_cutoff.isoformat(),**unresolved_locator})})
        for input_ordinal, provenance in enumerate(slot.occurrence_authorities,1):
            db.execute(text("""INSERT INTO sec_metric_publication_unresolved_inputs
              (publication_id,input_ordinal,run_source_id,raw_fact_id,statement_authority_id,normalization_id)
              VALUES (:publication,:ordinal,:source,:raw,:authority,:normalization)"""),
              {"publication":decision_id,"ordinal":input_ordinal,"source":source_ids[provenance["parse_run_id"]],
               "raw":provenance["raw_fact_id"],"authority":provenance["statement_authority_id"],
               "normalization":provenance.get("normalization_id")})
    for audit_ordinal, item in enumerate(audits, 1):
        rule_id = rules[item.mapping_rule_id].id if item.mapping_rule_id is not None else None
        db.execute(text("""INSERT INTO sec_metric_publication_audits
          (publication_run_id,mapping_rule_id,audit_ordinal,reason_code,raw_fact_ids_json,detail)
          VALUES (:run,:rule,:ordinal,:reason,CAST(:raw AS jsonb),:detail)"""),
          {"run":run_id,"rule":rule_id,"ordinal":audit_ordinal,"reason":item.reason,
           "raw":json.dumps(list(item.raw_fact_ids)),"detail":item.detail})
    return PublicationReceipt(run_id, False, False, tuple(fact_ids))


def finalize_sec_publication(db: Session, run_id: str) -> PublicationReceipt:
    """Idempotently expose a previously committed succeeded publication."""
    status = db.execute(text("SELECT status FROM sec_metric_publication_runs WHERE id=:id FOR UPDATE"), {"id": run_id}).scalar_one_or_none()
    if status != "succeeded":
        raise SecPublicationError("only a committed succeeded publication can be finalized")
    db.execute(text("INSERT INTO sec_metric_publication_availabilities (publication_run_id) VALUES (:id) ON CONFLICT DO NOTHING"), {"id":run_id})
    facts = tuple(db.execute(text("SELECT metric_fact_id FROM sec_metric_publications WHERE publication_run_id=:id AND metric_fact_id IS NOT NULL ORDER BY decision_ordinal"), {"id":run_id}).scalars())
    return PublicationReceipt(run_id, True, True, facts)
