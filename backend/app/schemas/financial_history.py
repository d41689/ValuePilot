"""Read-only financial history; never a second persistent fact representation."""
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AnnualWindow(BaseModel):
    status: Literal["determined", "undetermined"]
    years: list[int] = Field(default_factory=list)
    anchor_fact_id: int | None = None
    reason_code: str | None = None


class FinancialHistoryRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_kind: Literal["fact", "slot_state", "metric_state", "filing_cycle_state"]
    row_key: str = Field(min_length=1)
    status: str
    reason_code: str | None = None
    metric_key: str | None = None
    fact_id: int | None = Field(default=None, gt=0)
    publication_id: int | None = Field(default=None, gt=0)
    value_numeric_exact: str | None = Field(default=None, pattern=r"^-?[0-9]+(?:\.[0-9]+)?$")
    value_text: str | None = None
    unit: str | None = None
    currency: str | None = None
    period_type: str | None = None
    period_basis: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    fiscal_year: int | None = None
    fiscal_quarter: int | None = None
    source_type: str | None = None
    source_role: str | None = None
    fact_nature: str | None = None
    comparison_identity: dict[str, Any] | None = None
    scope: dict[str, Any] | None = None
    evidence_capability: Literal["sec_statement", "document_review", "reference_only", "unavailable"] = "unavailable"
    document_id: int | None = None

    @model_validator(mode="after")
    def enforce_identity_and_redaction(self):
        if self.row_kind == "fact":
            if self.fact_id is None or self.row_key != f"fact:{self.fact_id}" or not self.metric_key:
                raise ValueError("fact rows require an immutable fact identity")
        elif any(value is not None for value in (
            self.fact_id, self.value_numeric_exact, self.value_text,
        )):
            raise ValueError("state rows cannot expose fact values or fact IDs")
        return self


class FinancialHistory(BaseModel):
    schema_version: Literal[1] = 1
    evaluated_at: datetime
    annual_window: AnnualWindow
    total_rows: int = Field(ge=0)
    available_fact_count: int = Field(ge=0)
    state_count: int = Field(ge=0)
    rows: list[FinancialHistoryRow]

    @model_validator(mode="after")
    def enforce_counts(self):
        facts = sum(row.row_kind == "fact" for row in self.rows)
        if (self.total_rows != len(self.rows) or self.available_fact_count != facts
                or self.state_count != len(self.rows) - facts):
            raise ValueError("financial history counts must describe the complete rows collection")
        if len({row.row_key for row in self.rows}) != len(self.rows):
            raise ValueError("financial history row keys must be unique")
        return self


class WorkspaceResponse(BaseModel):
    # The legacy workspace is intentionally retained, including its nullable
    # fields and legacy numeric wire encoding. Only the new projection is typed.
    model_config = ConfigDict(extra="allow")
    financial_history: FinancialHistory
