"""Static guard for the PRD §7.3 product holdings read contract."""

import re
from pathlib import Path

import app.api.v1.endpoints as endpoints_pkg
import app.services as services_pkg


RAW_HOLDINGS_QUERY = re.compile(r"\.query\(\s*Holding13F(?:\s*[,.)])")


def test_product_surfaces_do_not_query_holding13f_directly():
    endpoint_root = Path(endpoints_pkg.__file__).parent
    service_root = Path(services_pkg.__file__).parent
    product_files = list(endpoint_root.rglob("*.py")) + [
        service_root / "thirteenf_user_api.py",
        service_root / "thirteenf_filing_season.py",
        service_root / "oracles_lens" / "dashboard.py",
    ]

    offenders: list[str] = []
    for path in product_files:
        if not path.exists():
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if RAW_HOLDINGS_QUERY.search(line):
                offenders.append(f"{path.relative_to(endpoint_root.parent.parent.parent)}:{lineno}")

    assert not offenders, (
        "Product-facing 13F reads must build on active_hr_holdings_query; "
        "direct Holding13F queries found at: " + ", ".join(offenders)
    )
