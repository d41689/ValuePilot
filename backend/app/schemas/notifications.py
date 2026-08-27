from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class SlackDestinationInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    webhook_url: str = Field(min_length=1, max_length=2048)
    consent: bool


class EmailDestinationInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    email: EmailStr
    consent: bool


class EmailVerificationInput(BaseModel):
    token: str = Field(min_length=16, max_length=200)


class SubscriptionInput(BaseModel):
    event_family: Literal[
        "followed_manager_filed",
        "followed_manager_position_changed",
        "intrinsic_value_threshold_crossed",
        "research_review_due",
        "research_coverage_changed",
        "filing_season_digest",
    ]
    destination_id: int | None = Field(default=None, gt=0)
    frequency: Literal["immediate", "daily_digest", "weekly_digest"] = "immediate"
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    quiet_start_local: str | None = Field(default=None, max_length=5)
    quiet_end_local: str | None = Field(default=None, max_length=5)
    cooldown_minutes: int = Field(default=60, ge=0, le=43200)
    threshold_ratio: float | None = Field(default=None, ge=0, le=0.95)
    hysteresis_ratio: float = Field(default=0.02, ge=0, le=0.25)
    is_enabled: bool = True

    @model_validator(mode="after")
    def validate_quiet_pair(self):
        if (self.quiet_start_local is None) != (self.quiet_end_local is None):
            raise ValueError("both quiet-hour boundaries are required")
        if self.event_family == "intrinsic_value_threshold_crossed":
            if self.threshold_ratio is None:
                raise ValueError("intrinsic-value alerts require threshold_ratio")
        elif self.threshold_ratio is not None:
            raise ValueError("threshold_ratio is only valid for intrinsic-value alerts")
        return self


class DestinationTestInput(BaseModel):
    confirm_send: bool

    @field_validator("confirm_send")
    @classmethod
    def require_confirmation(cls, value: bool) -> bool:
        if not value:
            raise ValueError("explicit confirmation is required")
        return value
