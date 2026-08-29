import ast
import json
import operator
import re
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select, update
from app.models.facts import MetricFact, Formula, CalculatedRun
from app.models.stocks import Stock
from app.services.metric_fact_visibility import visible_metric_fact_predicate
from app.services.financial_truth_locks import (
    acquire_active_account_mutation_lock,
    acquire_user_stock_fact_lock,
)
from app.services.analysis_method_gate import (
    analysis_kind_for_metric,
    evaluate_analysis_method,
    metric_fact_matches_method,
)
from datetime import datetime, timezone

# Safe operators for formula evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.Pow: operator.pow,
}
CANONICAL_METRIC_KEY_RE = re.compile(
    r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)

class FormulaEngine:
    def __init__(self, db: Session):
        self.db = db

    def validate_and_extract_dependencies(self, expression: str) -> List[str]:
        """
        Parses the expression to ensure it's safe and extracts variable names (metric keys).
        """
        compiled = self.compile_expression(expression)
        dependencies: list[str] = []

        def collect(node: dict) -> None:
            if node["type"] == "variable":
                if node["name"] not in dependencies:
                    dependencies.append(node["name"])
                return
            if node["type"] == "unary":
                collect(node["operand"])
                return
            if node["type"] == "binary":
                collect(node["left"])
                collect(node["right"])

        collect(compiled["root"])
        return dependencies

    def compile_expression(self, expression: str) -> dict:
        """Compile the restricted formula language to its canonical DB AST."""
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise ValueError(f"Invalid syntax: {exc}") from exc

        operator_names = {
            ast.Add: "add",
            ast.Sub: "subtract",
            ast.Mult: "multiply",
            ast.Div: "divide",
            ast.Pow: "power",
            ast.USub: "negate",
        }

        def compile_node(node):
            if isinstance(node, ast.Constant):
                if isinstance(node.value, bool) or not isinstance(
                    node.value, (int, float)
                ):
                    raise ValueError("Only numeric constants are allowed")
                return {"type": "number", "value": node.value}
            if isinstance(node, ast.Name):
                if not CANONICAL_METRIC_KEY_RE.fullmatch(node.id):
                    raise ValueError("Invalid metric key")
                return {"type": "variable", "name": node.id}
            if isinstance(node, ast.Call):
                if (
                    not isinstance(node.func, ast.Name)
                    or node.func.id != "metric"
                    or node.keywords
                    or len(node.args) != 1
                    or not isinstance(node.args[0], ast.Constant)
                    or not isinstance(node.args[0].value, str)
                    or not CANONICAL_METRIC_KEY_RE.fullmatch(node.args[0].value)
                ):
                    raise ValueError(
                        'Only metric("canonical.key") references are allowed'
                    )
                return {"type": "variable", "name": node.args[0].value}
            if isinstance(node, ast.BinOp) and type(node.op) in operator_names:
                return {
                    "type": "binary",
                    "operator": operator_names[type(node.op)],
                    "left": compile_node(node.left),
                    "right": compile_node(node.right),
                }
            if isinstance(node, ast.UnaryOp) and type(node.op) in operator_names:
                return {
                    "type": "unary",
                    "operator": operator_names[type(node.op)],
                    "operand": compile_node(node.operand),
                }
            raise ValueError(f"Unsupported node type: {type(node)}")

        return {"version": "formula-ast-v1", "root": compile_node(tree.body)}

    def render_compiled_expression(self, compiled_ast: dict) -> str:
        """Render the canonical expression shown to users and frozen on publish."""
        operator_symbols = {
            "add": "+",
            "subtract": "-",
            "multiply": "*",
            "divide": "/",
            "power": "**",
        }

        def render(node: dict) -> str:
            node_type = node.get("type")
            if node_type == "number":
                return str(node["value"])
            if node_type == "variable":
                return f"metric({json.dumps(str(node['name']))})"
            if node_type == "unary" and node.get("operator") == "negate":
                return f"(-{render(node['operand'])})"
            if node_type == "binary" and node.get("operator") in operator_symbols:
                return (
                    f"({render(node['left'])} "
                    f"{operator_symbols[node['operator']]} "
                    f"{render(node['right'])})"
                )
            raise ValueError("Unsupported canonical formula AST")

        if compiled_ast.get("version") != "formula-ast-v1":
            raise ValueError("Unsupported canonical formula AST version")
        return render(compiled_ast["root"])

    def evaluate(self, expression: str, context: Dict[str, float]) -> float:
        """
        Evaluates the expression using the provided context (metric_key -> value).
        """
        return self.evaluate_compiled(self.compile_expression(expression), context)

    def evaluate_compiled(
        self, compiled_ast: dict, context: Dict[str, float]
    ) -> float:
        if compiled_ast.get("version") != "formula-ast-v1":
            raise ValueError("Unsupported canonical formula AST version")

        def evaluate_node(node: dict) -> float:
            node_type = node.get("type")
            if node_type == "number":
                return float(node["value"])
            if node_type == "variable":
                name = str(node["name"])
                if name not in context:
                    raise ValueError(f"Missing metric value: {name}")
                return context[name]
            if node_type == "unary" and node.get("operator") == "negate":
                return -evaluate_node(node["operand"])
            if node_type == "binary":
                operations = {
                    "add": operator.add,
                    "subtract": operator.sub,
                    "multiply": operator.mul,
                    "divide": operator.truediv,
                    "power": operator.pow,
                }
                operation = operations.get(node.get("operator"))
                if operation is None:
                    raise ValueError("Unsupported canonical formula operator")
                return operation(
                    evaluate_node(node["left"]),
                    evaluate_node(node["right"]),
                )
            raise ValueError("Unsupported canonical formula AST")

        return evaluate_node(compiled_ast["root"])

    def _eval_node(self, node, context):
        if isinstance(node, (ast.Num, ast.Constant)):
            return node.n
        elif isinstance(node, ast.Name):
            if node.id not in context:
                # Decide behavior: raise error or return 0/None?
                # For now, raise Error to ensure data completeness
                raise ValueError(f"Missing metric value: {node.id}")
            return context[node.id]
        elif isinstance(node, ast.BinOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type}")
            left = self._eval_node(node.left, context)
            right = self._eval_node(node.right, context)
            return SAFE_OPERATORS[op_type](left, right)
        elif isinstance(node, ast.UnaryOp):
            op_type = type(node.op)
            if op_type not in SAFE_OPERATORS:
                raise ValueError(f"Unsupported operator: {op_type}")
            operand = self._eval_node(node.operand, context)
            return SAFE_OPERATORS[op_type](operand)
        else:
            raise ValueError(f"Unsupported node type: {type(node)}")

    def run_formula(
        self,
        formula_id: int,
        stock_id: int,
        user_id: int,
        *,
        commit: bool = True,
    ) -> Optional[CalculatedRun]:
        """
        Executes a specific formula for a stock.
        1. Fetch formula
        2. Fetch current facts for dependencies
        3. Evaluate
        4. Save CalculatedRun & MetricFact
        """
        if not acquire_active_account_mutation_lock(self.db, user_id=user_id):
            raise ValueError("Account no longer accepts formula changes")
        acquire_user_stock_fact_lock(
            self.db, user_id=user_id, stock_id=stock_id
        )
        formula = self.db.scalar(
            select(Formula)
            .where(Formula.id == formula_id, Formula.user_id == user_id)
            .with_for_update()
        )
        if not formula:
            raise ValueError("Formula not found")
        compiled_ast = self.compile_expression(formula.expression)
        canonical_expression = self.render_compiled_expression(compiled_ast)
        if formula.compiled_ast_json is None:
            prior_run_exists = self.db.scalar(
                select(CalculatedRun.id)
                .where(CalculatedRun.formula_id == formula.id)
                .limit(1)
            )
            if prior_run_exists is not None:
                raise ValueError(
                    "Legacy published formula has no canonical AST; clone it before rerunning"
                )
            formula.compiled_ast_json = compiled_ast
            formula.expression = canonical_expression
            self.db.flush()
        elif formula.compiled_ast_json != compiled_ast:
            raise ValueError("Formula expression does not match its canonical AST")
        elif formula.expression != canonical_expression:
            raise ValueError("Formula expression is not canonically rendered")
        stock_exists = self.db.scalar(
            select(Stock.id).where(Stock.id == stock_id).with_for_update()
        )
        if stock_exists is None:
            raise ValueError("Stock not found")
        
        # Fetch dependencies
        # In V1, we fetch the *current* fact for each dependency
        # TODO: Handle period matching (e.g. Sales 2023 vs EPS 2023)
        # For now, we take the `is_current=True` fact.
        
        required_kinds = {
            kind
            for metric_key in formula.dependencies_json
            if (kind := analysis_kind_for_metric(metric_key)) is not None
        }
        for kind in required_kinds:
            method = evaluate_analysis_method(
                self.db,
                stock_id=stock_id,
                analysis_kind=kind,
                cutoff=datetime.now(timezone.utc),
            )
            if method.state != "eligible":
                return None

        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key.in_(formula.dependencies_json),
                MetricFact.is_current.is_(True),
                visible_metric_fact_predicate(MetricFact, user_id=user_id),
                MetricFact.source_type != "sec",
            )
        ).all()

        eligible_by_slot: dict[
            tuple[Optional[str], Optional[str], object, object],
            dict[str, list[MetricFact]],
        ] = {}
        for fact in facts:
            if fact.value_numeric is None:
                continue
            kind = analysis_kind_for_metric(fact.metric_key)
            if kind is not None and not metric_fact_matches_method(
                fact,
                evaluate_analysis_method(
                    self.db,
                    stock_id=stock_id,
                    analysis_kind=kind,
                    cutoff=datetime.now(timezone.utc),
                ),
            ):
                continue
            slot = (
                fact.period,
                fact.period_type,
                fact.period_end_date,
                fact.as_of_date,
            )
            eligible_by_slot.setdefault(slot, {}).setdefault(
                fact.metric_key, []
            ).append(fact)

        dependency_keys = list(dict.fromkeys(formula.dependencies_json))
        complete_slots = [
            slot
            for slot, facts_by_key in eligible_by_slot.items()
            if all(facts_by_key.get(key) for key in dependency_keys)
        ]
        if not complete_slots:
            return None

        def _slot_rank(slot):
            period, period_type, period_end_date, as_of_date = slot
            return (
                period_end_date or datetime.min.date(),
                as_of_date or datetime.min.date(),
                period or "",
                period_type or "",
            )

        selected_slot = max(complete_slots, key=_slot_rank)
        selected_by_key = eligible_by_slot[selected_slot]
        if any(len(selected_by_key[key]) != 1 for key in dependency_keys):
            # Multiple visible facts in the selected full period are an
            # unresolved source conflict. Older clean periods must not hide it.
            return None
        input_facts = [selected_by_key[key][0] for key in dependency_keys]
        period, period_type, period_end_date, as_of_date = selected_slot
        context = {fact.metric_key: fact.value_numeric for fact in input_facts}
        
        # Check if we have all dependencies
        missing = set(dependency_keys) - set(context.keys())
        if missing:
            # Cannot calculate yet
            # Log warning or create a failed run?
            return None

        try:
            result = self.evaluate_compiled(compiled_ast, context)
            
            # Create/Update CalculatedRun
            run = CalculatedRun(
                user_id=user_id,
                formula_id=formula.id,
                output_key_snapshot=formula.output_key,
                stock_id=stock_id,
                period=period,
                period_type=period_type,
                period_end_date=period_end_date,
                as_of_date=as_of_date,
                input_fact_ids_json=[fact.id for fact in input_facts],
                result_value_json={"value": result},
                is_dirty=False
            )
            self.db.add(run)
            self.db.flush()
            
            # Display names are mutable presentation. The persisted, validated
            # output key owns canonical fact identity and collision prevention.
            output_key = formula.output_key
            
            self.db.execute(
                update(MetricFact)
                .where(
                    MetricFact.user_id == user_id,
                    MetricFact.stock_id == stock_id,
                    MetricFact.metric_key == output_key,
                    MetricFact.source_type == "calculated",
                    MetricFact.is_current.is_(True),
                    MetricFact.value_json.op("?")("formula_id"),
                    MetricFact.value_json["formula_id"].as_string()
                    == str(formula.id),
                    MetricFact.period.is_not_distinct_from(period),
                    MetricFact.period_type.is_not_distinct_from(period_type),
                    MetricFact.period_end_date.is_not_distinct_from(period_end_date),
                )
                .values(is_current=False)
            )
            
            fact = MetricFact(
                user_id=user_id,
                stock_id=stock_id,
                metric_key=output_key,
                value_json={
                    "value": result,
                    "formula_id": formula.id,
                    "calculated_run_id": run.id,
                    "input_fact_ids": [fact.id for fact in input_facts],
                    "formula_lineage_version": "formula-v2",
                },
                value_numeric=result,
                period=period,
                period_type=period_type,
                period_end_date=period_end_date,
                as_of_date=as_of_date,
                source_type="calculated",
                source_ref_id=run.id,
                is_current=True
            )
            self.db.add(fact)
            if commit:
                self.db.commit()
            else:
                self.db.flush()
            return run
            
        except Exception:
            self.db.rollback()
            raise
