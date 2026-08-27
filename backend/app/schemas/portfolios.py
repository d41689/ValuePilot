from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator


class ManualPortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=4000)

    @field_validator("name", "description")
    @classmethod
    def normalize_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ManualPortfolioArchive(BaseModel):
    expected_version: int = Field(ge=1)


class _ResearchLink(BaseModel):
    research_case_id: int | None = Field(default=None, gt=0)
    research_revision_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def revision_requires_case(self):
        if self.research_revision_id is not None and self.research_case_id is None:
            raise ValueError("research_revision_id requires research_case_id")
        return self


class ManualPositionCreate(_ResearchLink):
    stock_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=28, decimal_places=8)
    average_unit_cost: Decimal | None = Field(
        default=None, gt=0, max_digits=24, decimal_places=6
    )
    currency: str = Field(min_length=3, max_length=3)
    opened_on: date
    reason: str | None = Field(default=None, max_length=4000)

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter code")
        return normalized

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ManualPositionResize(_ResearchLink):
    expected_version: int = Field(ge=1)
    quantity: Decimal = Field(gt=0, max_digits=28, decimal_places=8)
    average_unit_cost: Decimal | None = Field(
        default=None, gt=0, max_digits=24, decimal_places=6
    )
    reason: str | None = Field(default=None, max_length=4000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ManualPositionClose(_ResearchLink):
    expected_version: int = Field(ge=1)
    closed_on: date
    reason: str | None = Field(default=None, max_length=4000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None


class ManualPositionReview(_ResearchLink):
    expected_version: int = Field(ge=1)
    reviewed_on: date
    reason: str = Field(min_length=1, max_length=4000)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("review reason is required")
        return normalized
