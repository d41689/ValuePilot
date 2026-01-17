from typing import List, Dict, Any
from sqlalchemy.orm import Session, aliased
from sqlalchemy import select, and_
from app.models.stocks import Stock
from app.models.facts import MetricFact

class ScreenerService:
    def __init__(self, db: Session):
        self.db = db

    def execute_screen(self, rule_json: Dict[str, Any]) -> List[Stock]:
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
        
        if rule_json.get("type") == "AND":
             query = self._build_and_query(query, rule_json.get("conditions", []))
        else:
            # "OR" logic is trickier with simple inner joins (might need left joins + coalescing, or union)
            # Keeping V1 scope to AND logic for simplicity as per common screener MVPs.
            # If OR is strictly required, we'd use separate subqueries or aliases.
            pass

        return self.db.scalars(query).all()

    def _build_and_query(self, query, conditions: List[Dict[str, Any]]):
        for cond in conditions:
            metric_key = cond["metric"]
            operator = cond["operator"]
            target_value = cond["value"]
            
            # Create an alias for MetricFact for this specific condition
            fact_alias = aliased(MetricFact)
            
            # Join this alias
            query = query.join(
                fact_alias,
                and_(
                    Stock.id == fact_alias.stock_id,
                    fact_alias.metric_key == metric_key,
                    fact_alias.is_current.is_(True)
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
