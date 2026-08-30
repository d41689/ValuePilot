from __future__ import annotations

import ast
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[2] / "app"
NETWORK_MODULES = {"httpx", "requests", "urllib.request", "aiohttp"}


def _network_imports(tree: ast.AST) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return {
        name
        for name in imports
        if any(name == module or name.startswith(module + ".") for module in NETWORK_MODULES)
    }


def test_sec_url_owners_do_not_import_direct_network_clients() -> None:
    """SEC URL construction is allowed; external I/O belongs to RateGuardClient."""
    violations: list[str] = []
    for path in APP_ROOT.rglob("*.py"):
        if path == APP_ROOT / "rate_guard" / "client.py":
            continue
        source = path.read_text(encoding="utf-8")
        if ".sec.gov" not in source:
            continue
        imported = _network_imports(ast.parse(source, filename=str(path)))
        # EdgarClient only accepts httpx.Client as Rate Guard's injected transport.
        if path == APP_ROOT / "edgar" / "client.py":
            imported.discard("httpx")
        if imported:
            violations.append(
                f"{path.relative_to(APP_ROOT)} imports {sorted(imported)}"
            )

    assert violations == [], (
        "Files owning SEC URLs must route I/O through EdgarClient/RateGuardClient: "
        + "; ".join(violations)
    )
