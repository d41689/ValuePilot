from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator, model_validator


OriginType = Literal[
    "manual",
    "ticker_search",
    "watchlist",
    "screener",
    "oracle_lens",
    "manager_holding",
    "manager_change",
]
CaseState = Literal["queued", "researching", "monitoring", "closed", "voided"]
Decision = Literal["watch", "own", "pass"]
DecisionAction = Literal["draft", "decision", "review"]
EvidenceType = Literal[
    "pdf_document",
    "metric_fact",
    "filing_13f",
    "holding_13f",
    "ownership_change",
    "oracles_lens_signal",
    "stock_price",
    "user_note",
    "external_url",
]


class ResearchOriginInput(BaseModel):
    origin_type: OriginType
    origin_key: str = Field(min_length=1, max_length=240)
    source_version: str = Field(min_length=1, max_length=120)
    source_ref: dict[str, Any] | None = None


class ResearchCaseCreate(BaseModel):
    stock_id: int = Field(gt=0)
    origin: ResearchOriginInput


class EvidenceInput(BaseModel):
    source_type: EvidenceType
    source_id: int | None = Field(default=None, gt=0)
    url: str | None = Field(default=None, max_length=2048)
    label: str = Field(min_length=1, max_length=240)
    source_date: date | None = None
    claim: str = Field(min_length=1, max_length=4000)

    @model_validator(mode="after")
    def validate_reference(self):
        if self.source_type == "external_url":
            if not self.url:
                raise ValueError("external_url evidence requires url")
            parsed = urlsplit(self.url)
            if (
                parsed.scheme.lower() != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("external evidence must use a credential-free HTTPS URL")
            self.url = urlunsplit(
                ("https", parsed.netloc.lower(), parsed.path or "/", parsed.query, "")
            )
            if self.source_id is not None:
                raise ValueError("external_url evidence cannot have source_id")
        elif self.source_type == "user_note":
            if self.url is not None:
                raise ValueError("user_note evidence cannot have url")
        else:
            if self.source_id is None:
                raise ValueError(f"{self.source_type} evidence requires source_id")
            if self.url is not None:
                raise ValueError("internal evidence cannot have url")
        return self


class ResearchRevisionCreate(BaseModel):
    expected_head_revision_number: int = Field(ge=0)
    target_state: CaseState
    thesis: str | None = Field(default=None, max_length=20000)
    variant_view: str | None = Field(default=None, max_length=12000)
    decision_reason: str | None = Field(default=None, max_length=12000)
    assumptions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    risks: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    evidence: list[EvidenceInput] = Field(default_factory=list, max_length=100)
    valuation_low: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    valuation_base: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    valuation_high: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    valuation_currency: str | None = Field(default=None, max_length=3)
    valuation_unavailable_reason: str | None = Field(default=None, max_length=1000)
    valuation_as_of_date: date | None = None
    decision: Decision | None = None
    next_review_on: date | None = None
    void_reason: str | None = Field(default=None, max_length=2000)
    correlation_id: str | None = Field(default=None, max_length=80)
    decision_action: DecisionAction = "draft"

    @field_validator(
        "thesis", "variant_view", "decision_reason", "valuation_unavailable_reason", "void_reason"
    )
    @classmethod
    def blank_text_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("valuation_currency")
    @classmethod
    def normalize_currency(cls, value: str | None) -> str | None:
        return value.upper() if value else None

    @model_validator(mode="after")
    def validate_state_and_valuation(self):
        values = (self.valuation_low, self.valuation_base, self.valuation_high)
        has_any_value = any(value is not None for value in values)
        has_all_values = all(value is not None for value in values)
        if has_any_value and not has_all_values:
            raise ValueError("valuation low, base, and high are required together")
        if has_all_values:
            assert self.valuation_low is not None
            assert self.valuation_base is not None
            assert self.valuation_high is not None
            if not self.valuation_low <= self.valuation_base <= self.valuation_high:
                raise ValueError("valuation must satisfy low <= base <= high")
            if self.valuation_currency != "USD":
                raise ValueError("V1 research valuation currency must be USD")
            if self.valuation_unavailable_reason:
                raise ValueError("valuation and unavailable reason are mutually exclusive")
            if self.valuation_as_of_date is None:
                raise ValueError("valuation_as_of_date is required with valuation")
        elif self.valuation_currency is not None:
            raise ValueError("valuation_currency requires a complete valuation range")
        elif self.valuation_unavailable_reason and self.valuation_as_of_date is None:
            raise ValueError("valuation_as_of_date is required with unavailable reason")

        if self.decision is not None and not (
            has_all_values or self.valuation_unavailable_reason
        ):
            raise ValueError("a decision requires a valuation range or unavailable reason")
        if self.target_state in {"queued", "researching"}:
            if self.decision is not None or self.next_review_on is not None or self.void_reason:
                raise ValueError("queued/researching cases cannot carry a current decision or review date")
        elif self.target_state == "monitoring":
            if self.decision not in {"watch", "own"} or self.next_review_on is None:
                raise ValueError("monitoring requires watch/own and next_review_on")
            if self.void_reason:
                raise ValueError("monitoring cannot have void_reason")
        elif self.target_state == "closed":
            if self.decision != "pass" or self.next_review_on is not None or self.void_reason:
                raise ValueError("closed requires pass and no review/void reason")
        elif self.target_state == "voided":
            if self.decision is not None or self.next_review_on is not None or not self.void_reason:
                raise ValueError("voided requires only a non-blank void_reason")
        if self.decision_action in {"decision", "review"} and self.decision is None:
            raise ValueError("decision and review actions require an explicit decision")
        if self.decision_action == "review" and self.target_state != "monitoring":
            raise ValueError("review actions require a monitoring target state")
        return self


class ResearchRevisionRedact(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 10:
            raise ValueError("redaction reason must be at least 10 characters")
        return normalized


class ResearchInboxSnooze(BaseModel):
    snoozed_until: date
