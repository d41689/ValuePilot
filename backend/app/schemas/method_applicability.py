from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


EconomicClass = Literal[
    "ordinary", "bank", "insurer", "reit", "other_financial", "unclassified"
]
RiskAttribute = Literal["high_sbc", "acquisitive", "cyclical", "commodity_exposed"]


class ClassificationReviewCreate(BaseModel):
    economic_class: EconomicClass
    effective_from: date
    effective_to: date | None = None
    review_reason: str = Field(min_length=1, max_length=4000)
    supersedes_review_id: int | None = Field(default=None, gt=0)

    model_config = {"extra": "forbid"}


class RiskReviewCreate(BaseModel):
    risk_attribute: RiskAttribute
    is_present: bool
    effective_from: date
    effective_to: date | None = None
    review_reason: str = Field(min_length=1, max_length=4000)
    supersedes_review_id: int | None = Field(default=None, gt=0)

    model_config = {"extra": "forbid"}


class ClassificationReviewRead(BaseModel):
    id: int
    stock_id: int
    economic_class: str
    effective_from: date
    effective_to: date | None
    known_at: datetime
    reviewer_user_id: int
    review_reason: str
    supersedes_review_id: int | None
    created_at: datetime
    created_txid: int

    model_config = {"from_attributes": True}


class RiskReviewRead(BaseModel):
    id: int
    stock_id: int
    risk_attribute: str
    is_present: bool
    effective_from: date
    effective_to: date | None
    known_at: datetime
    reviewer_user_id: int
    review_reason: str
    supersedes_review_id: int | None
    created_at: datetime
    created_txid: int

    model_config = {"from_attributes": True}
