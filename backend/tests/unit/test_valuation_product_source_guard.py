"""Product valuation reads/writes must go through the canonical service."""
from __future__ import annotations

from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_product_modules_do_not_own_intrinsic_value_metric_keys():
    sanctioned = {
        BACKEND_ROOT / "app" / "services" / "valuation.py",
    }
    roots = [
        BACKEND_ROOT / "app" / "api" / "v1" / "endpoints",
        BACKEND_ROOT / "app" / "services" / "oracles_lens",
    ]
    violations: list[str] = []
    for root in roots:
        for path in root.rglob("*.py"):
            if path in sanctioned:
                continue
            text = path.read_text()
            if '"val.fair_value"' in text or '"target.price_18m.mid"' in text:
                violations.append(str(path.relative_to(BACKEND_ROOT)))
    assert violations == [], (
        "valuation product consumers must import canonical keys/readers from "
        f"app.services.valuation; direct owners: {violations}"
    )


def test_product_writers_publish_intrinsic_value_only_through_research_revisions():
    sanctioned = {
        BACKEND_ROOT / "app" / "services" / "valuation.py",
        BACKEND_ROOT / "app" / "services" / "research_cases.py",
    }
    violations: list[str] = []
    for root in [
        BACKEND_ROOT / "app" / "api" / "v1" / "endpoints",
        BACKEND_ROOT / "app" / "services",
    ]:
        for path in root.rglob("*.py"):
            if path in sanctioned:
                continue
            if "publish_user_intrinsic_value(" in path.read_text():
                violations.append(str(path.relative_to(BACKEND_ROOT)))
    assert violations == [], (
        "product valuation writes must be owned by the research revision service; "
        f"direct publishers: {violations}"
    )
