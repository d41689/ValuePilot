from typing import List, Dict, Any, Callable
from datetime import date, datetime, timezone
from sqlalchemy.orm import Session, aliased
from decimal import Decimal
from sqlalchemy import select, and_, or_
from app.models.stocks import Stock
from app.models.facts import MetricFact
from app.services.canonical_financials import (
    CANONICAL_SOURCE_TYPES,
    guard_sec_run_availability,
    require_applicable_method_facts,
    visible_metric_fact_predicate,
)
from app.services.source_reconciliation import guard_reconciled_source_selection

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
    ) -> dict[int, dict[str, Any]]:
        if not stock_ids:
            return {}

        fact_nature_expr = MetricFact.value_json["fact_nature"].as_string()
        stmt = select(MetricFact).where(
            MetricFact.stock_id.in_(stock_ids),
            MetricFact.metric_key.in_(self.metric_keys()),
            MetricFact.is_current.is_(True),
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
                knowledge_cutoff=datetime.now(timezone.utc),
                selected_source_type=selected_source_type,
                session=self.db,
                user_id=current_user_id,
            )
            selected = guard_sec_run_availability(
                self.db,
                stock_id=stock_id,
                facts=selected,
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

    def execute_screen(self, rule_json: Dict[str, Any], current_user_id: int) -> List[Stock]:
        """
        Executes a screen based on the rule definition.
        
        Rule JSON Structure V1:
        {
            "type": "AND", # or OR
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
        selected_source_type = rule_json.get("source_type")
        if selected_source_type is not None and selected_source_type not in CANONICAL_SOURCE_TYPES:
            raise ValueError("unsupported source_type selection")
        conditions = rule_json.get("conditions", [])
        self._guard_screen_sources(
            conditions,
            current_user_id=current_user_id,
            selected_source_type=selected_source_type,
        )
        
        if rule_json.get("type") == "AND":
             query = self._build_and_query(
                 query,
                 conditions,
                 current_user_id,
                 selected_source_type=selected_source_type,
             )
        else:
            # "OR" logic is trickier with simple inner joins (might need left joins + coalescing, or union)
            # Keeping V1 scope to AND logic for simplicity as per common screener MVPs.
            # If OR is strictly required, we'd use separate subqueries or aliases.
            pass

        return self.db.scalars(query).all()

    def _build_and_query(
        self,
        query,
        conditions: List[Dict[str, Any]],
        current_user_id: int,
        *,
        selected_source_type: str | None,
    ):
        for cond in conditions:
            metric_key = self._canonical_metric_key(cond["metric"])
            operator = cond["operator"]
            target_value = Decimal(str(cond["value"]))
            
            # Create an alias for MetricFact for this specific condition
            fact_alias = aliased(MetricFact)
            
            # Join this alias
            query = query.join(
                fact_alias,
                and_(
                    Stock.id == fact_alias.stock_id,
                    fact_alias.metric_key == metric_key,
                    fact_alias.is_current.is_(True),
                    visible_metric_fact_predicate(fact_alias, user_id=current_user_id),
                    *(
                        [fact_alias.source_type == selected_source_type]
                        if selected_source_type is not None
                        else []
                    ),
                )
            )
            
            # Apply filter
            if operator == ">":
                query = query.where(fact_alias.value_numeric > target_value)
            elif operator == ">=":
                query = query.where(fact_alias.value_numeric >= target_value)
            elif operator == "<":
                query = query.where(fact_alias.value_numeric < target_value)
            elif operator == "<=":
                query = query.where(fact_alias.value_numeric <= target_value)
            elif operator == "=" or operator == "==":
                query = query.where(fact_alias.value_numeric == target_value)
                
        return query

    def _guard_screen_sources(
        self,
        conditions: list[dict[str, Any]],
        *,
        current_user_id: int,
        selected_source_type: str | None,
    ) -> None:
        metric_keys = {
            self._canonical_metric_key(str(condition.get("metric")))
            for condition in conditions
            if condition.get("metric") is not None
        }
        if not metric_keys:
            return
        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.metric_key.in_(metric_keys),
                MetricFact.is_current.is_(True),
                visible_metric_fact_predicate(MetricFact, user_id=current_user_id),
            )
        ).all()
        by_stock: dict[int, list[MetricFact]] = {}
        for fact in facts:
            by_stock.setdefault(fact.stock_id, []).append(fact)
        for stock_id, stock_facts in by_stock.items():
            evaluated_at = datetime.now(timezone.utc)
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
            )
            require_applicable_method_facts(
                self.db,
                stock_id=stock_id,
                facts=stock_facts,
                effective_as_of=date.today(),
                knowledge_at=evaluated_at,
            )
