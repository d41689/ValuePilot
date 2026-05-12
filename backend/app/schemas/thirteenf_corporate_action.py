from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class CorporateActionMappingPreviewRequest(BaseModel):
    cusip: str = Field(..., min_length=9, max_length=9)
    effective_from_quarter: str = Field(..., max_length=10)
    effective_to_quarter: Optional[str] = Field(None, max_length=10)


class CorporateActionMappingConfirmRequest(BaseModel):
    cusip: str = Field(..., min_length=9, max_length=9)
    new_ticker: Optional[str] = Field(None, max_length=10)
    new_issuer_name: Optional[str] = Field(None)
    effective_from_quarter: str = Field(..., max_length=10)
    effective_to_quarter: Optional[str] = Field(None, max_length=10)
    evidence_url: str = Field(..., min_length=1)
    reason: str = Field(..., min_length=1)
    prior_mapping_id: Optional[int] = Field(None)
