from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.core.currencies import normalize_iso4217_currency
from app.services.dcf_inputs import DCF_MAX_ASSUMPTIONS_BYTES


class ResearchValuationSave(BaseModel):
    """A product valuation write that must also create an auditable revision."""

    metric_key: str = Field(min_length=1, max_length=120)
    value_numeric: Decimal | None = Field(
        default=None, gt=0, max_digits=24, decimal_places=6
    )
    valuation_low: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    valuation_high: Decimal | None = Field(default=None, gt=0, max_digits=24, decimal_places=6)
    as_of_date: date | None = None
    source: Literal["manual", "watchlist", "dcf"] = "manual"
    valuation_currency: str | None = Field(default=None, max_length=3)
    pool_id: int | None = Field(default=None, gt=0)
    assumptions: list[dict[str, Any]] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_range_and_origin(self):
        if (
            self.source == "dcf"
            and len(json.dumps(self.assumptions, separators=(",", ":")).encode("utf-8"))
            > DCF_MAX_ASSUMPTIONS_BYTES
        ):
            raise ValueError("assumptions exceed the 64 KiB contract limit")
        if self.source != "dcf" and self.value_numeric is None:
            raise ValueError("value_numeric is required for manual and watchlist valuations")
        if self.value_numeric is None:
            if self.valuation_low is not None or self.valuation_high is not None:
                raise ValueError("valuation bounds require value_numeric")
        else:
            low = (
                self.valuation_low
                if self.valuation_low is not None
                else self.value_numeric
            )
            high = (
                self.valuation_high
                if self.valuation_high is not None
                else self.value_numeric
            )
            if not low <= self.value_numeric <= high:
                raise ValueError("valuation must satisfy low <= value_numeric <= high")
        if self.source != "watchlist" and self.pool_id is not None:
            raise ValueError("pool_id is only valid for watchlist valuations")
        if self.valuation_currency is not None:
            self.valuation_currency = normalize_iso4217_currency(self.valuation_currency)
            if self.valuation_currency is None:
                raise ValueError("valuation_currency must be an active monetary ISO 4217 code")
        if self.source == "dcf" and self.valuation_currency is None:
            raise ValueError("valuation_currency is required for DCF valuations")
        return self
