from datetime import date
from typing import Optional

from pydantic import BaseModel, Field

class CusipMappingCreate(BaseModel):
    cusip: str = Field(..., max_length=9, min_length=9)
    ticker: Optional[str] = Field(None, max_length=20)
    issuer_name: Optional[str] = Field(None)
    mapping_reason: Optional[str] = Field(None)
    confidence: str = Field("manual")
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None

class CusipMappingUpdate(BaseModel):
    ticker: Optional[str] = Field(None, max_length=20)
    issuer_name: Optional[str] = Field(None)
    mapping_reason: Optional[str] = Field(None)
    confidence: Optional[str] = Field(None)
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    is_active: Optional[bool] = None

class CusipMappingResponse(BaseModel):
    id: int
    cusip: str
    ticker: Optional[str]
    issuer_name: Optional[str]
    source: str
    mapping_reason: Optional[str]
    confidence: Optional[str]
    valid_from: Optional[date]
    valid_to: Optional[date]
    is_active: bool

    model_config = {"from_attributes": True}
