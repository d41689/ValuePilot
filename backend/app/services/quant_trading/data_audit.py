"""Read-only data sufficiency and statistical-power audit for quant Phase 1.

The planning approximation implemented here is intentionally conservative and
transparent. For a one-sided threshold ``t >= c``, annual alpha ``a``, annual
tracking error ``s`` and target rejection probability ``p`` under the stated
alternative, the normal approximation requires non-centrality

    lambda = c + Phi^-1(p)

and effective holdout years ``((lambda * s) / a) ** 2``. HAC is used by the
eventual spanning regression; this calculation is a *planning approximation*,
not a replacement for realized Newey-West standard errors or a simulation based
on the acquired return series.

Primary references:
- Newey & West, NBER TWP 0055 / Econometrica 55 (1987):
  https://www.nber.org/papers/t0055
- Statsmodels power API (power = 1 - type-II error):
  https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html
- SEC Form 13F instructions and official dataset notes:
  https://www.sec.gov/files/form13f.pdf
  https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta, timezone
import math
import re
from statistics import NormalDist, median
from typing import Any

from sqlalchemy import and_, func, or_, text, tuple_
from sqlalchemy.orm import Session

from app.models.artifacts import ValueLineDocumentReportIdentityRevision
from app.models.facts import MetricFact
from app.models.institutions import Filing13F, Holding13F, ParseRun13F
from app.models.stocks import StockPrice
from app.services.evaluation_snapshot import (
    database_evaluation_snapshot,
    transaction_visible_in_snapshot_predicate,
)
from app.services.thirteenf_filing_detail import competition_pool
from app.services.thirteenf_holdings_query import HR_FORM_TYPES


POLICY_VERSION = "quant-1-r0a-v1"
_DAYS_PER_YEAR = 365.2425


@dataclass(frozen=True)
class PowerAssumptions:
    """Pre-registered planning inputs, not fitted backtest parameters."""

    annual_alpha: float = 0.02
    target_power: float = 0.80
    holdout_fraction: float = 0.30
    t_threshold: float = 3.0
    tracking_error_low: float = 0.04
    tracking_error_high: float = 0.06
    minimum_cross_sectional_stocks: int = 100
    minimum_13f_managers: int = 20
    minimum_13f_mapped_stocks: int = 100

    def __post_init__(self) -> None:
        if self.annual_alpha <= 0:
            raise ValueError("annual_alpha must be positive")
        if not 0 < self.target_power < 1:
            raise ValueError("target_power must be between 0 and 1")
        if not 0 < self.holdout_fraction <= 1:
            raise ValueError("holdout_fraction must be in (0, 1]")
        if self.t_threshold <= 0:
            raise ValueError("t_threshold must be positive")
        if self.tracking_error_low <= 0 or self.tracking_error_high <= 0:
            raise ValueError("tracking errors must be positive")
        if self.tracking_error_low > self.tracking_error_high:
            raise ValueError("tracking_error_low cannot exceed tracking_error_high")
        if self.minimum_cross_sectional_stocks < 1:
            raise ValueError("minimum_cross_sectional_stocks must be positive")
        if self.minimum_13f_managers < 1 or self.minimum_13f_mapped_stocks < 1:
            raise ValueError("13F breadth floors must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_POWER_ASSUMPTIONS = PowerAssumptions()


@dataclass(frozen=True)
class SourceReadiness:
    """Operator-evidenced external source state.

    Defaults are deliberately all false. A credential, local row, or CLI flag
    is not evidence of a commercial license or a survivorship-free universe.
    """

    backbone_authorized: bool = False
    backbone_authorization_evidence_ref: str | None = None
    backbone_survivorship_free: bool = False
    backbone_includes_delisted: bool = False
    backbone_has_fundamentals: bool = False
    backbone_has_prices: bool = False
    backbone_start_date: date | None = None
    backbone_end_date: date | None = None
    backbone_minimum_monthly_stock_breadth: int = 0
    value_line_automation_authorized: bool = False
    value_line_authorization_evidence_ref: str | None = None

    def __post_init__(self) -> None:
        if self.backbone_authorized and not (self.backbone_authorization_evidence_ref or "").strip():
            raise ValueError("authorized backbone requires an evidence reference")
        if self.value_line_automation_authorized and not (
            self.value_line_authorization_evidence_ref or ""
        ).strip():
            raise ValueError("authorized Value Line automation requires an evidence reference")
        if (self.backbone_start_date is None) != (self.backbone_end_date is None):
            raise ValueError("backbone coverage requires both start and end dates")
        if (
            self.backbone_start_date is not None
            and self.backbone_end_date is not None
            and self.backbone_end_date < self.backbone_start_date
        ):
            raise ValueError("backbone_end_date cannot precede backbone_start_date")
        if self.backbone_minimum_monthly_stock_breadth < 0:
            raise ValueError("backbone breadth cannot be negative")

    @property
    def backbone_span_years(self) -> float:
        return _span_years(self.backbone_start_date, self.backbone_end_date)

    def to_dict(self) -> dict[str, Any]:
        values = asdict(self)
        for field in ("backbone_start_date", "backbone_end_date"):
            value = values[field]
            values[field] = value.isoformat() if value else None
        values["backbone_span_years"] = round(self.backbone_span_years, 6)
        return values


def _span_years(start: date | None, end: date | None) -> float:
    if start is None or end is None or end < start:
        return 0.0
    return (end - start).days / _DAYS_PER_YEAR


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _power_scenario(
    *,
    assumptions: PowerAssumptions,
    tracking_error_annual: float,
    periods_per_year: int,
) -> dict[str, Any]:
    z_power = NormalDist().inv_cdf(assumptions.target_power)
    required_noncentrality = assumptions.t_threshold + z_power
    effective_years = (
        required_noncentrality * tracking_error_annual / assumptions.annual_alpha
    ) ** 2
    holdout_periods = math.ceil(effective_years * periods_per_year)
    total_periods = math.ceil(holdout_periods / assumptions.holdout_fraction)
    expected_t_only_years = (
        assumptions.t_threshold * tracking_error_annual / assumptions.annual_alpha
    ) ** 2
    return {
        "tracking_error_annual": tracking_error_annual,
        "required_noncentrality": round(required_noncentrality, 9),
        "required_effective_holdout_years": round(effective_years, 6),
        "required_holdout_periods": holdout_periods,
        "required_total_calendar_periods": total_periods,
        "required_total_calendar_years": round(total_periods / periods_per_year, 6),
        "expected_t_only_years_50pct_power": round(expected_t_only_years, 6),
    }


def build_power_plans(
    assumptions: PowerAssumptions = DEFAULT_POWER_ASSUMPTIONS,
) -> dict[str, dict[str, Any]]:
    """Return deterministic H1/H2/H3 power plans.

    H1 and H2 use monthly signal-portfolio returns. H3 is quarterly because a
    manager's holdings become observable only when the filing is public. The
    selected TE is pre-registered at 4% for H1/H2 and 6% for the sparser H3;
    both 4% and 6% scenarios remain visible as sensitivity bounds.
    """

    specs = {
        "H1": ("monthly", 12, assumptions.tracking_error_low),
        "H2": ("monthly", 12, assumptions.tracking_error_low),
        "H3": ("quarterly", 4, assumptions.tracking_error_high),
    }
    plans: dict[str, dict[str, Any]] = {}
    for hypothesis, (frequency, periods_per_year, selected_te) in specs.items():
        scenarios = [
            _power_scenario(
                assumptions=assumptions,
                tracking_error_annual=tracking_error,
                periods_per_year=periods_per_year,
            )
            for tracking_error in (
                assumptions.tracking_error_low,
                assumptions.tracking_error_high,
            )
        ]
        selected = next(
            scenario
            for scenario in scenarios
            if scenario["tracking_error_annual"] == selected_te
        )
        plans[hypothesis] = {
            "observation_frequency": frequency,
            "periods_per_year": periods_per_year,
            "selected_tracking_error_annual": selected_te,
            "selected_scenario": selected,
            "sensitivity_scenarios": scenarios,
            "breadth_policy": {
                "statistically_fungible_with_time": False,
                "minimum_cross_sectional_stocks": assumptions.minimum_cross_sectional_stocks,
                "note": (
                    "Breadth is an operational cross-sectional eligibility floor; "
                    "it does not replace HAC return-history observations."
                ),
            },
        }
    return plans


def filing_lag_days(period_end: date, filed_at: date) -> int:
    lag = (filed_at - period_end).days
    if lag < 0:
        raise ValueError("13F filed_at is before period end")
    return lag


_ISOLATED_TEST_DATABASE_PATTERN = re.compile(
    r"valuepilot_test_[a-z0-9]+(?:_[a-z0-9]+)*"
)


def validate_audit_database_name(database_name: str | None) -> str:
    """Allow only canonical dev or a strictly named isolated test database."""

    is_isolated_test = (
        database_name is not None
        and len(database_name) <= 63
        and _ISOLATED_TEST_DATABASE_PATTERN.fullmatch(database_name) is not None
    )
    if database_name != "valuepilot" and not is_isolated_test:
        raise RuntimeError(
            "quant data audit may run only against the development or isolated "
            "test database"
        )
    return database_name


def begin_read_only_development_audit(session: Session) -> str:
    """Pin the audit to dev/test and make PostgreSQL reject writes."""

    bind = session.get_bind()
    url = getattr(bind, "url", None)
    if url is None and getattr(bind, "engine", None) is not None:
        url = bind.engine.url
    database_name = validate_audit_database_name(
        getattr(url, "database", None) if url is not None else None
    )
    session.execute(text("SET TRANSACTION READ ONLY"))
    return database_name


def _longest_consecutive_weeks(report_dates: list[date]) -> int:
    mondays = sorted({day - timedelta(days=day.weekday()) for day in report_dates})
    longest = 0
    current = 0
    previous: date | None = None
    for monday in mondays:
        if previous is not None and monday - previous == timedelta(days=7):
            current += 1
        else:
            current = 1
        longest = max(longest, current)
        previous = monday
    return longest


def _metric_fact_coverage(
    session: Session,
    *,
    user_id: int,
    knowledge_cutoff: datetime,
    knowledge_txid_snapshot: str | None = None,
) -> dict[str, Any]:
    if knowledge_txid_snapshot is None:
        knowledge_txid_snapshot = database_evaluation_snapshot(
            session, knowledge_cutoff
        ).visibility_snapshot
    identity = ValueLineDocumentReportIdentityRevision
    scope = (
        MetricFact.user_id == user_id,
        MetricFact.source_type == "parsed",
        MetricFact.source_document_id.is_not(None),
        or_(
            MetricFact.value_line_created_txid.is_(None),
            transaction_visible_in_snapshot_predicate(
                MetricFact.value_line_created_txid,
                visibility_snapshot=knowledge_txid_snapshot,
                bind_name="quant_fact_visibility_snapshot",
            ),
        ),
    )
    mismatch = or_(
        MetricFact.value_line_report_identity_revision_id.is_(None),
        MetricFact.value_line_fact_known_at.is_(None),
        identity.id.is_(None),
        and_(
            identity.id.is_not(None),
            ~transaction_visible_in_snapshot_predicate(
                identity.created_txid,
                visibility_snapshot=knowledge_txid_snapshot,
                bind_name="quant_identity_mismatch_visibility_snapshot",
            ),
        ),
        identity.document_id != MetricFact.source_document_id,
        identity.user_id != MetricFact.user_id,
        and_(identity.stock_id.is_not(None), identity.stock_id != MetricFact.stock_id),
        and_(
            MetricFact.value_line_created_txid.is_(None),
            or_(
                MetricFact.value_line_fact_known_at > knowledge_cutoff,
                identity.known_at > knowledge_cutoff,
            ),
        ),
        and_(
            MetricFact.value_line_created_txid.is_not(None),
            MetricFact.value_line_fact_known_at != MetricFact.created_at,
        ),
    )
    unverifiable = (
        session.query(MetricFact.id, MetricFact.source_document_id)
        .outerjoin(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .filter(*scope, mismatch)
        .limit(1)
        .first()
    )
    if unverifiable is not None:
        return _unavailable_metric_fact_coverage(
            fact_id=unverifiable.id,
            document_id=unverifiable.source_document_id,
        )

    fact_rows = (
        session.query(
            identity.document_id,
            identity.id.label("revision_id"),
            identity.report_date,
            MetricFact.stock_id,
            MetricFact.metric_key,
            MetricFact.period_end_date,
        )
        .join(
            identity,
            identity.id == MetricFact.value_line_report_identity_revision_id,
        )
        .filter(
            *scope,
            MetricFact.value_line_fact_known_at <= knowledge_cutoff,
            identity.known_at <= knowledge_cutoff,
            identity.report_date.is_not(None),
            identity.report_date <= knowledge_cutoff.date(),
            transaction_visible_in_snapshot_predicate(
                identity.created_txid,
                visibility_snapshot=knowledge_txid_snapshot,
                bind_name="quant_identity_visibility_snapshot",
            ),
            MetricFact.stock_id.is_not(None),
            or_(
                MetricFact.value_line_created_txid.is_(None),
                MetricFact.created_at <= knowledge_cutoff,
            ),
        )
        .all()
    )
    value_line_documents = {row.document_id for row in fact_rows}
    report_dates = list(
        {
            (row.document_id, row.revision_id, row.report_date)
            for row in fact_rows
        }
    )
    report_dates = [row[2] for row in report_dates]

    month_buckets: dict[str, dict[str, Any]] = {}
    all_stocks: set[int] = set()
    all_metric_keys: set[str] = set()
    period_dates: list[date] = []
    future_period_rows = 0
    for (
        _document_id,
        _revision_id,
        report_date,
        stock_id,
        metric_key,
        period_end_date,
    ) in fact_rows:
        month = report_date.strftime("%Y-%m")
        bucket = month_buckets.setdefault(
            month,
            {"stocks": set(), "metric_keys": set(), "fact_rows": 0},
        )
        bucket["stocks"].add(stock_id)
        bucket["metric_keys"].add(metric_key)
        bucket["fact_rows"] += 1
        all_stocks.add(stock_id)
        all_metric_keys.add(metric_key)
        if period_end_date is not None:
            period_dates.append(period_end_date)
            if period_end_date > report_date:
                future_period_rows += 1

    monthly_rows: list[dict[str, Any]] = []
    total_metric_keys = len(all_metric_keys)
    for month, values in sorted(month_buckets.items()):
        monthly_rows.append(
            {
                "month": month,
                "stocks": len(values["stocks"]),
                "metric_keys": len(values["metric_keys"]),
                "metric_key_coverage_ratio": round(
                    len(values["metric_keys"]) / total_metric_keys, 6
                )
                if total_metric_keys
                else 0.0,
                "fact_rows": values["fact_rows"],
            }
        )

    monthly_breadths = [row["stocks"] for row in monthly_rows]
    report_min = min(report_dates) if report_dates else None
    report_max = max(report_dates) if report_dates else None
    period_min = min(period_dates) if period_dates else None
    period_max = max(period_dates) if period_dates else None
    return {
        "status": "available",
        "reason_code": None,
        "documents": len(value_line_documents),
        "parsed_fact_rows": len(fact_rows),
        "stocks": len(all_stocks),
        "metric_keys": total_metric_keys,
        "report_date_start": _iso(report_min),
        "report_date_end": _iso(report_max),
        "publication_span_years": round(_span_years(report_min, report_max), 6),
        "publication_months": len(monthly_rows),
        "observed_archive_weeks": len(
            {day - timedelta(days=day.weekday()) for day in report_dates}
        ),
        "longest_consecutive_archive_weeks": _longest_consecutive_weeks(report_dates),
        "minimum_monthly_stock_breadth": min(monthly_breadths, default=0),
        "median_monthly_stock_breadth": float(median(monthly_breadths))
        if monthly_breadths
        else 0.0,
        "period_end_start": _iso(period_min),
        "period_end_end": _iso(period_max),
        "embedded_period_span_years": round(_span_years(period_min, period_max), 6),
        "future_or_estimate_period_rows": future_period_rows,
        "historical_or_asof_period_rows": len(period_dates) - future_period_rows,
        "monthly_cross_sections": monthly_rows,
        "coverage_semantics": {
            "publication_vintage": "strict_report_date_observation",
            "embedded_period_depth": (
                "restated/estimated rows inside observed reports; not independent PIT vintages"
            ),
            "user_scoped": True,
            "point_in_time_authority": "fact_bound_report_identity_and_fact_known_at",
        },
    }


def _unavailable_metric_fact_coverage(
    *, fact_id: int | None, document_id: int | None
) -> dict[str, Any]:
    """Return no quantitative claim when exact historical lineage is unknown."""

    return {
        "status": "unavailable",
        "reason_code": "historical_report_identity_unverifiable",
        "unverifiable_fact_id": fact_id,
        "unverifiable_document_id": document_id,
        "documents": 0,
        "parsed_fact_rows": 0,
        "stocks": 0,
        "metric_keys": 0,
        "report_date_start": None,
        "report_date_end": None,
        "publication_span_years": 0.0,
        "publication_months": 0,
        "observed_archive_weeks": 0,
        "longest_consecutive_archive_weeks": 0,
        "minimum_monthly_stock_breadth": 0,
        "median_monthly_stock_breadth": 0.0,
        "period_end_start": None,
        "period_end_end": None,
        "embedded_period_span_years": 0.0,
        "future_or_estimate_period_rows": 0,
        "historical_or_asof_period_rows": 0,
        "monthly_cross_sections": [],
        "coverage_semantics": {
            "publication_vintage": "unverifiable",
            "embedded_period_depth": "unverifiable",
            "user_scoped": True,
            "point_in_time_authority": "unverifiable",
        },
    }


def _price_coverage(
    session: Session,
    *,
    knowledge_cutoff: datetime,
) -> dict[str, Any]:
    cutoff_filters = (
        StockPrice.price_date <= knowledge_cutoff.date(),
        StockPrice.created_at <= knowledge_cutoff,
    )
    rows, stocks, start, end, missing_currency = (
        session.query(
            func.count(StockPrice.id),
            func.count(func.distinct(StockPrice.stock_id)),
            func.min(StockPrice.price_date),
            func.max(StockPrice.price_date),
            func.count(StockPrice.id).filter(StockPrice.currency.is_(None)),
        )
        .filter(*cutoff_filters)
        .one()
    )
    source_rows = (
        session.query(StockPrice.source, func.count(StockPrice.id))
        .filter(*cutoff_filters)
        .group_by(StockPrice.source)
        .order_by(StockPrice.source)
        .all()
    )
    return {
        "rows": int(rows or 0),
        "stocks": int(stocks or 0),
        "date_start": _iso(start),
        "date_end": _iso(end),
        "span_years": round(_span_years(start, end), 6),
        "missing_currency_rows": int(missing_currency or 0),
        "sources": {source: int(count) for source, count in source_rows},
        "qualifies_as_survivorship_free_backbone": False,
        "qualification_note": (
            "Local price rows have no historical-universe/delisting entitlement proof; "
            "row presence alone cannot satisfy H1/H3."
        ),
    }


def _parse_runs_as_of(
    session: Session,
    *,
    knowledge_cutoff: datetime,
) -> dict[str, ParseRun13F]:
    rows = (
        session.query(ParseRun13F)
        .filter(
            ParseRun13F.status == "succeeded",
            ParseRun13F.created_at <= knowledge_cutoff,
            ParseRun13F.finished_at.is_not(None),
            ParseRun13F.finished_at <= knowledge_cutoff,
        )
        .order_by(
            ParseRun13F.accession_number,
            ParseRun13F.finished_at.desc(),
            ParseRun13F.created_at.desc(),
            ParseRun13F.id.desc(),
        )
        .all()
    )
    selected: dict[str, ParseRun13F] = {}
    for row in rows:
        selected.setdefault(row.accession_number, row)
    return selected


def _filing_authorities_as_of(
    session: Session,
    *,
    knowledge_cutoff: datetime,
    parse_runs_by_accession: dict[str, ParseRun13F],
) -> tuple[list[Filing13F], list[Filing13F]]:
    eligible_filings = (
        session.query(Filing13F)
        .filter(
            Filing13F.form_type.in_(HR_FORM_TYPES),
            Filing13F.filed_at <= knowledge_cutoff.date(),
            Filing13F.ingested_at <= knowledge_cutoff,
            Filing13F.updated_at <= knowledge_cutoff,
            or_(
                Filing13F.accepted_at.is_(None),
                Filing13F.accepted_at <= knowledge_cutoff,
            ),
            Filing13F.accession_number.in_(
                list(parse_runs_by_accession) or ["__no_eligible_parse__"]
            ),
        )
        .all()
    )
    grouped: dict[tuple[int, date], list[Filing13F]] = {}
    for filing in eligible_filings:
        if filing.quarter_end_date is None:
            continue
        grouped.setdefault((filing.manager_id, filing.quarter_end_date), []).append(
            filing
        )

    authorities: list[Filing13F] = []
    for filings in grouped.values():
        _kind, pool = competition_pool(filings)
        if not pool:
            continue
        if len(pool) == 1:
            authorities.append(pool[0])
            continue
        if any(filing.accepted_at is None for filing in pool):
            continue
        ranked = sorted(
            pool,
            key=lambda filing: (filing.accepted_at, filing.accession_number or ""),
            reverse=True,
        )
        if ranked[0].accepted_at == ranked[1].accepted_at:
            continue
        authorities.append(ranked[0])
    return authorities, eligible_filings


def _thirteenf_coverage(
    session: Session,
    *,
    knowledge_cutoff: datetime,
) -> dict[str, Any]:
    as_of_date = knowledge_cutoff.date()
    parse_runs_by_accession = _parse_runs_as_of(
        session,
        knowledge_cutoff=knowledge_cutoff,
    )
    authority_filings, version_filings = _filing_authorities_as_of(
        session,
        knowledge_cutoff=knowledge_cutoff,
        parse_runs_by_accession=parse_runs_by_accession,
    )
    filing_rows = [
        (
            filing.id,
            filing.manager_id,
            filing.quarter_end_date,
            filing.filed_at,
            filing.official_filing_deadline,
        )
        for filing in authority_filings
    ]
    version_rows = [
        (
            filing.id,
            filing.manager_id,
            filing.quarter_end_date,
            filing.filed_at,
        )
        for filing in version_filings
    ]
    authority_pairs = [
        (filing.id, parse_runs_by_accession[filing.accession_number].id)
        for filing in authority_filings
        if filing.accession_number in parse_runs_by_accession
    ]
    holding_rows = (
        session.query(Holding13F)
        .filter(
            tuple_(Holding13F.filing_id, Holding13F.parse_run_id).in_(
                authority_pairs or [(-1, -1)]
            ),
            Holding13F.created_at <= knowledge_cutoff,
            Holding13F.updated_at <= knowledge_cutoff,
        )
        .with_entities(
            Holding13F.quarter_end_date,
            Holding13F.manager_id,
            Holding13F.stock_id,
            Holding13F.put_call,
            Holding13F.ssh_prnamt_type,
        )
        .all()
    )

    quarters: dict[date, dict[str, set[int] | int | list[date]]] = {}
    filed_dates: list[date] = []
    lags: list[int] = []
    invalid_negative_lags = 0
    for _, manager_id, quarter_end, filed_at, official_deadline in filing_rows:
        if quarter_end is None or filed_at is None:
            continue
        bucket = quarters.setdefault(
            quarter_end,
            {
                "managers": set(),
                "mapped_stocks": set(),
                "holdings": 0,
                "deadlines": [],
            },
        )
        bucket["managers"].add(manager_id)  # type: ignore[union-attr]
        deadline = official_deadline or (quarter_end + timedelta(days=45))
        bucket["deadlines"].append(deadline)  # type: ignore[union-attr]
        filed_dates.append(filed_at)
        try:
            lags.append(filing_lag_days(quarter_end, filed_at))
        except ValueError:
            invalid_negative_lags += 1

    mapped_holdings = 0
    eligible_common_mapped_holdings = 0
    mapped_stocks: set[int] = set()
    for quarter_end, _, stock_id, put_call, amount_type in holding_rows:
        if quarter_end is None:
            continue
        bucket = quarters.setdefault(
            quarter_end,
            {
                "managers": set(),
                "mapped_stocks": set(),
                "holdings": 0,
                "deadlines": [],
            },
        )
        bucket["holdings"] = int(bucket["holdings"]) + 1
        if stock_id is not None:
            mapped_holdings += 1
            mapped_stocks.add(stock_id)
            bucket["mapped_stocks"].add(stock_id)  # type: ignore[union-attr]
            if put_call is None and (amount_type or "SH") == "SH":
                eligible_common_mapped_holdings += 1

    quarter_rows: list[dict[str, Any]] = []
    for quarter_end, values in sorted(quarters.items()):
        deadlines = values["deadlines"]
        official_deadline = max(deadlines) if deadlines else quarter_end + timedelta(days=45)  # type: ignore[arg-type]
        quarter_rows.append(
            {
                "quarter_end_date": quarter_end.isoformat(),
                "official_filing_deadline": official_deadline.isoformat(),
                "mature": official_deadline <= as_of_date,
                "managers": len(values["managers"]),  # type: ignore[arg-type]
                "holdings": int(values["holdings"]),
                "mapped_stocks": len(values["mapped_stocks"]),  # type: ignore[arg-type]
            }
        )
    mature_quarter_rows = [row for row in quarter_rows if row["mature"]]
    manager_breadths = [row["managers"] for row in mature_quarter_rows]
    stock_breadths = [row["mapped_stocks"] for row in mature_quarter_rows]
    filed_start = min(filed_dates) if filed_dates else None
    filed_end = max(filed_dates) if filed_dates else None
    lag_summary = {
        "minimum": min(lags) if lags else None,
        "median": float(median(lags)) if lags else None,
        "maximum": max(lags) if lags else None,
        "invalid_negative_count": invalid_negative_lags,
    }
    version_groups: dict[tuple[int, date], list[date]] = {}
    for _, manager_id, quarter_end, filed_at in version_rows:
        if quarter_end is None or filed_at is None:
            continue
        version_groups.setdefault((manager_id, quarter_end), []).append(filed_at)
    first_availability_dates = [min(dates) for dates in version_groups.values() if dates]
    return {
        "authoritative_filings": len(filing_rows),
        "authoritative_holdings": len(holding_rows),
        "mapped_holdings": mapped_holdings,
        "mapped_holding_ratio": round(mapped_holdings / len(holding_rows), 6)
        if holding_rows
        else 0.0,
        "eligible_common_mapped_holdings": eligible_common_mapped_holdings,
        "mapped_stocks": len(mapped_stocks),
        "versioned_filings": len(version_rows),
        "manager_quarters_with_multiple_versions": sum(
            1 for dates in version_groups.values() if len(dates) > 1
        ),
        "first_availability_date_start": _iso(
            min(first_availability_dates) if first_availability_dates else None
        ),
        "first_availability_date_end": _iso(
            max(first_availability_dates) if first_availability_dates else None
        ),
        "quarters": len(quarter_rows),
        "mature_quarters": len(mature_quarter_rows),
        "immature_quarters": len(quarter_rows) - len(mature_quarter_rows),
        "quarter_end_start": quarter_rows[0]["quarter_end_date"] if quarter_rows else None,
        "quarter_end_end": quarter_rows[-1]["quarter_end_date"] if quarter_rows else None,
        "availability_date_start": _iso(filed_start),
        "availability_date_end": _iso(filed_end),
        "availability_span_years": round(_span_years(filed_start, filed_end), 6),
        "minimum_manager_breadth": min(manager_breadths, default=0),
        "median_manager_breadth": float(median(manager_breadths))
        if manager_breadths
        else 0.0,
        "minimum_mapped_stock_breadth": min(stock_breadths, default=0),
        "median_mapped_stock_breadth": float(median(stock_breadths))
        if stock_breadths
        else 0.0,
        "filing_lag_days": lag_summary,
        "quarterly_cross_sections": quarter_rows,
        "availability_semantics": (
            "Signals become observable on filed_at, never on quarter_end_date; "
            "13F filings may arrive up to the official filing deadline."
        ),
        "historical_version_semantics": (
            "Today's active filing is a current product snapshot only. Historical "
            "research must reconstruct the filing/amendment version observable at T "
            "from versioned filings; it must not back-project today's active version."
        ),
    }


def collect_database_coverage(
    session: Session,
    *,
    user_id: int,
    as_of_date: date | None = None,
    knowledge_cutoff: datetime | None = None,
) -> dict[str, Any]:
    """Collect aggregate coverage without mutating or committing the session."""

    if user_id <= 0:
        raise ValueError("user_id must be positive")
    if knowledge_cutoff is not None and knowledge_cutoff.tzinfo is None:
        raise ValueError("knowledge_cutoff must be timezone-aware")
    normalized_cutoff = (
        knowledge_cutoff.astimezone(timezone.utc)
        if knowledge_cutoff is not None
        else None
    )
    if (
        as_of_date is not None
        and normalized_cutoff is not None
        and as_of_date != normalized_cutoff.date()
    ):
        raise ValueError("as_of_date and knowledge_cutoff must use the same UTC date")
    target_date = as_of_date or (
        normalized_cutoff.date() if normalized_cutoff is not None else date.today()
    )
    cutoff = normalized_cutoff or datetime.combine(
        target_date,
        time.max,
        tzinfo=timezone.utc,
    )
    evaluation_snapshot = database_evaluation_snapshot(session, cutoff)
    return {
        "metric_facts": _metric_fact_coverage(
            session,
            user_id=user_id,
            knowledge_cutoff=evaluation_snapshot.cutoff,
            knowledge_txid_snapshot=evaluation_snapshot.visibility_snapshot,
        ),
        "prices": _price_coverage(session, knowledge_cutoff=cutoff),
        "thirteenf": _thirteenf_coverage(session, knowledge_cutoff=cutoff),
    }


def _requirement(code: str, passed: bool, observed: Any, required: Any) -> dict[str, Any]:
    return {
        "code": code,
        "passed": bool(passed),
        "observed": observed,
        "required": required,
    }


def _decision(requirements: list[dict[str, Any]], *, blocking: bool) -> dict[str, Any]:
    failures = [item["code"] for item in requirements if not item["passed"]]
    return {
        "status": "GO" if not failures else "NO_GO",
        "blocking_for_1_r0": blocking,
        "failed_reason_codes": failures,
        "requirements": requirements,
    }


def evaluate_hypothesis_gates(
    *,
    coverage: dict[str, Any],
    readiness: SourceReadiness,
    power_plans: dict[str, dict[str, Any]],
    assumptions: PowerAssumptions = DEFAULT_POWER_ASSUMPTIONS,
) -> dict[str, Any]:
    """Evaluate data-only gates; this never evaluates alpha or profitability."""

    backbone_evidenced = readiness.backbone_authorized and bool(
        (readiness.backbone_authorization_evidence_ref or "").strip()
    )
    common_backbone_requirements = [
        _requirement(
            "backbone_authorization_missing",
            backbone_evidenced,
            readiness.backbone_authorization_evidence_ref,
            "recorded operator authorization evidence",
        ),
        _requirement(
            "backbone_not_survivorship_free",
            readiness.backbone_survivorship_free,
            readiness.backbone_survivorship_free,
            True,
        ),
        _requirement(
            "backbone_missing_delisted_names",
            readiness.backbone_includes_delisted,
            readiness.backbone_includes_delisted,
            True,
        ),
        _requirement(
            "backbone_missing_fundamentals",
            readiness.backbone_has_fundamentals,
            readiness.backbone_has_fundamentals,
            True,
        ),
        _requirement(
            "backbone_missing_prices",
            readiness.backbone_has_prices,
            readiness.backbone_has_prices,
            True,
        ),
    ]

    h1_required_years = power_plans["H1"]["selected_scenario"][
        "required_total_calendar_years"
    ]
    h1_requirements = [
        *common_backbone_requirements,
        _requirement(
            "insufficient_backbone_history",
            readiness.backbone_span_years >= h1_required_years,
            round(readiness.backbone_span_years, 6),
            h1_required_years,
        ),
        _requirement(
            "insufficient_backbone_cross_sectional_breadth",
            readiness.backbone_minimum_monthly_stock_breadth
            >= assumptions.minimum_cross_sectional_stocks,
            readiness.backbone_minimum_monthly_stock_breadth,
            assumptions.minimum_cross_sectional_stocks,
        ),
    ]

    metric = coverage["metric_facts"]
    h2_required_years = power_plans["H2"]["selected_scenario"][
        "required_total_calendar_years"
    ]
    h2_requirements = [
        _requirement(
            "value_line_automation_authorization_missing",
            readiness.value_line_automation_authorized
            and bool((readiness.value_line_authorization_evidence_ref or "").strip()),
            readiness.value_line_authorization_evidence_ref,
            "recorded operator authorization evidence",
        ),
        _requirement(
            "value_line_four_week_continuity_not_proven",
            metric["longest_consecutive_archive_weeks"] >= 4,
            metric["longest_consecutive_archive_weeks"],
            4,
        ),
        _requirement(
            "insufficient_value_line_publication_history",
            metric["publication_span_years"] >= h2_required_years,
            metric["publication_span_years"],
            h2_required_years,
        ),
        _requirement(
            "insufficient_value_line_cross_sectional_breadth",
            metric["minimum_monthly_stock_breadth"]
            >= assumptions.minimum_cross_sectional_stocks,
            metric["minimum_monthly_stock_breadth"],
            assumptions.minimum_cross_sectional_stocks,
        ),
    ]

    thirteenf = coverage["thirteenf"]
    h3_required_years = power_plans["H3"]["selected_scenario"][
        "required_total_calendar_years"
    ]
    h3_requirements = [
        *common_backbone_requirements,
        _requirement(
            "insufficient_13f_availability_history",
            thirteenf["availability_span_years"] >= h3_required_years,
            thirteenf["availability_span_years"],
            h3_required_years,
        ),
        _requirement(
            "insufficient_13f_manager_breadth",
            thirteenf["minimum_manager_breadth"] >= assumptions.minimum_13f_managers,
            thirteenf["minimum_manager_breadth"],
            assumptions.minimum_13f_managers,
        ),
        _requirement(
            "insufficient_13f_mapped_stock_breadth",
            thirteenf["minimum_mapped_stock_breadth"]
            >= assumptions.minimum_13f_mapped_stocks,
            thirteenf["minimum_mapped_stock_breadth"],
            assumptions.minimum_13f_mapped_stocks,
        ),
    ]

    hypotheses = {
        "H1": _decision(h1_requirements, blocking=True),
        "H2": _decision(h2_requirements, blocking=False),
        "H3": _decision(h3_requirements, blocking=False),
    }
    # The accepted 1-R0 contract explicitly requires H1 data sufficiency before
    # 1-R1...1-R4. H3 can be useful later but cannot bypass this first gate.
    h1_go = hypotheses["H1"]["status"] == "GO"
    return {
        "overall_1_r0_gate": "GO" if h1_go else "NO_GO",
        "phase_1_follow_on_unlocked": h1_go,
        "unlock_rule": "H1 data sufficiency must be GO; H2 is non-blocking and H3 cannot bypass 1-R0",
        "hypotheses": hypotheses,
    }


def build_audit_report(
    session: Session,
    *,
    user_id: int,
    evaluated_at: datetime | None = None,
    readiness: SourceReadiness | None = None,
    assumptions: PowerAssumptions = DEFAULT_POWER_ASSUMPTIONS,
) -> dict[str, Any]:
    evaluated = evaluated_at or datetime.now(timezone.utc)
    if evaluated.tzinfo is None:
        raise ValueError("evaluated_at must be timezone-aware")
    evaluated = evaluated.astimezone(timezone.utc)
    source_readiness = readiness or SourceReadiness()
    coverage = collect_database_coverage(
        session,
        user_id=user_id,
        as_of_date=evaluated.date(),
        knowledge_cutoff=evaluated,
    )
    power_plans = build_power_plans(assumptions)
    gate = evaluate_hypothesis_gates(
        coverage=coverage,
        readiness=source_readiness,
        power_plans=power_plans,
        assumptions=assumptions,
    )
    return {
        "schema_version": "1.0",
        "policy_version": POLICY_VERSION,
        "evaluated_at": evaluated.isoformat(),
        "environment": "development",
        "user_scope_id": user_id,
        "read_only": True,
        "power_assumptions": assumptions.to_dict(),
        "power_method": {
            "type": "normal_noncentrality_planning_approximation_for_future_HAC_test",
            "formula": "years=((t_threshold+Phi^-1(target_power))*tracking_error/alpha)^2",
            "limitation": (
                "Final adequacy must be recomputed from acquired return autocorrelation "
                "and realized HAC variance; this approximation cannot certify power."
            ),
        },
        "power_plans": power_plans,
        "source_readiness": source_readiness.to_dict(),
        "coverage": coverage,
        "data_availability_matrix": [
            {
                "source": "user_uploaded_value_line",
                "strict_publication_vintages": coverage["metric_facts"]["publication_months"],
                "embedded_history_use": "reconstructed-vintage relative judgments only",
                "absolute_return_gate_eligible": False,
            },
            {
                "source": "survivorship_free_commodity_backbone",
                "strict_publication_vintages": None,
                "embedded_history_use": "H1/H3 backbone and generic null",
                "absolute_return_gate_eligible": source_readiness.backbone_authorized
                and source_readiness.backbone_survivorship_free
                and source_readiness.backbone_includes_delisted,
            },
            {
                "source": "sec_edgar_13f",
                "strict_publication_vintages": coverage["thirteenf"]["quarters"],
                "embedded_history_use": "H3; signals available only from filed_at",
                "absolute_return_gate_eligible": False,
            },
        ],
        "gate": gate,
        "sources": [
            "https://www.nber.org/papers/t0055",
            "https://www.statsmodels.org/stable/generated/statsmodels.stats.power.TTestPower.solve_power.html",
            "https://www.sec.gov/files/form13f.pdf",
            "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets",
            "docs/architecture/coverage-source-policy.md",
        ],
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    coverage = report["coverage"]
    metric = coverage["metric_facts"]
    prices = coverage["prices"]
    thirteenf = coverage["thirteenf"]
    gate = report["gate"]
    assumptions = report["power_assumptions"]
    lines = [
        "# Quant Trading 1-R0A Data-Sufficiency Audit",
        "",
        f"- Evaluated at: `{report['evaluated_at']}`",
        f"- Policy: `{report['policy_version']}`",
        f"- Environment: `{report['environment']}` (read-only)",
        f"- User scope: `{report['user_scope_id']}`",
        f"- Overall gate: **{gate['overall_1_r0_gate']}**",
        "",
        "## Decision",
        "",
    ]
    if gate["phase_1_follow_on_unlocked"]:
        lines.append("H1 data sufficiency is GO; 1-R1 may be opened under the accepted roadmap.")
    else:
        lines.append(
            "No hypothesis research or holdout evaluation is authorized. "
            "1-R1 through 1-R4 remain closed because H1 data sufficiency is NO_GO."
        )
    lines.extend(
        [
            "",
            "## Pre-registered power contract",
            "",
            (
                f"One-sided threshold `t_HAC >= {assumptions['t_threshold']:.1f}`, "
                f"net alpha `{assumptions['annual_alpha']:.1%}/yr`, target power "
                f"`{assumptions['target_power']:.0%}`, final holdout "
                f"`{assumptions['holdout_fraction']:.0%}`. Breadth is a separate "
                "eligibility floor, not a substitute for return-history time."
            ),
            "",
            "| Hypothesis | Frequency | Selected TE | Holdout periods | Total years required | Status |",
            "| --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for key in ("H1", "H2", "H3"):
        plan = report["power_plans"][key]
        scenario = plan["selected_scenario"]
        lines.append(
            f"| {key} | {plan['observation_frequency']} | "
            f"{scenario['tracking_error_annual']:.1%} | "
            f"{scenario['required_holdout_periods']} | "
            f"{scenario['required_total_calendar_years']:.1f} | "
            f"**{gate['hypotheses'][key]['status']}** |"
        )
    lines.extend(
        [
            "",
            "This is a normal/HAC planning approximation. Final power must be re-estimated "
            "from the acquired return series and its realized autocorrelation before any holdout is unlocked.",
            "",
            "## Observed database coverage",
            "",
            "### User-scoped Value Line facts",
            "",
            f"- Parsed Value Line documents: **{metric['documents']}**",
            f"- Parsed fact rows / stocks / metric keys: **{metric['parsed_fact_rows']} / {metric['stocks']} / {metric['metric_keys']}**",
            f"- Strict publication range: **{_fmt(metric['report_date_start'])} → {_fmt(metric['report_date_end'])}** "
            f"({metric['publication_span_years']:.3f} years; {metric['publication_months']} observed months)",
            f"- Weekly archive: **{metric['observed_archive_weeks']}** observed weeks; longest consecutive run **{metric['longest_consecutive_archive_weeks']}**",
            f"- Embedded period range: **{_fmt(metric['period_end_start'])} → {_fmt(metric['period_end_end'])}**. "
            "This is restated/estimated depth, not independent publication-vintage depth.",
            "",
            "### Local prices (non-qualifying inventory)",
            "",
            f"- Rows / stocks / range: **{prices['rows']} / {prices['stocks']} / {_fmt(prices['date_start'])} → {_fmt(prices['date_end'])}**",
            f"- Sources: `{prices['sources']}`",
            "- These rows do not prove survivorship-free historical membership, delisted-name coverage, or licensed production use.",
            "",
            "### SEC 13F authoritative history",
            "",
            f"- Active/current-successful filings / holdings: **{thirteenf['authoritative_filings']} / {thirteenf['authoritative_holdings']}**",
            f"- Versioned successful filings / manager-quarters with amendments: **{thirteenf['versioned_filings']} / {thirteenf['manager_quarters_with_multiple_versions']}**",
            f"- Quarters / mapped stocks / mapped holding ratio: **{thirteenf['quarters']} / {thirteenf['mapped_stocks']} / {thirteenf['mapped_holding_ratio']:.1%}**",
            f"- Mature / still-open quarters at the audit date: **{thirteenf['mature_quarters']} / {thirteenf['immature_quarters']}**; breadth floors use mature quarters only.",
            f"- Quarter-end range: **{_fmt(thirteenf['quarter_end_start'])} → {_fmt(thirteenf['quarter_end_end'])}**",
            f"- Actually observable (`filed_at`) range: **{_fmt(thirteenf['availability_date_start'])} → {_fmt(thirteenf['availability_date_end'])}** "
            f"({thirteenf['availability_span_years']:.3f} years)",
            f"- Filing lag days min / median / max: **{_fmt(thirteenf['filing_lag_days']['minimum'])} / {_fmt(thirteenf['filing_lag_days']['median'])} / {_fmt(thirteenf['filing_lag_days']['maximum'])}**",
            "- Today's active filing is not a historical PIT selector. Later amendments must never be back-projected into dates before they were filed.",
            "",
            "## Fail-closed gate reasons",
            "",
        ]
    )
    for key in ("H1", "H2", "H3"):
        decision = gate["hypotheses"][key]
        reasons = ", ".join(decision["failed_reason_codes"]) or "none"
        lines.append(f"- **{key} {decision['status']}**: `{reasons}`")
    lines.extend(
        [
            "",
            "## Source and licensing state",
            "",
            "- Value Line automated acquisition remains blocked by `coverage-source-policy.md`; only explicit user uploads are authorized today.",
            "- A survivorship-free fundamentals + prices backbone with delisted names has no recorded authorization evidence in this audit.",
            "- SEC 13F data is public, but holdings are delayed; every research timestamp must use `filed_at`, never quarter end.",
            "",
            "## Reliable references",
            "",
        ]
    )
    lines.extend(f"- {source}" for source in report["sources"])
    return "\n".join(lines) + "\n"
