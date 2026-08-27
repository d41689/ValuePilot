"""CLI for the read-only quant Phase 1 data-sufficiency audit.

Run inside Docker from /code:

    python -m app.cli.quant_data_audit \
      --user-id 775 \
      --evaluated-at 2026-07-21T12:00:00+00:00 \
      --json-output docs/audits/quant/2026-07-21_1-r0-data-sufficiency.json \
      --markdown-output docs/audits/quant/2026-07-21_1-r0-data-sufficiency.md
"""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import typer

from app.core.db import SessionLocal
from app.services.quant_trading.data_audit import (
    SourceReadiness,
    begin_read_only_development_audit,
    build_audit_report,
    render_markdown,
)


app = typer.Typer(add_completion=False)


@app.command()
def audit(
    user_id: int = typer.Option(..., min=1, help="Owner of user-scoped Value Line facts."),
    evaluated_at: str = typer.Option(
        ...,
        help="Timezone-aware ISO-8601 audit timestamp.",
    ),
    json_output: Path = typer.Option(..., help="Machine-readable report path."),
    markdown_output: Path = typer.Option(..., help="Human-readable report path."),
) -> None:
    """Audit current development data without mutating the database."""

    try:
        evaluated = datetime.fromisoformat(evaluated_at)
        if evaluated.tzinfo is None:
            raise ValueError("timezone offset is required")
    except ValueError as exc:
        raise typer.BadParameter(f"invalid evaluated-at: {exc}") from exc

    session = SessionLocal()
    try:
        begin_read_only_development_audit(session)
        # Current policy is explicit: upload-only Value Line and no authorized
        # survivorship-free commercial backbone. Do not expose boolean CLI
        # switches that could launder an unevidenced source into a GO result.
        report = build_audit_report(
            session,
            user_id=user_id,
            evaluated_at=evaluated,
            readiness=SourceReadiness(),
        )
        session.rollback()
    finally:
        session.close()

    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)
    json_output.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    markdown_output.write_text(render_markdown(report), encoding="utf-8")
    typer.echo(
        f"{report['gate']['overall_1_r0_gate']}: "
        f"JSON={json_output} Markdown={markdown_output}"
    )


if __name__ == "__main__":
    app()
