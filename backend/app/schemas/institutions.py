from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class InstitutionResponse(BaseModel):
    id: int
    cik: str
    legal_name: str
    display_name: Optional[str]
    is_superinvestor: bool
    dataroma_code: Optional[str]
    match_status: str

    model_config = {"from_attributes": True}


class Filing13FResponse(BaseModel):
    id: int
    accession_no: str
    period_of_report: date
    filed_at: date
    form_type: str
    version_rank: int
    is_latest_for_period: bool
    has_confidential_treatment: bool
    reported_total_value_thousands: Optional[int]
    computed_total_value_thousands: Optional[int]

    model_config = {"from_attributes": True}


class Holding13FResponse(BaseModel):
    id: int
    cusip: str
    issuer_name: str
    title_of_class: Optional[str]
    value_thousands: int
    shares: Optional[int]
    share_type: Optional[str]
    put_call: Optional[str]
    investment_discretion: Optional[str]
    ticker: Optional[str] = None  # enriched from cusip_ticker_map

    model_config = {"from_attributes": True}
