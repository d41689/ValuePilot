from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class IdentityInfo:
    ticker: Optional[str] = None
    exchange: Optional[str] = None
    company_name: Optional[str] = None

@dataclass
class ExtractionResult:
    field_key: str
    raw_value_text: str
    original_text_snippet: Optional[str] = None
    parsed_value_json: Optional[Dict[str, Any]] = None
    page_number: int = 1
    confidence_score: float = 1.0
    bbox_json: Optional[Dict[str, Any]] = None

class BaseParser(ABC):
    def __init__(self, text: str):
        self.text = text

    @abstractmethod
    def extract_identity(self) -> IdentityInfo:
        """
        Extracts ticker, exchange, and company name to help with stock resolution.
        """
        pass

    @abstractmethod
    def parse(self) -> list[ExtractionResult]:
        """
        Main method to extract all metrics.
        Returns a list of ExtractionResult objects.
        """
        pass
