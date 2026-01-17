import re
from app.ingestion.parsers.base import BaseParser, IdentityInfo, ExtractionResult

class ValueLineV1Parser(BaseParser):
    def extract_identity(self) -> IdentityInfo:
        """
        Attempts to extract identity info from the first page header text.
        """
        # This is a heuristic implementation. 
        # Value Line headers are typically: 
        # [Line 1] PAGE NUMBER ... DATE
        # [Line 2] COMPANY NAME    TICKER (EXCHANGE)
        
        lines = self.text.split('\n')[:10] # Look at first 10 lines
        
        info = IdentityInfo()
        
        # Regex for Ticker/Exchange pattern like "MSFT (NDQ)" or "GOOG (NAS)"
        # Value Line often uses specific abbreviations like NDQ, NYS.
        ticker_pattern = re.compile(r'\b([A-Z]{1,5})\s*\(([A-Z]{3})\)')
        
        for line in lines:
            match = ticker_pattern.search(line)
            if match:
                info.ticker = match.group(1)
                info.exchange = match.group(2) # Value Line exchange code
                
                # Assume company name is on the same line or the one before, 
                # strictly strictly excluding the ticker part.
                # For now, let's just take the text before the match as a candidate
                pre_match = line[:match.start()].strip()
                if len(pre_match) > 3:
                    info.company_name = pre_match
                break
        
        # Fallback/Additional heuristics can go here
        return info

    def parse(self) -> list[ExtractionResult]:
        results = []
        
        # 1. Header Metrics (Recent Price, P/E, Yield)
        # Pattern: "RECENT PRICE 425.15" or "P/E RATIO 35.2"
        # Value Line often stacks these.
        
        # Recent Price
        price_match = re.search(r'RECENT\s+PRICE\s+(\d+\.?\d*)', self.text, re.IGNORECASE)
        if price_match:
            results.append(ExtractionResult(
                field_key="recent_price",
                raw_value_text=price_match.group(1),
                original_text_snippet=price_match.group(0),
                confidence_score=0.9
            ))

        # P/E Ratio
        pe_match = re.search(r'P/E\s+RATIO\s+(\d+\.?\d*)', self.text, re.IGNORECASE)
        if pe_match:
            results.append(ExtractionResult(
                field_key="pe_ratio",
                raw_value_text=pe_match.group(1),
                original_text_snippet=pe_match.group(0),
                confidence_score=0.9
            ))

        # Dividend Yield
        yield_match = re.search(r'DIV\'D\s+YLD\s+(\d+\.?\d*)%', self.text, re.IGNORECASE)
        if not yield_match:
             yield_match = re.search(r'DIVIDEND\s+YIELD\s+(\d+\.?\d*)%', self.text, re.IGNORECASE)
        
        if yield_match:
            results.append(ExtractionResult(
                field_key="dividend_yield",
                raw_value_text=yield_match.group(1) + "%", # preserve unit in raw text
                original_text_snippet=yield_match.group(0),
                confidence_score=0.9
            ))

        # 2. Target Price Ranges
        # Pattern: "2027-2029 PROJECTIONS ... High 100 Low 50" (Simplification)
        # This is harder without visual layout, but let's try a simple regex for the 18-month target
        # "Target Price Range 2024 2025"
        
        # For now, we'll stick to the header metrics as proof of concept for Phase 2.3
        
        return results