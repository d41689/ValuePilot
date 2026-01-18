import re
from typing import Dict, Any, Optional
from app.ingestion.parsers.base import BaseParser, IdentityInfo, ExtractionResult

class ValueLineV1Parser(BaseParser):
    def __init__(self, text: str, page_words: Optional[dict[int, list[dict[str, Any]]]] = None):
        super().__init__(text)
        self.page_words = page_words or {}

    def extract_identity(self) -> IdentityInfo:
        """
        Attempts to extract identity info from the first page header text.
        """
        raw_lines = self.text.split('\n')
        lines = [line.strip() for line in raw_lines if line.strip()]
        search_lines = lines[:30]  # Look beyond the first 10 lines for multi-page headers
        
        info = IdentityInfo()
        
        exchange_codes = [
            "NYSE",
            "NASDAQ",
            "NDQ",
            "NSDQ",
            "ASE",
            "AMEX",
            "NAS",
            "NMS",
            "NCM",
            "NGM",
            "OTC",
            "PNK",
            "TSE",
            "TSX",
        ]
        exchange_code_set = {code.upper() for code in exchange_codes}
        exchange_tokens = "(" + "|".join(exchange_codes) + ")"
        ticker_pattern = r"[A-Z]{1,5}(?:\\.[A-Z]{1,4})?"
        exchange_map = {
            "NASDAQ": "NDQ",
            "NAS": "NDQ",
            "NMS": "NDQ",
            "NCM": "NDQ",
            "NGM": "NDQ",
            "NSDQ": "NDQ",
            "TSX": "TSE",
        }

        # Pattern 1: TICKER (EXCHANGE) e.g. "MSFT (NDQ)"
        pattern1 = re.compile(rf'\b({ticker_pattern})\s*\(\s*{exchange_tokens}\s*\)', re.IGNORECASE)

        # Pattern 2: EXCHANGE-TICKER or EXCHANGE:TICKER e.g. "NYSE-ADM" / "NYSE: ADM"
        pattern2 = re.compile(rf'\b{exchange_tokens}\s*[-:]\s*({ticker_pattern})(?=\s|$)', re.IGNORECASE)

        # Pattern 3: EXCHANGE TICKER e.g. "NASDAQ AAPL"
        pattern3 = re.compile(rf'\b{exchange_tokens}\s+({ticker_pattern})(?=\s|$)', re.IGNORECASE)
        pattern4 = re.compile(r'\b([A-Z]{1,5}\.[A-Z]{1,4})(?=\s|$)', re.IGNORECASE)

        def set_company_name(line: str, match_start: int, line_idx: int) -> None:
            pre_match = line[:match_start].strip()
            clean_pre = pre_match.rstrip(":-").strip()
            if len(clean_pre) > 3 and clean_pre.upper() not in exchange_code_set:
                info.company_name = clean_pre
                return
            for prev_line in reversed(search_lines[:line_idx]):
                clean_prev = prev_line.strip()
                if not clean_prev:
                    continue
                upper_prev = clean_prev.upper()
                if "VALUE LINE" in upper_prev or "PAGE" in upper_prev:
                    continue
                if "RECENT" in upper_prev:
                    info.company_name = clean_prev.split("RECENT")[0].strip()
                else:
                    info.company_name = clean_prev
                break

        for idx, line in enumerate(search_lines):
            match1 = pattern1.search(line)
            if match1:
                info.ticker = match1.group(1).upper()
                exchange = match1.group(2).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                set_company_name(line, match1.start(), idx)
                break

            match2 = pattern2.search(line)
            if match2:
                exchange = match2.group(1).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                info.ticker = match2.group(2).upper()
                set_company_name(line, match2.start(), idx)
                break

            match3 = pattern3.search(line)
            if match3:
                exchange = match3.group(1).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                info.ticker = match3.group(2).upper()
                set_company_name(line, match3.start(), idx)
                break

            match4 = pattern4.search(line)
            if match4:
                info.ticker = match4.group(1).upper()
                if info.ticker.endswith(".TO"):
                    info.exchange = "TSE"
                set_company_name(line, match4.start(), idx)
                break
        
        return info

    def parse(self) -> list[ExtractionResult]:
        results = []
        
        # Helper to add result
        def add_res(key, match, group_idx=1, snippet_group=0, raw_override: Optional[str] = None, parsed_json: Optional[Dict[str, Any]] = None):
            if match:
                results.append(ExtractionResult(
                    field_key=key,
                    raw_value_text=raw_override if raw_override is not None else match.group(group_idx),
                    original_text_snippet=match.group(snippet_group),
                    parsed_value_json=parsed_json,
                    confidence_score=0.9,
                ))

        # --- 1. Header Metrics (Expanded) ---
        
        # Recent Price (text layer or word-merged tokens like "RECENT109.10")
        recent_match = re.search(r'\bRECENT\s*(?:PRICE\s*)?(\d+\.?\d*)', self.text, re.IGNORECASE)
        if recent_match:
            add_res("recent_price", recent_match)
        elif 1 in self.page_words:
            recent_from_words = self._recent_price_from_words(self.page_words[1])
            if recent_from_words:
                results.append(ExtractionResult(
                    field_key="recent_price",
                    raw_value_text=recent_from_words,
                    original_text_snippet="RECENT (word layout)",
                    confidence_score=0.7,
                ))

        # P/E Ratio (Current)
        add_res("pe_ratio", re.search(r'P/E\s+(?:RATIO\s+)?(\d+\.?\d*)', self.text, re.IGNORECASE))

        # P/E Ratio (Trailing) - "Trailing:17.9"
        add_res("pe_ratio_trailing", re.search(r'Trailing\s*:\s*(\d+\.?\d*)', self.text, re.IGNORECASE))

        # P/E Ratio (Median) - "Median:22.0"
        add_res("pe_ratio_median", re.search(r'Median\s*:\s*(\d+\.?\d*)', self.text, re.IGNORECASE))

        # Relative P/E - "RELATIVE 0.93"
        add_res("relative_pe_ratio", re.search(r'RELATIVE\s+(\d+\.?\d*)', self.text, re.IGNORECASE))

        # Dividend Yield
        yield_match = re.search(r'DIV(?:’|\'|I?DEND)\s*D?\s*(?:YLD|YIELD)?\s+(\d+\.?\d*)%', self.text, re.IGNORECASE)
        if yield_match:
            results.append(ExtractionResult(
                field_key="dividend_yield",
                raw_value_text=yield_match.group(1) + "%",
                original_text_snippet=yield_match.group(0),
                confidence_score=0.9
            ))

        # Beta - "BETA 1.00"
        add_res("beta", re.search(r'BETA\s+(\d+\.?\d*)', self.text, re.IGNORECASE))

        # Ratings (Timeliness / Technical) - tolerate "Lowered1/2/26" without spaces
        for key in ("timeliness", "technical", "safety"):
            m = re.search(rf'\b{key.upper()}\s+(\d+)(?:\s+([A-Za-z]+)\s*(\d{{1,2}}/\d{{1,2}}/\d{{2}}))?', self.text, re.IGNORECASE)
            if m:
                notes = None
                if m.group(2) and m.group(3):
                    notes = f"{m.group(2).title()} {m.group(3)}"
                results.append(ExtractionResult(
                    field_key=key,
                    raw_value_text=m.group(1),
                    original_text_snippet=m.group(0),
                    parsed_value_json={"value": int(m.group(1)), "notes": notes} if notes else {"value": int(m.group(1))},
                    confidence_score=0.8,
                ))

        if not any(r.field_key == "safety" for r in results) and 1 in self.page_words:
            safety_value = self._rating_from_words("SAFETY", self.page_words[1])
            if safety_value is not None:
                results.append(ExtractionResult(
                    field_key="safety",
                    raw_value_text=str(safety_value),
                    original_text_snippet="SAFETY (word layout)",
                    parsed_value_json={"value": safety_value},
                    confidence_score=0.6,
                ))

        strength_match = re.search(r'FinancialStrength\s+([A-Z][A-Z+\-]{0,3})', self.text, re.IGNORECASE)
        if strength_match:
            results.append(ExtractionResult(
                field_key="company_financial_strength",
                raw_value_text=strength_match.group(1),
                original_text_snippet=strength_match.group(0),
                confidence_score=0.8,
            ))

        stability_match = re.search(r"Stock[’']?s?PriceStability\s+(\d{1,3})", self.text, re.IGNORECASE)
        if stability_match:
            results.append(ExtractionResult(
                field_key="stock_price_stability",
                raw_value_text=stability_match.group(1),
                original_text_snippet=stability_match.group(0),
                confidence_score=0.8,
            ))

        growth_match = re.search(r'PriceGrowthPersistence\s+(\d{1,3})', self.text, re.IGNORECASE)
        if growth_match:
            results.append(ExtractionResult(
                field_key="price_growth_persistence",
                raw_value_text=growth_match.group(1),
                original_text_snippet=growth_match.group(0),
                confidence_score=0.8,
            ))

        predict_match = re.search(r'EarningsPredictability\s+(\d{1,3})', self.text, re.IGNORECASE)
        if predict_match:
            results.append(ExtractionResult(
                field_key="earnings_predictability",
                raw_value_text=predict_match.group(1),
                original_text_snippet=predict_match.group(0),
                confidence_score=0.8,
            ))

        # Analyst name + report date near the bottom: "NilsC.VanLiew January2,2026"
        m = re.search(
            r'\b([A-Z][A-Za-z.]{2,40})\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{1,2})\s*,\s*(\d{4})',
            self.text,
        )
        if m:
            analyst_raw = m.group(1)
            analyst_norm = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', analyst_raw)
            analyst_norm = re.sub(r'\.(?=[A-Za-z])', '. ', analyst_norm)
            analyst_norm = re.sub(r'\s+', ' ', analyst_norm).strip()

            month_map = {
                "january": "01",
                "february": "02",
                "march": "03",
                "april": "04",
                "may": "05",
                "june": "06",
                "july": "07",
                "august": "08",
                "september": "09",
                "october": "10",
                "november": "11",
                "december": "12",
            }
            iso_date = f"{m.group(4)}-{month_map[m.group(2).lower()]}-{int(m.group(3)):02d}"

            results.append(ExtractionResult(
                field_key="analyst_name",
                raw_value_text=analyst_norm,
                original_text_snippet=m.group(0),
                parsed_value_json={"value": analyst_norm},
                confidence_score=0.8,
            ))
            results.append(ExtractionResult(
                field_key="report_date",
                raw_value_text=iso_date,
                original_text_snippet=m.group(0),
                parsed_value_json={"iso_date": iso_date, "display": f"{m.group(2)}{m.group(3)},{m.group(4)}"},
                confidence_score=0.8,
            ))

        # --- 2. Target Price Ranges ---
        
        # 18-Month Range: "$55-$97 $76(10%)"
        # Regex: \$(\d+)-\$(\d+)\s+\$(\d+)\((\d+%)\)
        target_18m_match = re.search(r'\$(\d+)-\$(\d+)\s+\$(\d+)\((\d+%)\)', self.text)
        if target_18m_match:
            results.append(ExtractionResult(field_key="target_18m_low", raw_value_text=target_18m_match.group(1), original_text_snippet=target_18m_match.group(0)))
            results.append(ExtractionResult(field_key="target_18m_high", raw_value_text=target_18m_match.group(2), original_text_snippet=target_18m_match.group(0)))
            results.append(ExtractionResult(field_key="target_18m_mid", raw_value_text=target_18m_match.group(3), original_text_snippet=target_18m_match.group(0)))
            results.append(ExtractionResult(field_key="target_18m_upside_pct", raw_value_text=target_18m_match.group(4), original_text_snippet=target_18m_match.group(0)))

        # Long Term Projections (year range + high/low)
        yr = re.search(r'\b(20\d{2})-(\d{2})\s*PROJECTIONS\b', self.text, re.IGNORECASE)
        if yr:
            start_year = int(yr.group(1))
            end_suffix = int(yr.group(2))
            end_year = (start_year // 100) * 100 + end_suffix
            results.append(ExtractionResult(
                field_key="long_term_projection_year_range",
                raw_value_text=f"{start_year}-{end_year}",
                original_text_snippet=yr.group(0),
                confidence_score=0.9,
            ))

        high_match = re.search(r'High\s+(\d+)\s*\(\+?(\d+)%\)\s+(\d+)%', self.text, re.IGNORECASE)
        if high_match:
            results.append(ExtractionResult(field_key="long_term_projection_high_price", raw_value_text=high_match.group(1), original_text_snippet=high_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_high_price_gain_pct", raw_value_text=f"{high_match.group(2)}%", original_text_snippet=high_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_high_total_return_pct", raw_value_text=f"{high_match.group(3)}%", original_text_snippet=high_match.group(0), confidence_score=0.9))

        low_match = re.search(r'Low\s+(\d+)\s*\(\+?(\d+)%\)\s+(\d+)%', self.text, re.IGNORECASE)
        if low_match:
            results.append(ExtractionResult(field_key="long_term_projection_low_price", raw_value_text=low_match.group(1), original_text_snippet=low_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_low_price_gain_pct", raw_value_text=f"{low_match.group(2)}%", original_text_snippet=low_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_low_total_return_pct", raw_value_text=f"{low_match.group(3)}%", original_text_snippet=low_match.group(0), confidence_score=0.9))

        # --- 3. Financial Snapshot ---
        
        def _money_from_match(match: re.Match, num_group: int = 1, scale_group: int = 2) -> str:
            num = match.group(num_group)
            token = match.group(scale_group).lower()
            if token in {"mil", "mill", "million"}:
                token = "mill"
            elif token in {"bil", "billion"}:
                token = "billion"
            return f"${num} {token}"

        cap_as_of = re.search(
            r'CAPITAL\s*STRUCTURE\s*as\s*of\s*(\d{1,2}/\d{1,2}/\d{2})',
            self.text,
            re.IGNORECASE,
        )
        if cap_as_of:
            iso = self._iso_from_mdy(cap_as_of.group(1))
            results.append(ExtractionResult(
                field_key="capital_structure_as_of",
                raw_value_text=iso or cap_as_of.group(1),
                original_text_snippet=cap_as_of.group(0),
                parsed_value_json={"iso_date": iso} if iso else None,
                confidence_score=0.7,
            ))

        total_debt = re.search(r'Total\s*Debt\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if total_debt:
            results.append(ExtractionResult(field_key="total_debt", raw_value_text=_money_from_match(total_debt), original_text_snippet=total_debt.group(0), confidence_score=0.9))

        due_5y = re.search(r'Due\s*in\s*5\s*Yrs\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if due_5y:
            results.append(ExtractionResult(field_key="debt_due_in_5_years", raw_value_text=_money_from_match(due_5y), original_text_snippet=due_5y.group(0), confidence_score=0.9))
        
        lt_debt = re.search(r'LT\s*Debt\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if lt_debt:
            results.append(ExtractionResult(field_key="lt_debt", raw_value_text=_money_from_match(lt_debt), original_text_snippet=lt_debt.group(0), confidence_score=0.9))

        lt_interest = re.search(r'LT\s*Interest\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if lt_interest:
            results.append(ExtractionResult(field_key="lt_interest", raw_value_text=_money_from_match(lt_interest), original_text_snippet=lt_interest.group(0), confidence_score=0.9))

        cap_pct = re.search(r'\((\d+\.?\d*)%\s*of\s*Cap', self.text, re.IGNORECASE)
        if cap_pct:
            results.append(ExtractionResult(field_key="debt_percent_of_capital", raw_value_text=f"{cap_pct.group(1)}%", original_text_snippet=cap_pct.group(0), confidence_score=0.8))

        leases = re.search(r'Leases,UncapitalizedAnnualrentals\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if leases:
            results.append(ExtractionResult(field_key="leases_uncapitalized_annual_rentals", raw_value_text=_money_from_match(leases), original_text_snippet=leases.group(0), confidence_score=0.8))

        pension_assets = re.search(r'Pension\s*Assets-?\s*\d{1,2}/\d{2}\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if pension_assets:
            results.append(ExtractionResult(field_key="pension_assets", raw_value_text=_money_from_match(pension_assets), original_text_snippet=pension_assets.group(0), confidence_score=0.8))

        oblig = re.search(r'Oblig\.\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if oblig:
            results.append(ExtractionResult(field_key="pension_obligations", raw_value_text=_money_from_match(oblig), original_text_snippet=oblig.group(0), confidence_score=0.8))

        pfd_stock = re.search(r'Pfd\s*Stock\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if pfd_stock:
            results.append(ExtractionResult(
                field_key="preferred_stock",
                raw_value_text=_money_from_match(pfd_stock),
                original_text_snippet=pfd_stock.group(0),
                confidence_score=0.8,
            ))

        pfd_div = re.search(r'Pfd\s*Div[^\d$]*\s*\$([\d\.]+)\s*(mil|mill|million|bil|billion)\.?\b', self.text, re.IGNORECASE)
        if pfd_div:
            results.append(ExtractionResult(
                field_key="preferred_dividend",
                raw_value_text=_money_from_match(pfd_div),
                original_text_snippet=pfd_div.group(0),
                confidence_score=0.8,
            ))
        
        shares_match = re.search(r'Common\s*Stock\s*([\d,]+)\s*shares', self.text, re.IGNORECASE)
        if shares_match:
            results.append(ExtractionResult(field_key="shares_outstanding", raw_value_text=shares_match.group(1).replace(',', ''), original_text_snippet=shares_match.group(0)))

        shares_match2 = re.search(r'CommonStock\s*([\d,]+)\s*(?:shares|shs)\.?', self.text, re.IGNORECASE)
        if shares_match2:
            as_of = None
            tail = self.text[shares_match2.end(): shares_match2.end() + 200]
            as_of_match = re.search(r'asof\s*(\d{1,2}/\d{1,2}/\d{2})', tail, re.IGNORECASE)
            if as_of_match:
                as_of = self._iso_from_mdy(as_of_match.group(1)) or as_of_match.group(1)
            results.append(ExtractionResult(
                field_key="common_stock_shares_outstanding",
                raw_value_text=shares_match2.group(1).replace(',', ''),
                original_text_snippet=shares_match2.group(0),
                parsed_value_json={"as_of": as_of} if as_of else None,
                confidence_score=0.9,
            ))

        mkt_match = re.search(r'MARKET\s*CAP\s*:?\s*\$([\d\.]+)\s*(billion|mil|mill|million)\b', self.text, re.IGNORECASE)
        if mkt_match:
            val = mkt_match.group(1)
            token = mkt_match.group(2).lower()
            if token in {"mil", "mill", "million"}:
                token = "mill"
            elif token in {"billion"}:
                token = "billion"
            results.append(ExtractionResult(field_key="market_cap", raw_value_text=f"${val} {token}", original_text_snippet=mkt_match.group(0), confidence_score=0.9))

        # --- 4. Narrative ---
        # "BUSINESS:A.O.SmithCorp...."
        biz_match = re.search(r'BUSINESS:(.*?)(?:Telephone:.*?Internet:.*?\.)', self.text, re.IGNORECASE | re.DOTALL)
        if biz_match:
            desc = biz_match.group(1)
            # Remove common current-position table row bleed-through that often interleaves with BUSINESS text.
            desc = re.sub(
                r'\b(?:Cash\s*Assets|Receivables|Inventory\s*\(LIFO\)|Accts\s*Payable|Debt\s*Due|Current\s*Assets|Current\s*Liab\.?|Other)\b\s+[0-9.]+\s+[0-9.]+\s+[0-9.]+',
                ' ',
                desc,
                flags=re.IGNORECASE,
            )
            desc = re.sub(r'\(\$MILL\.\)', ' ', desc, flags=re.IGNORECASE)
            desc = re.sub(r'\s+', ' ', desc).strip()
            results.append(ExtractionResult(field_key="business_description", raw_value_text=desc, original_text_snippet=biz_match.group(0), confidence_score=0.7))

        # --- 5. Structured blocks / tables (JSON outputs) ---
        def _slice_between(start_pat: str, end_pat: str) -> Optional[str]:
            start = re.search(start_pat, self.text, re.IGNORECASE)
            if not start:
                return None
            end = re.search(end_pat, self.text[start.end():], re.IGNORECASE)
            if not end:
                return self.text[start.end():]
            return self.text[start.end(): start.end() + end.start()]

        # Current Position table ($mill.) -> structured JSON
        cp_block = _slice_between(r'\bCURRENTPOSITION\b', r'\bANNUALRATES\b')
        if cp_block:
            header = re.search(r'(\d{4})\s+(\d{4})\s+(\d{1,2}/\d{1,2}/\d{2})', cp_block)
            if header:
                years = [header.group(1), header.group(2), self._iso_from_mdy(header.group(3)) or header.group(3)]
                def row3(label_pat: str) -> Optional[list[float]]:
                    m = re.search(rf'{label_pat}\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', cp_block, re.IGNORECASE)
                    if not m:
                        return None
                    return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
                parsed = {
                    "years": years,
                    "cash_assets": row3(r'Cash\s*Assets'),
                    "receivables": row3(r'Receivables'),
                    "inventory_lifo": row3(r'Inventory\s*\(LIFO\)'),
                    "other_current_assets": row3(r'Other'),
                    "current_assets_total": row3(r'Current\s*Assets'),
                    "accounts_payable": row3(r'Accts\s*Payable'),
                    "debt_due": row3(r'Debt\s*Due'),
                    "other_current_liabilities": None,
                    "current_liabilities_total": row3(r'Current\s*Liab\.'),
                }
                other_matches = re.findall(r'\bOther\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', cp_block, re.IGNORECASE)
                if len(other_matches) >= 2:
                    parsed["other_current_assets"] = [float(x) for x in other_matches[0]]
                    parsed["other_current_liabilities"] = [float(x) for x in other_matches[1]]

                if parsed["cash_assets"] and parsed["current_assets_total"]:
                    results.append(ExtractionResult(
                        field_key="current_position_usd_millions",
                        raw_value_text=None,
                        original_text_snippet="CURRENTPOSITION ...",
                        parsed_value_json=parsed,
                        confidence_score=0.7,
                    ))

        # Financial Position table ($mill.) -> structured JSON
        fp_match = re.search(r'\bFINANCIALPOSITION\b', self.text, re.IGNORECASE)
        fp_block = None
        if fp_match:
            fp_block = self.text[fp_match.end(): fp_match.end() + 1500]
        if fp_block:
            header = re.search(r'(\d{4})\s+(\d{4})\s+(\d{1,2}/\d{1,2}/\d{2})', fp_block)
            if header:
                years = [header.group(1), header.group(2), self._iso_from_mdy(header.group(3)) or header.group(3)]

                def row3(label_pat: str) -> Optional[list[float]]:
                    m = re.search(rf'{label_pat}\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', fp_block, re.IGNORECASE)
                    if not m:
                        return None
                    return [float(m.group(1)), float(m.group(2)), float(m.group(3))]

                other_matches = re.findall(r'\bOther\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', fp_block, re.IGNORECASE)
                assets_other = [float(x) for x in other_matches[0]] if len(other_matches) >= 1 else None
                liabilities_other = [float(x) for x in other_matches[1]] if len(other_matches) >= 2 else None

                parsed = {
                    "years": years,
                    "assets": {
                        "bonds": row3(r'Bonds'),
                        "stocks": row3(r'Stocks'),
                        "other": assets_other,
                        "total_assets": row3(r'Total\s*Assets'),
                    },
                    "liabilities": {
                        "unearned_premiums": row3(r'Unearned\s*Prems'),
                        "reserves": row3(r'Reserves'),
                        "other": liabilities_other,
                        "total_liabilities": row3(r'Total\s*Liab[^\s]*'),
                    },
                }

                if parsed["assets"]["bonds"] and parsed["liabilities"]["unearned_premiums"]:
                    results.append(ExtractionResult(
                        field_key="financial_position_usd_millions",
                        raw_value_text=None,
                        original_text_snippet="FINANCIALPOSITION ...",
                        parsed_value_json=parsed,
                        confidence_score=0.7,
                    ))

        # Annual Rates of Change -> structured JSON (ratios)
        ar_block = _slice_between(r'\bANNUALRATES\b', r'\bQUARTERLYSALES\b')
        if ar_block:
            def growth_row(label_pat: str) -> Optional[dict[str, float]]:
                m = re.search(
                    rf'{label_pat}[^\d%]{{0,20}}([0-9.]+)%\s+([0-9.]+)%\s+([0-9.]+)%',
                    ar_block,
                    re.IGNORECASE,
                )
                if not m:
                    return None
                return {
                    "past_10y": float(m.group(1)) / 100.0,
                    "past_5y": float(m.group(2)) / 100.0,
                    "est_to_2028_2030": float(m.group(3)) / 100.0,
                }
            parsed = {
                "sales": growth_row(r'\bSales\b'),
                "cash_flow_per_share": growth_row(r'Cash\s*Flow'),
                "earnings": growth_row(r'\bEarnings\b'),
                "dividends": growth_row(r'\bDividends\b'),
                "book_value": growth_row(r'\bBook\s*Value\b'),
            }
            if parsed["sales"]:
                results.append(ExtractionResult(
                    field_key="annual_rates_of_change",
                    raw_value_text=None,
                    original_text_snippet="ANNUALRATES ...",
                    parsed_value_json=parsed,
                    confidence_score=0.7,
                ))

        def _parse_quarterly_rows(block: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            for m in re.finditer(
                r'^\s*(\d{4})\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)(?:\s+([0-9.]+))?(?:\s+.*)?$',
                block,
                re.MULTILINE,
            ):
                def _f(s: str) -> float:
                    if s.startswith('.'):
                        s = '0' + s
                    return float(s)
                rows.append({
                    "calendar_year": int(m.group(1)),
                    "mar_31": _f(m.group(2)),
                    "jun_30": _f(m.group(3)),
                    "sep_30": _f(m.group(4)),
                    "dec_31": _f(m.group(5)),
                    "full_year": _f(m.group(6)) if m.group(6) else None,
                })
            return rows

        eps_start_pat = r'\bEARNINGSPERSHARE\b|\bEARNINGSPERSHAREA\b'
        qs_block = _slice_between(r'\bQUARTERLYSALES\b', eps_start_pat)
        if qs_block:
            parsed = _parse_quarterly_rows(qs_block)
            if parsed:
                results.append(ExtractionResult(
                    field_key="quarterly_sales_usd_millions",
                    raw_value_text=None,
                    original_text_snippet="QUARTERLYSALES ...",
                    parsed_value_json=parsed,
                    confidence_score=0.8,
                ))

        div_start_pat = r'\bQUARTERLYDIVIDENDS\b|\bQUARTERLYDIVIDENDSPAID\b|\bQUARTERLYDIVIDENDSPAIDB\b'
        eps_block = _slice_between(eps_start_pat, div_start_pat)
        if eps_block:
            parsed = _parse_quarterly_rows(eps_block)
            if parsed:
                results.append(ExtractionResult(
                    field_key="earnings_per_share",
                    raw_value_text=None,
                    original_text_snippet="EARNINGSPERSHARE ...",
                    parsed_value_json=parsed,
                    confidence_score=0.8,
                ))

        div_block = _slice_between(div_start_pat, r'\bBUSINESS\b')
        if div_block:
            parsed = _parse_quarterly_rows(div_block)
            if parsed:
                results.append(ExtractionResult(
                    field_key="quarterly_dividends_paid_per_share",
                    raw_value_text=None,
                    original_text_snippet="QUARTERLYDIVIDENDS ...",
                    parsed_value_json=parsed,
                    confidence_score=0.8,
                ))

        results.extend(self._parse_annual_table_metrics())

        tables_time_series = self._parse_time_series_tables()
        if tables_time_series:
            results.append(ExtractionResult(
                field_key="tables_time_series",
                raw_value_text=None,
                original_text_snippet="TABLES_TIME_SERIES ...",
                parsed_value_json=tables_time_series,
                confidence_score=0.6,
            ))

        if 1 in self.page_words:
            total_return = self._parse_total_return_from_words(self.page_words[1])
            if total_return:
                results.append(total_return)

        # Institutional Decisions (word-layout assisted)
        if 1 in self.page_words:
            inst = self._parse_institutional_decisions_from_words(self.page_words[1])
            if inst:
                results.append(inst)

        return results

    def _parse_annual_table_metrics(self) -> list[ExtractionResult]:
        flat_text = re.sub(r'\s+', ' ', self.text)
        years = self._find_year_sequence(flat_text)
        if not years:
            return []

        value_pat = r'[-+]?\d*\.?\d+%?'
        value_re = re.compile(rf'^{value_pat}$')
        tokens = flat_text.split()
        results: list[ExtractionResult] = []

        def parse_row(label_pat: str, field_key: str, *, scale_token: Optional[str] = None, percent: bool = False):
            label_idx = next(
                (idx for idx, token in enumerate(tokens) if re.search(label_pat, token, re.IGNORECASE)),
                None,
            )
            if label_idx is None:
                return
            values_raw: list[str] = []
            for j in range(label_idx - 1, -1, -1):
                if value_re.match(tokens[j]):
                    values_raw.append(tokens[j])
                else:
                    if values_raw:
                        break
            values_raw = list(reversed(values_raw))
            if not values_raw:
                return
            if percent:
                values_raw = [token for token in values_raw if "%" in token]
                if not values_raw:
                    return
            if len(values_raw) > len(years):
                values_raw = values_raw[-len(years):]
            aligned_years = self._align_years(years, values_raw)
            token_by_year = {year: token for year, token in zip(aligned_years, values_raw)}
            value_by_year = {year: self._coerce_value(token) for year, token in token_by_year.items()}

            estimate_year = years[-1]
            estimate_value = value_by_year.get(estimate_year)
            if estimate_value is not None and len(years) > 1:
                actual_year = years[-2]
            else:
                actual_year = aligned_years[-1] if aligned_years else None

            snippet = " ".join(tokens[max(0, label_idx - 20): label_idx + 5])

            if actual_year is not None:
                actual_token = token_by_year.get(actual_year)
                if actual_token is not None and value_by_year.get(actual_year) is not None:
                    results.append(
                        self._annual_metric_result(
                            field_key=field_key,
                            raw_token=actual_token,
                            year=actual_year,
                            is_estimate=False,
                            snippet=snippet,
                            scale_token=scale_token,
                            percent=percent,
                        )
                    )

            if estimate_value is not None:
                estimate_token = token_by_year.get(estimate_year)
                if estimate_token is not None:
                    results.append(
                        self._annual_metric_result(
                            field_key=field_key,
                            raw_token=estimate_token,
                            year=estimate_year,
                            is_estimate=True,
                            snippet=snippet,
                            scale_token=scale_token,
                            percent=percent,
                        )
                    )

        parse_row(r"Cap[’']?lSpendingpersh", "capital_spending_per_share_usd")
        parse_row(r"AvgAnn[’']?lDiv[’']?dYield", "avg_annual_dividend_yield_pct", percent=True)
        parse_row(r"Depreciation\(\$?mill\)", "depreciation_usd_millions", scale_token="mill")
        parse_row(r"NetProfit\(\$?mill\)", "net_profit_usd_millions", scale_token="mill")

        return results

    @staticmethod
    def _annual_metric_result(
        *,
        field_key: str,
        raw_token: str,
        year: int,
        is_estimate: bool,
        snippet: str,
        scale_token: Optional[str],
        percent: bool,
    ) -> ExtractionResult:
        raw_value_text = raw_token.strip()
        if percent and not raw_value_text.endswith("%"):
            raw_value_text = f"{raw_value_text}%"
        if scale_token:
            raw_value_text = f"{raw_value_text} {scale_token}"

        parsed_value_json = {
            "year": year,
            "period_type": "FY",
            "period_end_date": f"{year}-12-31",
            "is_estimate": is_estimate,
        }

        return ExtractionResult(
            field_key=field_key,
            raw_value_text=raw_value_text,
            original_text_snippet=snippet,
            parsed_value_json=parsed_value_json,
            confidence_score=0.7,
        )

    @staticmethod
    def _find_year_sequence(text: str) -> list[int]:
        candidates: list[list[int]] = []
        for match in re.finditer(r'(?:20\d{2}\s+){6,}20\d{2}', text):
            years = [int(y) for y in re.findall(r'20\d{2}', match.group(0))]
            if years:
                candidates.append(years)
        if not candidates:
            return []
        return max(candidates, key=len)

    @staticmethod
    def _align_years(years: list[int], values: list[str]) -> list[int]:
        if not values:
            return []
        if len(values) == len(years):
            return years
        if len(values) == len(years) - 1:
            return years[:-1]
        if len(values) < len(years):
            return years[-len(values):]
        return years

    @staticmethod
    def _coerce_value(token: str) -> Optional[float]:
        if token is None:
            return None
        raw = token.strip()
        upper = raw.upper()
        if upper in {"--", "NMF", "NIL"}:
            return None
        neg = False
        if raw and raw[0] in {"d", "D"}:
            neg = True
            raw = raw[1:]
        cleaned = raw.replace("%", "")
        if cleaned.startswith("."):
            cleaned = f"0{cleaned}"
        try:
            value = float(cleaned)
        except ValueError:
            return None
        return -value if neg else value

    @staticmethod
    def _iso_from_mdy(value: str) -> Optional[str]:
        match = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2})', value)
        if not match:
            return None
        year = 2000 + int(match.group(3))
        return f"{year:04d}-{int(match.group(1)):02d}-{int(match.group(2)):02d}"

    @staticmethod
    def _recent_price_from_words(words: list[dict[str, Any]]) -> Optional[str]:
        for w in words:
            text = str(w.get("text", ""))
            match = re.search(r'RECENT\s*(\d+\.?\d*)', text, re.IGNORECASE)
            if match:
                return match.group(1)
        for w in words:
            if str(w.get("text", "")).upper() != "RECENT":
                continue
            base_top = float(w.get("top", 0.0))
            base_x = float(w.get("x0", 0.0))
            line_words = [
                x for x in words
                if abs(float(x.get("top", 0.0)) - base_top) < 1.0
                and float(x.get("x0", 0.0)) > base_x
            ]
            line_words = sorted(line_words, key=lambda x: float(x.get("x0", 0.0)))
            for candidate in line_words:
                token = str(candidate.get("text", ""))
                if re.fullmatch(r'\d+\.?\d*', token):
                    return token
        return None

    def _parse_total_return_from_words(self, words: list[dict[str, Any]]) -> Optional[ExtractionResult]:
        label_word = next(
            (w for w in words if "TOT.RETURN" in str(w.get("text", "")).upper()),
            None,
        )
        if not label_word:
            return None

        label_text = str(label_word.get("text", ""))
        date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2})', label_text)
        as_of = self._iso_from_mdy(date_match.group(1)) if date_match else None

        lines: dict[float, list[dict[str, Any]]] = {}
        for w in words:
            top = round(float(w.get("top", 0.0)), 1)
            lines.setdefault(top, []).append(w)

        def line_text(line_words: list[dict[str, Any]]) -> str:
            ordered = sorted(line_words, key=lambda x: float(x.get("x0", 0.0)))
            parts: list[str] = []
            prev_x1 = None
            for w in ordered:
                text = str(w.get("text", ""))
                x0 = float(w.get("x0", 0.0))
                if prev_x1 is not None and x0 - prev_x1 > 2.0:
                    parts.append(" ")
                parts.append(text)
                prev_x1 = float(w.get("x1", 0.0))
            return "".join(parts)

        def parse_line(tag: str) -> Optional[tuple[float, float]]:
            pattern = rf'\b{tag}\.?\s+([0-9.]+)\s+([0-9.]+)'
            for line_words in lines.values():
                text = line_text(line_words)
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return float(match.group(1)), float(match.group(2))
            return None

        returns = {
            "1y": parse_line("1yr"),
            "3y": parse_line("3yr"),
            "5y": parse_line("5yr"),
        }
        if not any(returns.values()):
            return None

        def ratio(value: Optional[float]) -> Optional[float]:
            if value is None:
                return None
            return value / 100.0

        total_return = {
            "stock": {
                "1y": ratio(returns["1y"][0]) if returns["1y"] else None,
                "3y": ratio(returns["3y"][0]) if returns["3y"] else None,
                "5y": ratio(returns["5y"][0]) if returns["5y"] else None,
            },
            "index": {
                "1y": ratio(returns["1y"][1]) if returns["1y"] else None,
                "3y": ratio(returns["3y"][1]) if returns["3y"] else None,
                "5y": ratio(returns["5y"][1]) if returns["5y"] else None,
            },
        }

        parsed = {
            "value_line_total_return_as_of": as_of,
            "total_return": total_return,
        }

        return ExtractionResult(
            field_key="price_semantics_and_returns",
            raw_value_text=None,
            original_text_snippet=label_text,
            parsed_value_json=parsed,
            confidence_score=0.7,
        )

    def _parse_time_series_tables(self) -> Optional[dict[str, Any]]:
        flat_text = re.sub(r'\s+', ' ', self.text)
        years = self._find_year_sequence(flat_text)
        if not years:
            return None

        tokens = flat_text.split()

        def is_value_token(token: str) -> bool:
            upper = token.upper()
            if upper in {"--", "NMF", "NIL"}:
                return True
            return re.fullmatch(r'[dD]?\d*\.?\d+%?', token) is not None

        def coerce(token: str, percent_ratio: bool) -> Optional[float]:
            value = self._coerce_value(token)
            if value is None:
                return None
            if percent_ratio:
                if token.endswith("%") or abs(value) > 1:
                    return value / 100.0
            return value

        def parse_series(label_pat: str, *, percent_ratio: bool) -> tuple[list[Optional[float]], Optional[float]]:
            label_idx = next(
                (idx for idx, token in enumerate(tokens) if re.search(label_pat, token, re.IGNORECASE)),
                None,
            )
            if label_idx is None:
                return [None for _ in years], None

            values_raw: list[str] = []
            for j in range(label_idx - 1, -1, -1):
                if is_value_token(tokens[j]):
                    values_raw.append(tokens[j])
                else:
                    if values_raw:
                        break
            values_raw = list(reversed(values_raw))
            if len(values_raw) > len(years):
                values_raw = values_raw[-len(years):]

            aligned_years = self._align_years(years, values_raw)
            values = [coerce(token, percent_ratio) for token in values_raw]
            series = [None for _ in years]
            for year, value in zip(aligned_years, values):
                series[years.index(year)] = value

            projection = None
            for k in range(label_idx + 1, len(tokens)):
                if is_value_token(tokens[k]):
                    projection = coerce(tokens[k], percent_ratio)
                    break

            return series, projection

        def parse_price_series(label: str) -> list[Optional[float]]:
            match = re.search(rf'{label}:\s*([0-9.\s]+)', self.text, re.IGNORECASE)
            if not match:
                return [None for _ in range(12)]
            segment = match.group(1)
            for stop in ("TargetPriceRange", "Low:", "High:"):
                if stop in segment:
                    segment = segment.split(stop)[0]
            values = [float(v) for v in re.findall(r'\d+\.?\d*', segment)]
            if len(values) < 12:
                return values + [None for _ in range(12 - len(values))]
            return values[:12]

        proj_range = None
        proj_match = re.search(r'(20\d{2})\s*-\s*(\d{2})', flat_text)
        if proj_match:
            start_year = int(proj_match.group(1))
            end_year = (start_year // 100) * 100 + int(proj_match.group(2))
            proj_range = f"{start_year}-{end_year}"

        per_share = {}
        projection = {}

        series, proj = parse_series(r'P/CPremEarnedpersh', percent_ratio=False)
        per_share["pc_prem_earned_per_share_usd"] = series
        if proj is not None:
            projection["pc_prem_earned_per_share_usd"] = proj

        series, proj = parse_series(r'InvestmentIncpersh', percent_ratio=False)
        per_share["investment_income_per_share_usd"] = series
        if proj is not None:
            projection["investment_income_per_share_usd"] = proj

        series, proj = parse_series(r'UnderwritingIncpersh', percent_ratio=False)
        per_share["underwriting_income_per_share_usd"] = series
        if proj is not None:
            projection["underwriting_income_per_share_usd"] = proj

        series, proj = parse_series(r'Earningspersh', percent_ratio=False)
        per_share["earnings_per_share_usd"] = series
        if proj is not None:
            projection["earnings_per_share_usd"] = proj

        series, proj = parse_series(r'Div.?dsDecl.?dpersh', percent_ratio=False)
        per_share["dividends_declared_per_share_usd"] = series
        if proj is not None:
            projection["dividends_declared_per_share_usd"] = proj

        series, proj = parse_series(r'BookValuepersh', percent_ratio=False)
        per_share["book_value_per_share_usd"] = series
        if proj is not None:
            projection["book_value_per_share_usd"] = proj

        series, proj = parse_series(r'CommonShsOutst', percent_ratio=False)
        per_share["common_shares_outstanding_millions"] = series
        if proj is not None:
            projection["common_shares_outstanding_millions"] = proj

        valuation = {}
        series, _ = parse_series(r'PricetoBookValue', percent_ratio=True)
        valuation["price_to_book_value_pct"] = series

        series, proj = parse_series(r'AvgAnn.?lP/ERatio', percent_ratio=False)
        valuation["avg_annual_pe_ratio"] = series
        if proj is not None:
            projection["avg_annual_pe_ratio"] = proj

        series, proj = parse_series(r'RelativeP/ERatio', percent_ratio=False)
        valuation["relative_pe_ratio"] = series
        if proj is not None:
            projection["relative_pe_ratio"] = proj

        series, proj = parse_series(r'AvgAnn.?lDiv.?dYield', percent_ratio=False)
        valuation["avg_annual_dividend_yield_pct"] = series
        if proj is not None:
            projection["avg_annual_dividend_yield_pct"] = proj

        income_statement = {}
        series, proj = parse_series(r'P/CPremiumsEarned', percent_ratio=False)
        income_statement["pc_premiums_earned"] = series
        if proj is not None:
            projection["pc_premiums_earned_usd_millions"] = proj

        series, proj = parse_series(r'LosstoPremEarned', percent_ratio=True)
        income_statement["loss_to_prem_earned_pct"] = series
        if proj is not None:
            projection["loss_to_prem_earned_pct"] = proj

        series, proj = parse_series(r'ExpensetoPremWrit', percent_ratio=True)
        income_statement["expense_to_prem_written"] = series
        if proj is not None:
            projection["expense_to_prem_written"] = proj

        series, proj = parse_series(r'UnderwritingMargin', percent_ratio=True)
        income_statement["underwriting_margin_pct"] = series
        if proj is not None:
            projection["underwriting_margin_pct"] = proj

        series, proj = parse_series(r'IncomeTaxRate', percent_ratio=True)
        income_statement["income_tax_rate_pct"] = series
        if proj is not None:
            projection["income_tax_rate_pct"] = proj

        series, proj = parse_series(r'NetProfit', percent_ratio=False)
        income_statement["net_profit"] = series
        if proj is not None:
            projection["net_profit_usd_millions"] = proj

        series, proj = parse_series(r'InvInc/TotalInv', percent_ratio=True)
        income_statement["inv_inc_to_total_investments_pct"] = series
        if proj is not None:
            projection["inv_inc_to_total_investments_pct"] = proj

        balance_sheet = {}
        series, proj = parse_series(r'TotalAssets', percent_ratio=False)
        balance_sheet["total_assets"] = series
        if proj is not None:
            projection["total_assets_usd_millions"] = proj

        series, proj = parse_series(r'Shr.?Equity', percent_ratio=False)
        balance_sheet["shareholders_equity"] = series
        if proj is not None:
            projection["shareholders_equity_usd_millions"] = proj

        series, proj = parse_series(r'ReturnonShr.?Equity', percent_ratio=True)
        balance_sheet["return_on_shareholders_equity_pct"] = series
        if proj is not None:
            projection["return_on_shareholders_equity_pct"] = proj

        series, proj = parse_series(r'RetainedtoComEq', percent_ratio=True)
        balance_sheet["retained_to_common_equity_pct"] = series
        if proj is not None:
            projection["retained_to_common_equity_pct"] = proj

        series, proj = parse_series(r'AllDiv.?dstoNetProf', percent_ratio=True)
        balance_sheet["all_dividends_to_net_profit_pct"] = series
        if proj is not None:
            projection["all_dividends_to_net_profit_pct"] = proj

        return {
            "price_history_high_low": {
                "high": parse_price_series("High"),
                "low": parse_price_series("Low"),
                "notes": None,
            },
            "annual_financials_and_ratios_2015_2026_with_projection_2028_2030": {
                "years": years,
                "projection_year_range": proj_range,
                "per_share": {**per_share, "notes": None},
                "valuation": valuation,
                "income_statement_usd_millions": income_statement,
                "balance_sheet_and_returns_usd_millions": balance_sheet,
                "projection_2028_2030": projection,
            },
        }

    @staticmethod
    def _rating_from_words(label: str, words: list[dict[str, Any]]) -> Optional[int]:
        label_upper = label.upper()
        label_word = next(
            (w for w in words if str(w.get("text", "")).upper() == label_upper),
            None,
        )
        if not label_word:
            return None

        base_top = float(label_word.get("top", 0.0))
        label_x = float(label_word.get("x1", 0.0))
        candidates = [
            w
            for w in words
            if str(w.get("text", "")).isdigit()
            and abs(float(w.get("top", 0.0)) - base_top) < 5.0
        ]
        if not candidates:
            return None
        candidates = sorted(candidates, key=lambda w: abs(float(w.get("x0", 0.0)) - label_x))
        return int(candidates[0]["text"])

    @staticmethod
    def _parse_institutional_decisions_from_words(words: list[dict[str, Any]]) -> Optional[ExtractionResult]:
        def _round_top(w: dict[str, Any]) -> float:
            return round(float(w.get("top", 0.0)), 1)

        idx = next((i for i, w in enumerate(words) if w.get("text") == "InstitutionalDecisions"), None)
        if idx is None:
            return None

        quarter_words = [w for w in words[idx:] if w.get("text") in {"1Q", "2Q", "3Q", "4Q"}]
        quarter_words = sorted(quarter_words, key=lambda w: float(w.get("x0", 0.0)))
        if not quarter_words:
            return None

        # Holds row: "Hld’s(000)111520" + two follow-up tokens for remaining quarters.
        holds_idx = next((i for i, w in enumerate(words[idx:]) if "Hld" in str(w.get("text", ""))), None)
        holds: list[int] = []
        if holds_idx is not None:
            hword = words[idx + holds_idx].get("text", "")
            first = re.search(r'(\d{5,})', str(hword))
            if first:
                holds.append(int(first.group(1)))
            for w in words[idx + holds_idx + 1 : idx + holds_idx + 5]:
                if re.fullmatch(r'\d{5,}', str(w.get("text", ""))):
                    holds.append(int(w["text"]))
                if len(holds) >= len(quarter_words):
                    break

        quarterly: list[dict[str, Any]] = []
        for q_idx, q in enumerate(quarter_words):
            row_top = float(q.get("top", 0.0))
            base_x0 = float(q.get("x0", 0.0))
            next_x0 = (
                float(quarter_words[q_idx + 1].get("x0", 0.0))
                if q_idx + 1 < len(quarter_words)
                else base_x0 + 40.0
            )
            x_max = max(base_x0 + 12.0, next_x0 - 1.0)

            # Year tokens often appear on the same baseline (e.g., "20" "2" "5")
            year_tokens = [
                w for w in words[idx:]
                if abs(float(w.get("top", 0.0)) - row_top) < 0.6
                and base_x0 < float(w.get("x0", 0.0)) < x_max
                and re.fullmatch(r'\d{1,2}', str(w.get("text", "")))
            ]
            year_str = "".join([str(w["text"]) for w in sorted(year_tokens, key=lambda w: float(w.get("x0", 0.0)))])
            if len(year_str) == 4:
                year = int(year_str)
            else:
                year = 2000 + int(year_str[-2:]) if len(year_str) >= 2 else 0

            candidates = [
                w for w in words[idx:]
                if base_x0 < float(w.get("x0", 0.0)) < x_max
                and float(w.get("top", 0.0)) > row_top + 1.0
                and re.fullmatch(r'\d', str(w.get("text", "")))
            ]
            tops = sorted({_round_top(w) for w in candidates})
            if len(tops) < 2:
                continue

            def digits_at(top_val: float) -> str:
                ds = [w for w in candidates if _round_top(w) == top_val]
                ds = sorted(ds, key=lambda w: float(w.get("x0", 0.0)))
                return "".join([str(w["text"]) for w in ds])

            to_buy = int(digits_at(tops[0]))
            to_sell = int(digits_at(tops[1]))
            holds_000 = holds[q_idx] if q_idx < len(holds) else None

            quarterly.append({
                "period": f"{q['text']}{year}",
                "to_buy": to_buy,
                "to_sell": to_sell,
                "holds_000": holds_000,
            })

        if not quarterly:
            return None

        return ExtractionResult(
            field_key="institutional_decisions",
            raw_value_text=None,
            original_text_snippet="InstitutionalDecisions ...",
            parsed_value_json={"quarterly": quarterly},
            confidence_score=0.7,
        )
