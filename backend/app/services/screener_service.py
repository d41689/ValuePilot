from dataclasses import dataclass
from typing import List, Dict, Any
from datetime import datetime
import re
from sqlalchemy.orm import Session, aliased
from decimal import Decimal, DecimalException
from sqlalchemy import select, and_, false, or_, tuple_
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.evaluation_snapshot import database_evaluation_snapshot
from app.services.metric_fact_currentness import CurrentnessScope, current_metric_fact_ids_at
from app.services.canonical_financials import (
    CANONICAL_SOURCE_TYPES,
    CanonicalUnavailableError,
    evaluation_business_date,
    guard_sec_run_availability,
    require_applicable_method_facts,
    visible_metric_fact_predicate,
)
from app.services.source_reconciliation import guard_reconciled_source_selection


MAX_SCREENER_GUARD_FACTS = 10_000
MAX_SCREENER_CONDITIONS = 20
MAX_SCREENER_METRIC_KEY_LENGTH = 128
MAX_SCREENER_ABS_TARGET = Decimal("1e25")
MAX_SCREENER_SQL_BIND_BUDGET = 12_000
SCREENER_ALLOWED_PAIR_BIND_COUNT = 2
# Each condition also binds its metric/value, two cutoffs, tenant visibility,
# and optionally its source type. Keep substantial headroom below PostgreSQL's
# protocol limit and expression-stack ceiling for the stock predicate and
# future bounded filters.
SCREENER_CONDITION_BIND_OVERHEAD = 8
SCREEN_OPERATORS = frozenset({">", ">=", "<", "<=", "=", "=="})
SCREEN_METRIC_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.]*$")


class ScreenerRuleError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class _ScreenerCondition:
    metric_key: str
    operator: str
    target_value: Decimal


@dataclass(frozen=True)
class _NormalizedScreenerRule:
    conditions: tuple[_ScreenerCondition, ...]
    selected_source_type: str | None


@dataclass(frozen=True)
class _ScreenerSourceAuthority:
    evaluated_at: datetime
    allowed_by_stock_metric: dict[
        tuple[int, str], tuple[tuple[int, Decimal], ...]
    ]

    def pairs_for_metric(self, metric_key: str) -> tuple[tuple[int, Decimal], ...]:
        return tuple(
            pair
            for (stock_id, key), pairs in self.allowed_by_stock_metric.items()
            if key == metric_key
            for pair in pairs
        )


@dataclass(frozen=True)
class ScreenerEvaluation:
    stocks: list[Stock]
    evaluated_at: datetime


class ScreenerService:
    def __init__(self, db: Session):
        self.db = db

    METRIC_OUTPUT_SPECS: dict[str, dict[str, Any]] = {
        "net_profit_usd_millions": {"keys": ["is.net_income"], "period_type": "FY"},
        "depreciation_usd_millions": {"keys": ["is.depreciation"], "period_type": "FY"},
        "capital_spending_per_share_usd": {"keys": ["per_share.capital_spending"], "period_type": "FY"},
        "common_shares_outstanding_millions": {
            "keys": ["equity.shares_outstanding"],
            "period_type": ["AS_OF", "FY"],
        },
        "timeliness": {"keys": ["rating.timeliness"], "period_type": "AS_OF"},
        "safety": {"keys": ["rating.safety"], "period_type": "AS_OF"},
        "avg_annual_dividend_yield_pct": {"keys": ["val.avg_dividend_yield"], "period_type": "FY"},
        "company_financial_strength": {"keys": ["quality.financial_strength"], "period_type": "AS_OF"},
        "stock_price_stability": {"keys": ["quality.stock_price_stability"], "period_type": "AS_OF"},
        "price_growth_persistence": {"keys": ["quality.price_growth_persistence"], "period_type": "AS_OF"},
        "earnings_predictability": {"keys": ["quality.earnings_predictability"], "period_type": "AS_OF"},
    }

    LEGACY_METRIC_KEY_MAP: dict[str, str] = {
        "pe_ratio": "val.pe",
        "dividend_yield": "val.dividend_yield",
        "net_profit_usd_millions": "is.net_income",
        "depreciation_usd_millions": "is.depreciation",
        "capital_spending_per_share_usd": "per_share.capital_spending",
        "common_stock_shares_outstanding": "equity.shares_outstanding",
        "timeliness": "rating.timeliness",
        "safety": "rating.safety",
        "avg_annual_dividend_yield_pct": "val.avg_dividend_yield",
        "company_financial_strength": "quality.financial_strength",
        "stock_price_stability": "quality.stock_price_stability",
        "price_growth_persistence": "quality.price_growth_persistence",
        "earnings_predictability": "quality.earnings_predictability",
    }

    @classmethod
    def metric_keys(cls) -> set[str]:
        keys: set[str] = set()
        for spec in cls.METRIC_OUTPUT_SPECS.values():
            keys.update(spec["keys"])
        return keys

    @classmethod
    def _canonical_metric_key(cls, key: str) -> str:
        return cls.LEGACY_METRIC_KEY_MAP.get(key, key)

    @staticmethod
    def _extract_value(fact: MetricFact) -> Any:
        if fact.value_numeric is not None:
            return float(fact.value_numeric)
        if fact.value_text is not None:
            return fact.value_text
        if fact.value_json is None:
            return None
        if isinstance(fact.value_json, dict):
            return fact.value_json.get("value", fact.value_json.get("raw"))
        return fact.value_json

    def fetch_metrics_for_stocks(
        self,
        stock_ids: list[int],
        current_user_id: int,
        *,
        selected_source_type: str | None = None,
        knowledge_cutoff: datetime | None = None,
    ) -> dict[int, dict[str, Any]]:
        if not stock_ids:
            return {}
        evaluation_snapshot = database_evaluation_snapshot(self.db, knowledge_cutoff)
        evaluated_at = evaluation_snapshot.cutoff

        fact_nature_expr = MetricFact.value_json["fact_nature"].as_string()
        stmt = select(MetricFact).where(
            MetricFact.stock_id.in_(stock_ids),
            MetricFact.metric_key.in_(self.metric_keys()),
            MetricFact.id.in_(
                current_metric_fact_ids_at(
                    self.db,
                    knowledge_cutoff=evaluated_at,
                    knowledge_txid_snapshot=evaluation_snapshot.visibility_snapshot,
                    scope=CurrentnessScope(
                        stock_ids=tuple(stock_ids),
                        metric_keys=tuple(sorted(self.metric_keys())),
                    ),
                )
            ),
            visible_metric_fact_predicate(MetricFact, user_id=current_user_id),
            or_(
                fact_nature_expr.is_(None),
                fact_nature_expr != "estimate",
            ),
        )
        facts = self.db.scalars(stmt).all()

        facts_by_stock: dict[int, dict[str, list[MetricFact]]] = {}
        for fact in facts:
            facts_by_stock.setdefault(fact.stock_id, {}).setdefault(fact.metric_key, []).append(fact)

        metrics_by_stock: dict[int, dict[str, Any]] = {}
        for stock_id in stock_ids:
            stock_metrics: dict[str, Any] = {}
            fact_map = facts_by_stock.get(stock_id, {})
            selected = guard_reconciled_source_selection(
                [fact for rows in fact_map.values() for fact in rows],
                consumer="screener_metrics",
                knowledge_cutoff=evaluated_at,
                selected_source_type=selected_source_type,
                session=self.db,
                user_id=current_user_id,
            )
            selected = guard_sec_run_availability(
                self.db,
                stock_id=stock_id,
                facts=selected,
                knowledge_cutoff=evaluated_at,
            )
            selected_ids = {fact.id for fact in selected}
            for output_key, spec in self.METRIC_OUTPUT_SPECS.items():
                desired_period_type = spec.get("period_type")
                for key in spec["keys"]:
                    facts_for_key = [fact for fact in fact_map.get(key, []) if fact.id in selected_ids]
                    if desired_period_type:
                        if isinstance(desired_period_type, (list, tuple, set)):
                            facts_for_key = [
                                fact for fact in facts_for_key if fact.period_type in desired_period_type
                            ]
                        else:
                            facts_for_key = [
                                fact for fact in facts_for_key if fact.period_type == desired_period_type
                            ]
                    if not facts_for_key:
                        continue
                    fact = max(
                        facts_for_key,
                        key=lambda f: (
                            f.period_end_date.toordinal() if f.period_end_date else -1,
                            f.created_at.timestamp() if f.created_at else 0.0,
                            f.id or 0,
                        ),
                    )
                    value = self._extract_value(fact)
                    if value is None:
                        continue
                    if key == "equity.shares_outstanding":
                        try:
                            value = float(value) / 1_000_000.0
                        except (TypeError, ValueError):
                            value = None
                    if value is not None:
                        stock_metrics[output_key] = value
                        break
            metrics_by_stock[stock_id] = stock_metrics

        return metrics_by_stock

    def execute_screen(
        self, rule_json: Dict[str, Any], current_user_id: int
    ) -> List[Stock]:
        return self.evaluate_screen(rule_json, current_user_id).stocks

    def evaluate_screen(
        self, rule_json: Dict[str, Any], current_user_id: int
    ) -> ScreenerEvaluation:
        """
        Executes a screen based on the rule definition.
        
        Rule JSON Structure V1:
        {
            "type": "AND",
            "conditions": [
                {
                    "metric": "pe_ratio",
                    "operator": "<",
                    "value": 20
                },
                {
                    "metric": "dividend_yield",
                    "operator": ">",
                    "value": 0.02
                }
            ]
        }
        """
        rule = self._normalize_rule(rule_json)

        # Base query: Start with all active stocks
        query = select(Stock).where(Stock.is_active.is_(True))
        
        # In SQLAlchemy, filtering by multiple related rows (EAV pattern) efficiently 
        # often involves joins or EXISTS subqueries.
        # For V1, simple joining:
        # SELECT s.* FROM stocks s
        # JOIN metric_facts f1 ON s.id = f1.stock_id AND f1.metric_key = 'pe_ratio' AND f1.is_current = True
        # JOIN metric_facts f2 ON s.id = f2.stock_id AND f2.metric_key = 'dividend_yield' AND f2.is_current = True
        # WHERE f1.value_numeric < 20 AND f2.value_numeric > 0.02
        
        # We need to parse the rule and construct these joins dynamically.
        selected_source_type = rule.selected_source_type
        conditions = rule.conditions
        authority = self._guard_screen_sources(
            conditions,
            current_user_id=current_user_id,
            selected_source_type=selected_source_type,
        )
        
        query = self._build_and_query(
            query,
            conditions,
            current_user_id,
            selected_source_type=selected_source_type,
            authority=authority,
        )

        return ScreenerEvaluation(
            stocks=list(self.db.scalars(query).all()),
            evaluated_at=authority.evaluated_at,
        )

    def _normalize_rule(self, rule_json: object) -> _NormalizedScreenerRule:
        if not isinstance(rule_json, dict):
            raise ScreenerRuleError(
                "screener_rule_invalid", "screener rule must be an object"
            )
        if not set(rule_json).issubset({"type", "conditions", "source_type"}):
            raise ScreenerRuleError(
                "screener_rule_invalid", "screener rule contains unknown fields"
            )
        if rule_json.get("type") != "AND":
            raise ScreenerRuleError(
                "screener_rule_type_unsupported",
                "only AND screener rules are supported",
            )
        conditions = rule_json.get("conditions")
        if not isinstance(conditions, list) or not conditions:
            raise ScreenerRuleError(
                "screener_rule_conditions_invalid",
                "screener conditions must be a non-empty list",
            )
        if len(conditions) > MAX_SCREENER_CONDITIONS:
            raise CanonicalUnavailableError(
                {"reason_code": "screener_source_guard_bound_exceeded"}
            )
        selected_source_type = rule_json.get("source_type")
        if (
            selected_source_type is not None
            and selected_source_type not in CANONICAL_SOURCE_TYPES
        ):
            raise ScreenerRuleError(
                "screener_rule_source_type_unsupported",
                "unsupported screener source type",
            )

        normalized: list[_ScreenerCondition] = []
        for condition in conditions:
            if not isinstance(condition, dict):
                raise ScreenerRuleError(
                    "screener_rule_condition_invalid",
                    "each screener condition must be an object",
                )
            if set(condition) != {"metric", "operator", "value"}:
                raise ScreenerRuleError(
                    "screener_rule_condition_invalid",
                    "each screener condition requires metric, operator, and value",
                )
            metric = condition["metric"]
            if (
                not isinstance(metric, str)
                or not metric
                or len(metric) > MAX_SCREENER_METRIC_KEY_LENGTH
                or SCREEN_METRIC_KEY_PATTERN.fullmatch(metric) is None
            ):
                raise ScreenerRuleError(
                    "screener_rule_metric_invalid", "invalid screener metric key"
                )
            operator = condition["operator"]
            if not isinstance(operator, str) or operator not in SCREEN_OPERATORS:
                raise ScreenerRuleError(
                    "screener_rule_operator_unsupported",
                    "unsupported screener comparison operator",
                )
            value = condition["value"]
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                raise ScreenerRuleError(
                    "screener_rule_value_invalid",
                    "screener comparison value must be a finite number",
                )
            try:
                target_value = Decimal(str(value))
            except DecimalException as error:
                raise ScreenerRuleError(
                    "screener_rule_value_invalid",
                    "screener comparison value must be a finite number",
                ) from error
            if (
                not target_value.is_finite()
                or abs(target_value) > MAX_SCREENER_ABS_TARGET
            ):
                raise ScreenerRuleError(
                    "screener_rule_value_invalid",
                    "screener comparison value must be a finite in-range number",
                )
            normalized.append(
                _ScreenerCondition(
                    metric_key=self._canonical_metric_key(metric),
                    operator=operator,
                    target_value=target_value,
                )
            )
        return _NormalizedScreenerRule(
            conditions=tuple(normalized),
            selected_source_type=selected_source_type,
        )

    def _build_and_query(
        self,
        query,
        conditions: tuple[_ScreenerCondition, ...],
        current_user_id: int,
        *,
        selected_source_type: str | None,
        authority: _ScreenerSourceAuthority,
    ):
        prepared_conditions: list[
            tuple[_ScreenerCondition, tuple[tuple[int, Decimal], ...]]
        ] = []
        estimated_bind_count = 0
        for cond in conditions:
            allowed_pairs = authority.pairs_for_metric(cond.metric_key)
            estimated_bind_count += (
                len(allowed_pairs) * SCREENER_ALLOWED_PAIR_BIND_COUNT
                + SCREENER_CONDITION_BIND_OVERHEAD
            )
            if estimated_bind_count > MAX_SCREENER_SQL_BIND_BUDGET:
                raise CanonicalUnavailableError(
                    {
                        "reason_code": "screener_source_guard_bound_exceeded",
                    }
                )
            prepared_conditions.append((cond, allowed_pairs))

        for cond, allowed_pairs in prepared_conditions:

            # Create an alias for MetricFact for this specific condition
            fact_alias = aliased(MetricFact)
            
            # Join this alias
            query = query.join(
                fact_alias,
                and_(
                    Stock.id == fact_alias.stock_id,
                    fact_alias.metric_key == cond.metric_key,
                    visible_metric_fact_predicate(fact_alias, user_id=current_user_id),
                    (
                        tuple_(fact_alias.id, fact_alias.value_numeric).in_(
                            allowed_pairs
                        )
                        if allowed_pairs
                        else false()
                    ),
                    *(
                        [fact_alias.source_type == selected_source_type]
                        if selected_source_type is not None
                        else []
                    ),
                )
            )
            
            # Apply filter
            if cond.operator == ">":
                query = query.where(fact_alias.value_numeric > cond.target_value)
            elif cond.operator == ">=":
                query = query.where(fact_alias.value_numeric >= cond.target_value)
            elif cond.operator == "<":
                query = query.where(fact_alias.value_numeric < cond.target_value)
            elif cond.operator == "<=":
                query = query.where(fact_alias.value_numeric <= cond.target_value)
            else:
                query = query.where(fact_alias.value_numeric == cond.target_value)
                
        return query.distinct()

    def _guard_screen_sources(
        self,
        conditions: tuple[_ScreenerCondition, ...],
        *,
        current_user_id: int,
        selected_source_type: str | None,
    ) -> _ScreenerSourceAuthority:
        evaluation_snapshot = database_evaluation_snapshot(self.db)
        evaluated_at = evaluation_snapshot.cutoff
        metric_keys = {condition.metric_key for condition in conditions}
        condition_repetitions = max(
            sum(condition.metric_key == key for condition in conditions)
            for key in metric_keys
        )
        candidate_fact_limit = min(
            MAX_SCREENER_GUARD_FACTS,
            (
                MAX_SCREENER_SQL_BIND_BUDGET
                - len(conditions) * SCREENER_CONDITION_BIND_OVERHEAD
            )
            // (SCREENER_ALLOWED_PAIR_BIND_COUNT * condition_repetitions),
        )
        facts = list(
            self.db.scalars(
                select(MetricFact).where(
                    MetricFact.metric_key.in_(metric_keys),
                    MetricFact.id.in_(
                        current_metric_fact_ids_at(
                            self.db,
                            knowledge_cutoff=evaluated_at,
                            knowledge_txid_snapshot=evaluation_snapshot.visibility_snapshot,
                            scope=CurrentnessScope(
                                metric_keys=tuple(sorted(metric_keys))
                            ),
                        )
                    ),
                    visible_metric_fact_predicate(
                        MetricFact, user_id=current_user_id
                    ),
                )
                .limit(candidate_fact_limit + 1)
                .execution_options(populate_existing=True, autoflush=False)
            ).all()
        )
        if len(facts) > candidate_fact_limit:
            raise CanonicalUnavailableError(
                {
                    "reason_code": "screener_source_guard_bound_exceeded",
                }
            )
        by_stock: dict[int, list[MetricFact]] = {}
        for fact in facts:
            by_stock.setdefault(fact.stock_id, []).append(fact)
        allowed: dict[tuple[int, str], list[tuple[int, Decimal]]] = {}
        for stock_id, stock_facts in by_stock.items():
            stock_facts = guard_reconciled_source_selection(
                stock_facts,
                consumer="screener",
                knowledge_cutoff=evaluated_at,
                selected_source_type=selected_source_type,
                session=self.db,
                user_id=current_user_id,
            )
            stock_facts = guard_sec_run_availability(
                self.db,
                stock_id=stock_id,
                facts=stock_facts,
                knowledge_cutoff=evaluated_at,
            )
            applicable = require_applicable_method_facts(
                self.db,
                stock_id=stock_id,
                facts=stock_facts,
                effective_as_of=evaluation_business_date(evaluated_at),
                knowledge_at=evaluated_at,
            )
            for fact in applicable:
                if (
                    isinstance(fact.id, int)
                    and not isinstance(fact.id, bool)
                    and fact.id > 0
                    and fact.metric_key in metric_keys
                    and fact.value_numeric is not None
                ):
                    allowed.setdefault((fact.stock_id, fact.metric_key), []).append(
                        (fact.id, fact.value_numeric)
                    )
        allowed_count = sum(len(pairs) for pairs in allowed.values())
        if allowed_count > MAX_SCREENER_GUARD_FACTS:
            raise CanonicalUnavailableError(
                {
                    "reason_code": "screener_source_guard_bound_exceeded",
                }
            )
        return _ScreenerSourceAuthority(
            evaluated_at=evaluated_at,
            allowed_by_stock_metric={
                key: tuple(sorted(set(pairs))) for key, pairs in allowed.items()
            },
        )
