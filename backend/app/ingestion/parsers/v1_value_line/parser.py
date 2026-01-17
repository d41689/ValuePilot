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
        
        exchange_tokens = r"(NYSE|NASDAQ|NDQ|ASE|AMEX|NAS|NMS|NCM|NGM|OTC)"
        exchange_map = {
            "NASDAQ": "NDQ",
            "NAS": "NDQ",
            "NMS": "NDQ",
            "NCM": "NDQ",
            "NGM": "NDQ",
        }

        # Pattern 1: TICKER (EXCHANGE) e.g. "MSFT (NDQ)"
        pattern1 = re.compile(rf'\b([A-Z]{{1,5}})\s*\(\s*{exchange_tokens}\s*\)', re.IGNORECASE)

        # Pattern 2: EXCHANGE-TICKER or EXCHANGE:TICKER e.g. "NYSE-ADM" / "NYSE: ADM"
        pattern2 = re.compile(rf'\b{exchange_tokens}\s*[-:]\s*([A-Z]{{1,5}})\b', re.IGNORECASE)

        # Pattern 3: EXCHANGE TICKER e.g. "NASDAQ AAPL"
        pattern3 = re.compile(rf'\b{exchange_tokens}\s+([A-Z]{{1,5}})\b', re.IGNORECASE)

        def set_company_name(line: str, match_start: int, line_idx: int) -> None:
            pre_match = line[:match_start].strip()
            if len(pre_match) > 3:
                info.company_name = pre_match
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
        
        # Recent Price
        add_res("recent_price", re.search(r'RECENT\s+(?:PRICE\s+)?(\d+\.?\d*)', self.text, re.IGNORECASE))

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
        
        shares_match = re.search(r'Common\s*Stock\s*([\d,]+)\s*shares', self.text, re.IGNORECASE)
        if shares_match:
            results.append(ExtractionResult(field_key="shares_outstanding", raw_value_text=shares_match.group(1).replace(',', ''), original_text_snippet=shares_match.group(0)))

        shares_match2 = re.search(r'CommonStock\s*([\d,]+)\s*shares', self.text, re.IGNORECASE)
        if shares_match2:
            results.append(ExtractionResult(field_key="common_stock_shares_outstanding", raw_value_text=shares_match2.group(1).replace(',', ''), original_text_snippet=shares_match2.group(0), confidence_score=0.9))

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
            def _iso_from_mdy2(s: str) -> str:
                m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2})', s)
                if not m:
                    return s
                yy = int(m.group(3))
                year = 2000 + yy
                return f"{year:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            if header:
                years = [header.group(1), header.group(2), _iso_from_mdy2(header.group(3))]
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
        cleaned = token.replace("%", "")
        if cleaned.startswith("."):
            cleaned = f"0{cleaned}"
        try:
            return float(cleaned)
        except ValueError:
            return None

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
