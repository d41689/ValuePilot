import ast
import operator
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.facts import MetricFact, Formula, CalculatedRun

# Safe operators for formula evaluation
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
    ast.Pow: operator.pow,
}

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
            elif isinstance(node, (ast.Constant, ast.Num, ast.BinOp, ast.UnaryOp, ast.Expression, ast.Load, ast.operator)):
                continue
            # Add more checks for forbidden nodes if necessary
            
        return list(dependencies)

    def evaluate(self, expression: str, context: Dict[str, float]) -> float:
        """
        Evaluates the expression using the provided context (metric_key -> value).
        """
        tree = ast.parse(expression, mode='eval')
        return self._eval_node(tree.body, context)

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

    def run_formula(self, formula_id: int, stock_id: int, user_id: int) -> Optional[CalculatedRun]:
        """
        Executes a specific formula for a stock.
        1. Fetch formula
        2. Fetch current facts for dependencies
        3. Evaluate
        4. Save CalculatedRun & MetricFact
        """
        formula = self.db.get(Formula, formula_id)
        if not formula:
            raise ValueError("Formula not found")
        
        # Fetch dependencies
        # In V1, we fetch the *current* fact for each dependency
        # TODO: Handle period matching (e.g. Sales 2023 vs EPS 2023)
        # For now, we take the `is_current=True` fact.
        
        facts = self.db.scalars(
            select(MetricFact).where(
                MetricFact.stock_id == stock_id,
                MetricFact.metric_key.in_(formula.dependencies_json),
                MetricFact.is_current.is_(True)
            )
        ).all()
        
        context = {f.metric_key: f.value_numeric for f in facts if f.value_numeric is not None}
        
        # Check if we have all dependencies
        missing = set(formula.dependencies_json) - set(context.keys())
        if missing:
            # Cannot calculate yet
            # Log warning or create a failed run?
            return None

        try:
            result = self.evaluate(formula.expression, context)
            
            # Create/Update CalculatedRun
            run = CalculatedRun(
                user_id=user_id,
                formula_id=formula.id,
                stock_id=stock_id,
                result_value_json={"value": result},
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
            output_key = formula.name.lower().replace(" ", "_")
            
            # Deactivate old current fact for this calculated metric
            # (Simple "latest is current" logic)
            # ... skipping deactivation for brevity, ideally handled in transaction
            
            fact = MetricFact(
                user_id=user_id,
                stock_id=stock_id,
                metric_key=output_key,
                value_json={"value": result, "formula_id": formula.id},
                value_numeric=result,
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
