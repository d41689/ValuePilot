import ast
import operator
from decimal import Decimal, localcontext
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.facts import MetricFact, Formula, CalculatedRun
from app.services.numeric_persistence import persist_numeric_38_12
from app.services.canonical_financials import (
    database_evaluation_cutoff,
    evaluation_business_date,
    guard_sec_run_availability,
    is_reserved_system_output_key,
    require_applicable_method_facts,
    visible_metric_fact_predicate,
)
from app.services.source_reconciliation import (
    CanonicalReconciliationError,
    guard_reconciled_source_selection,
)

# Safe operators for formula evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.Pow: operator.pow,
}
SAFE_COMPARISONS = {ast.Lt: operator.lt, ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq, ast.NotEq: operator.ne}


class ReservedMethodFormulaOutputError(ValueError):
    code = "method_reserved_formula_output"

    def __init__(self, metric_key: str):
        self.metric_key = metric_key
        super().__init__(
            f"Formula output {metric_key!r} is reserved for a reviewed system method."
        )


class FormulaEngine:
    def __init__(self, db: Session):
        self.db = db

    def validate_and_extract_dependencies(self, expression: str) -> List[str]:
        """
        Parses the expression to ensure it's safe and extracts variable names (metric keys).
        """
        try:
            tree = ast.parse(expression, mode='eval')
        except SyntaxError as e:
            raise ValueError(f"Invalid syntax: {e}")

        dependencies = set()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                dependencies.add(node.id)
            elif isinstance(node, ast.Call):
                raise ValueError("Function calls are not allowed in V1 formulas.")
            elif isinstance(node, (ast.Constant, ast.Num, ast.BinOp, ast.UnaryOp, ast.Compare, ast.Expression, ast.Load, ast.operator, ast.cmpop)):
                continue
            # Add more checks for forbidden nodes if necessary
            
        return list(dependencies)

    def evaluate(self, expression: str, context: Dict[str, Decimal]) -> Decimal | bool:
        """
        Evaluates the expression using the provided context (metric_key -> value).
        """
        tree = ast.parse(expression, mode='eval')
        with localcontext() as decimal_context:
            decimal_context.prec = 50
            return self._eval_node(tree.body, context, expression)

    def _eval_node(self, node, context, expression):
        if isinstance(node, (ast.Num, ast.Constant)):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError("Only decimal numeric constants are allowed")
            lexical = ast.get_source_segment(expression, node)
            if lexical is None or "e" in lexical.lower():
                raise ValueError("Scientific notation is not allowed")
            return Decimal(lexical)
        elif isinstance(node, ast.Name):
            if node.id not in context:
                # Decide behavior: raise error or return 0/None?
                # For now, raise Error to ensure data completeness
                raise ValueError(f"Missing metric value: {node.id}")
            value = context[node.id]
            if not isinstance(value, (int, float, Decimal)) or isinstance(value, bool):
                raise ValueError(f"Non-numeric metric value: {node.id}")
            return value if isinstance(value, Decimal) else Decimal(str(value))
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type}")
            left = self._eval_node(node.left, context, expression)
            right = self._eval_node(node.right, context, expression)
            return SAFE_OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type}")
            operand = self._eval_node(node.operand, context, expression)
            return SAFE_OPERATORS[op_type](operand)
        elif isinstance(node, ast.Compare):
            if len(node.ops) != 1 or len(node.comparators) != 1 or type(node.ops[0]) not in SAFE_COMPARISONS:
                raise ValueError("Only one safe comparison is allowed")
            return SAFE_COMPARISONS[type(node.ops[0])](self._eval_node(node.left, context, expression), self._eval_node(node.comparators[0], context, expression))
        else:
            raise ValueError(f"Unsupported node type: {type(node)}")

    def run_formula(
        self,
        formula_id: int,
        stock_id: int,
        user_id: int,
        *,
        selected_source_type: str | None = None,
    ) -> Optional[CalculatedRun]:
        """
        Executes a specific formula for a stock.
        1. Fetch formula
        2. Fetch current facts for dependencies
        3. Evaluate
        4. Save CalculatedRun & MetricFact
        """
        formula = self.db.get(Formula, formula_id)
        if not formula or formula.user_id != user_id:
            raise ValueError("Formula not found")
        output_key = formula.name.lower().replace(" ", "_")
        if is_reserved_system_output_key(output_key):
            raise ReservedMethodFormulaOutputError(output_key)
        
        # Fetch dependencies
        # In V1, we fetch the *current* fact for each dependency
        # TODO: Handle period matching (e.g. Sales 2023 vs EPS 2023)
        # For now, we take the `is_current=True` fact.
        
        evaluated_at = database_evaluation_cutoff(self.db)
        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key.in_(formula.dependencies_json),
                MetricFact.is_current.is_(True),
                MetricFact.created_at <= evaluated_at,
                MetricFact.updated_at <= evaluated_at,
                visible_metric_fact_predicate(MetricFact, user_id=user_id),
            )
        ).all()
        facts = guard_reconciled_source_selection(
            facts,
            consumer="formula",
            knowledge_cutoff=evaluated_at,
            selected_source_type=selected_source_type,
            session=self.db,
            user_id=user_id,
        )
        facts = guard_sec_run_availability(
            self.db,
            stock_id=stock_id,
            facts=facts,
            knowledge_cutoff=evaluated_at,
        )
        facts = require_applicable_method_facts(
            self.db,
            stock_id=stock_id,
            facts=facts,
            effective_as_of=evaluation_business_date(evaluated_at),
            knowledge_at=evaluated_at,
        )
        facts_by_metric = {
            metric_key: [fact for fact in facts if fact.metric_key == metric_key]
            for metric_key in formula.dependencies_json
        }
        ambiguous = {
            metric_key: rows
            for metric_key, rows in facts_by_metric.items()
            if len(rows) > 1
        }
        if ambiguous:
            raise CanonicalReconciliationError(
                consumer="formula",
                blocking_items=[
                    {
                        "metric_key": metric_key,
                        "status": "unresolved",
                        "reason_code": "formula_period_selection_required",
                        "blocking": True,
                        "fact_ids": sorted(fact.id for fact in rows),
                        "source_types": sorted({fact.source_type for fact in rows}),
                    }
                    for metric_key, rows in sorted(ambiguous.items())
                ],
            )
        context = {f.metric_key: f.value_numeric for f in facts if f.value_numeric is not None}
        
        # Check if we have all dependencies
        missing = set(formula.dependencies_json) - set(context.keys())
        if missing:
            # Cannot calculate yet
            # Log warning or create a failed run?
            return None

        try:
            result = self.evaluate(formula.expression, context)
            if isinstance(result, bool):
                raise ValueError("Comparison formulas cannot be persisted as numeric facts")
            persisted_result = persist_numeric_38_12(result)
            
            # Create/Update CalculatedRun
            run = CalculatedRun(
                user_id=user_id,
                formula_id=formula.id,
                stock_id=stock_id,
                result_value_json={"value": format(persisted_result, "f")},
                is_dirty=False
            )
            self.db.add(run)
            self.db.flush()
            
            # Create authoritative MetricFact
            # Use formula name as the metric key? Or a separate field?
            # PRD says: metric_key = formula-defined output key. 
            # Let's assume formula.name IS the key for simplicity in V1, 
            # or we add an output_key field to Formula. 
            # Using formula.name as key (normalized).
            # Deactivate old current fact for this calculated metric
            # (Simple "latest is current" logic)
            # ... skipping deactivation for brevity, ideally handled in transaction
            
            fact = MetricFact(
                user_id=user_id,
                stock_id=stock_id,
                metric_key=output_key,
                value_json={
                    "value": format(persisted_result, "f"),
                    "formula_id": formula.id,
                    "source_types": sorted({f.source_type for f in facts}),
                    "user_authored_formula": True,
                    "fact_nature": "derived_actual",
                    "calculation_version": "formula-engine-v1",
                    "inputs": [
                        {
                            "fact_id": source.id,
                            "metric_key": source.metric_key,
                            "source_type": source.source_type,
                        }
                        for source in sorted(facts, key=lambda item: item.id)
                    ],
                },
                value_numeric=persisted_result,
                source_type="calculated",
                source_ref_id=run.id,
                is_current=True
            )
            self.db.add(fact)
            self.db.commit()
            return run
            
        except Exception as e:
            # Log error
            raise e
