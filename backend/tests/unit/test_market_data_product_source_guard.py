"""Prevent product consumers from re-inventing canonical EOD selection."""
from __future__ import annotations

from pathlib import Path
import re


APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SANCTIONED = {
    APP_ROOT / "services" / "market_data_service.py",
}
DIRECT_READ = re.compile(
    r"(?:query|select)\(StockPrice\)|(?:session|db)\.get\(StockPrice"
)


def test_product_stock_price_reads_use_canonical_market_data_service():
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path in SANCTIONED or "models" in path.parts:
            continue
        if DIRECT_READ.search(path.read_text()):
            violations.append(str(path.relative_to(APP_ROOT)))

    assert violations == [], (
        "Direct StockPrice product reads bypass canonical source/freshness "
        f"selection: {violations}"
    )
