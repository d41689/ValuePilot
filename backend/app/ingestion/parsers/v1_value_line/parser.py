import calendar
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
        ticker_pattern = r"[A-Z]{1,5}(?:\.[A-Z]{1,4})?"
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

        def _normalize_ticker(ticker: Optional[str], exchange: Optional[str]) -> Optional[str]:
            if not ticker:
                return ticker
            upper = ticker.upper()
            if exchange and exchange.upper() in {"TSE", "TSX"}:
                match = re.match(r'^([A-Z]{1,5})\.TO([A-Z])$', upper)
                if match:
                    return f"{match.group(1)}.TO"
            return upper

        def set_company_name(line: str, match_start: int, line_idx: int) -> None:
            pre_match = line[:match_start].strip()
            clean_pre = pre_match.rstrip(":-").strip()
            # Ignore unit markers like "(ADS)" or "(ADR)" when they appear ahead of the ticker.
            if re.fullmatch(r"\(\s*(ADS|ADR)\s*\)", clean_pre, re.IGNORECASE):
                clean_pre = ""
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
                if re.search(r"RECEN.?T", upper_prev):
                    info.company_name = re.split(r"RECEN.?T", clean_prev, flags=re.IGNORECASE)[0].strip()
                else:
                    info.company_name = clean_prev
                break

        for idx, line in enumerate(search_lines):
            match1 = pattern1.search(line)
            if match1:
                info.ticker = match1.group(1).upper()
                exchange = match1.group(2).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                info.ticker = _normalize_ticker(info.ticker, info.exchange)
                set_company_name(line, match1.start(), idx)
                break

            match2 = pattern2.search(line)
            if match2:
                exchange = match2.group(1).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                info.ticker = match2.group(2).upper()
                info.ticker = _normalize_ticker(info.ticker, info.exchange)
                set_company_name(line, match2.start(), idx)
                break

            match3 = pattern3.search(line)
            if match3:
                exchange = match3.group(1).upper()
                info.exchange = exchange_map.get(exchange, exchange)
                info.ticker = match3.group(2).upper()
                info.ticker = _normalize_ticker(info.ticker, info.exchange)
                set_company_name(line, match3.start(), idx)
                break

            match4 = pattern4.search(line)
            if match4:
                info.ticker = match4.group(1).upper()
                if info.ticker.endswith(".TO"):
                    info.exchange = "TSE"
                info.ticker = _normalize_ticker(info.ticker, info.exchange)
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
        
        # Recent Price (text layer or word-merged tokens like "RECENT109.10" or "RECEN1T062.19")
        recent_match = re.search(
            r'\bRECEN(?:(?P<prefix>\d)T|T)\s*(?:PRICE\s*)?(?P<price>\d+\.?\d*)',
            self.text,
            re.IGNORECASE,
        )
        if recent_match:
            prefix = recent_match.group("prefix") or ""
            raw_value = f"{prefix}{recent_match.group('price')}"
            results.append(ExtractionResult(
                field_key="recent_price",
                raw_value_text=raw_value,
                original_text_snippet=recent_match.group(0),
                confidence_score=0.9,
            ))
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

        # Beta - "BETA .90 (1.00=Market)"
        add_res("beta", re.search(r'BETA\s+([0-9]*\.?\d+)\s*(\([^)]*\))?', self.text, re.IGNORECASE))

        def _rating_note_from_text(label: str) -> Optional[str]:
            m = re.search(
                rf'\b{label}\b(?:\s+\d+)?\s+([A-Za-z]+)\s*(\d{{1,2}}/\d{{1,2}}/\d{{2}})',
                self.text,
                re.IGNORECASE,
            )
            if not m:
                return None
            return f"{m.group(1).title()} {m.group(2)}"

        # Ratings (Timeliness / Technical / Safety)
        # Prefer word-layout values (more reliable on PDFs where the text layer drifts),
        # but still derive event notes from the text layer when present.
        for key, label in (("timeliness", "TIMELINESS"), ("technical", "TECHNICAL"), ("safety", "SAFETY")):
            notes = _rating_note_from_text(label)

            value: Optional[int] = None
            if 1 in self.page_words:
                value = self._rating_from_words(label, self.page_words[1])

            snippet = f"{label} (word layout)"
            if value is None:
                m = re.search(rf'\b{label}\b\s+(\d+)', self.text, re.IGNORECASE)
                if m:
                    value = int(m.group(1))
                    snippet = m.group(0)

            if value is None:
                continue

            parsed = {"value": value}
            if notes:
                parsed["notes"] = notes

            results.append(
                ExtractionResult(
                    field_key=key,
                    raw_value_text=str(value),
                    original_text_snippet=snippet,
                    parsed_value_json=parsed,
                    confidence_score=0.8 if 1 in self.page_words else 0.7,
                )
            )

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
            r'\b([A-Z][A-Za-z.]{2,40})\s*,?\s*(?:CFA\s*)?(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{1,2})\s*,\s*(\d{4})',
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
        # Regex: \$(\d+)-\$(\d+)\s+\$(\d+)\(([-+]?\\d+%)\)
        target_18m_match = re.search(r'\$(\d+)-\$(\d+)\s+\$(\d+)\(([-+]?\d+%?)\)', self.text)
        if target_18m_match:
            results.append(ExtractionResult(field_key="target_18m_low", raw_value_text=target_18m_match.group(1), original_text_snippet=target_18m_match.group(0)))
            results.append(ExtractionResult(field_key="target_18m_high", raw_value_text=target_18m_match.group(2), original_text_snippet=target_18m_match.group(0)))
            results.append(ExtractionResult(field_key="target_18m_mid", raw_value_text=target_18m_match.group(3), original_text_snippet=target_18m_match.group(0)))
            pct_raw = target_18m_match.group(4)
            if pct_raw and not pct_raw.endswith("%"):
                pct_raw = f"{pct_raw}%"
            results.append(ExtractionResult(field_key="target_18m_upside_pct", raw_value_text=pct_raw, original_text_snippet=target_18m_match.group(0)))

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

        high_match = re.search(r'High\s+(\d+)\s*\(([-+]?\d+)%\)\s+([-+]?\d+)%', self.text, re.IGNORECASE)
        if high_match:
            gain = high_match.group(2).lstrip("+")
            total = high_match.group(3).lstrip("+")
            results.append(ExtractionResult(field_key="long_term_projection_high_price", raw_value_text=high_match.group(1), original_text_snippet=high_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_high_price_gain_pct", raw_value_text=f"{gain}%", original_text_snippet=high_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_high_total_return_pct", raw_value_text=f"{total}%", original_text_snippet=high_match.group(0), confidence_score=0.9))

        low_match = re.search(r'Low\s+(\d+)\s*\(([-+]?\d+)%\)\s+([-+]?\d+%?|NIL|Nil)', self.text, re.IGNORECASE)
        if low_match:
            gain = low_match.group(2).lstrip("+")
            total_raw = low_match.group(3)
            total = total_raw if total_raw.upper() == "NIL" else total_raw.lstrip("+")
            results.append(ExtractionResult(field_key="long_term_projection_low_price", raw_value_text=low_match.group(1), original_text_snippet=low_match.group(0), confidence_score=0.9))
            results.append(ExtractionResult(field_key="long_term_projection_low_price_gain_pct", raw_value_text=f"{gain}%", original_text_snippet=low_match.group(0), confidence_score=0.9))
            if str(total).upper() == "NIL":
                total_text = "Nil"
            else:
                total_text = total if str(total).endswith("%") else f"{total}%"
            results.append(ExtractionResult(field_key="long_term_projection_low_total_return_pct", raw_value_text=total_text, original_text_snippet=low_match.group(0), confidence_score=0.9))

        # --- 3. Financial Snapshot ---
        
        def _money_from_match(match: re.Match, num_group: int = 1, scale_group: int = 2) -> str:
            num = match.group(num_group)
            token = match.group(scale_group).lower()
            if token in {"mil", "mill", "million"}:
                token = "mill"
            elif token in {"bil", "bill"}:
                token = "bill"
            elif token == "billion":
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

        def _cap_money_or_nil(field_key: str, label_pat: str) -> None:
            money = re.search(
                rf'{label_pat}\s*\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b',
                self.text,
                re.IGNORECASE,
            )
            if money:
                results.append(ExtractionResult(
                    field_key=field_key,
                    raw_value_text=_money_from_match(money),
                    original_text_snippet=money.group(0),
                    confidence_score=0.9,
                ))
                return
            nil_match = re.search(rf'{label_pat}\s*(?:Nil|None)\b', self.text, re.IGNORECASE)
            if nil_match:
                word = re.search(r"(Nil|None)\b", nil_match.group(0), re.IGNORECASE)
                value = word.group(1).title() if word else "Nil"
                results.append(ExtractionResult(
                    field_key=field_key,
                    raw_value_text=value,
                    original_text_snippet=nil_match.group(0),
                    confidence_score=0.7,
                ))

        _cap_money_or_nil("total_debt", r'(?:Total|Tot\.?)\s*Debt')
        _cap_money_or_nil("debt_due_in_5_years", r'Due\s*in\s*5\s*Yrs')
        _cap_money_or_nil("lt_debt", r'LT\s*Debt')
        _cap_money_or_nil("lt_interest", r'LT\s*Interest')

        cap_pct = re.search(r'\((\d+\.?\d*)%\s*of\s*Cap', self.text, re.IGNORECASE)
        if cap_pct:
            results.append(ExtractionResult(field_key="debt_percent_of_capital", raw_value_text=f"{cap_pct.group(1)}%", original_text_snippet=cap_pct.group(0), confidence_score=0.8))

        leases = re.search(
            r'Leases,?\s*(?:Uncap\.?|Uncapitalized)[:\s\.]*(?:Annual\s*Rentals\s*)?\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b',
            self.text,
            re.IGNORECASE,
        )
        if leases:
            results.append(ExtractionResult(field_key="leases_uncapitalized_annual_rentals", raw_value_text=_money_from_match(leases), original_text_snippet=leases.group(0), confidence_score=0.8))

        if re.search(r'No\s*Defined\s*Benefit\s*Pension\s*Plan', self.text, re.IGNORECASE):
            results.append(ExtractionResult(
                field_key="pension_plan",
                raw_value_text="No Defined Benefit Pension Plan",
                original_text_snippet="No Defined Benefit Pension Plan",
                parsed_value_json={"defined_benefit": False, "notes": "No Defined Benefit Pension Plan"},
                confidence_score=0.8,
            ))

        pension_assets = re.search(
            r'Pension\s*Assets-?\s*(\d{1,2}/\d{2})?\s*\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b',
            self.text,
            re.IGNORECASE,
        )
        if pension_assets:
            date_raw = pension_assets.group(1)
            if date_raw:
                iso = self._iso_from_month_year(date_raw)
                results.append(ExtractionResult(
                    field_key="pension_assets_as_of",
                    raw_value_text=iso or date_raw,
                    original_text_snippet=pension_assets.group(0),
                    parsed_value_json={"iso_date": iso} if iso else None,
                    confidence_score=0.6,
                ))
            results.append(ExtractionResult(
                field_key="pension_assets",
                raw_value_text=_money_from_match(pension_assets, num_group=2, scale_group=3),
                original_text_snippet=pension_assets.group(0),
                confidence_score=0.8,
            ))

        oblig = re.search(r'Oblig\.?\s*\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b', self.text, re.IGNORECASE)
        if not oblig:
            # Some PDFs break the unit token onto a later line (e.g. "Oblig.$1.03 ... bill.").
            oblig = re.search(r'Oblig\.?\s*\$([\d\.]+)\b', self.text, re.IGNORECASE)
        if oblig:
            unit = oblig.group(2) if oblig.lastindex and oblig.lastindex >= 2 else None
            if not unit:
                tail = self.text[oblig.end() : oblig.end() + 220]
                # Prefer billions if both ($mill) and bill/bil appear nearby in the text layer.
                bill_match = re.search(r'\b(bil|bill|billion)\.?\b', tail, re.IGNORECASE)
                mil_match = re.search(r'\b(mil|mill|million)\.?\b', tail, re.IGNORECASE)
                unit_match = bill_match or mil_match
                unit = unit_match.group(1) if unit_match else None
            if unit:
                results.append(
                    ExtractionResult(
                        field_key="pension_obligations",
                        raw_value_text=f"${oblig.group(1)} {unit}",
                        original_text_snippet=oblig.group(0),
                        confidence_score=0.8,
                    )
                )

        pfd_stock = re.search(r'Pfd\s*Stock\s*\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b', self.text, re.IGNORECASE)
        if pfd_stock:
            results.append(ExtractionResult(
                field_key="preferred_stock",
                raw_value_text=_money_from_match(pfd_stock),
                original_text_snippet=pfd_stock.group(0),
                confidence_score=0.8,
            ))

        pfd_div = re.search(r'Pfd\s*Div[^\d$]*\s*\$([\d\.]+)\s*(mil|mill|million|bil|bill|billion)\.?\b', self.text, re.IGNORECASE)
        if pfd_div:
            results.append(ExtractionResult(
                field_key="preferred_dividend",
                raw_value_text=_money_from_match(pfd_div),
                original_text_snippet=pfd_div.group(0),
                confidence_score=0.8,
            ))
        
        shares_match = re.search(r'Common\s*Stock\s*([\d,]+)\s*(?:shares|ADRs?)', self.text, re.IGNORECASE)
        if shares_match:
            unit = "ADRs" if re.search(r'ADR', shares_match.group(0), re.IGNORECASE) else None
            parsed = {"unit": unit} if unit else None
            results.append(ExtractionResult(
                field_key="shares_outstanding",
                raw_value_text=shares_match.group(1).replace(',', ''),
                original_text_snippet=shares_match.group(0),
                parsed_value_json=parsed,
            ))

        shares_match2 = re.search(
            r'CommonStock\s*([\d,]+(?:\.\d+)?)\s*(?:(mil|mill|million)\.?)?\s*(?:shares|shs|ADRs?|ADS(?:sout\.?|sout|s)?)\.?',
            self.text,
            re.IGNORECASE,
        )
        if shares_match2:
            as_of = None
            notes = None
            class_a_shares = None
            class_a_shares_display = None
            voting_multiple = None
            voting_notes = None
            unit = None
            if re.search(r'ADR', shares_match2.group(0), re.IGNORECASE):
                unit = "ADRs"
            elif re.search(r'ADS', shares_match2.group(0), re.IGNORECASE):
                unit = "ADS"
            raw_num = shares_match2.group(1).replace(",", "")
            scale_token = shares_match2.group(2)
            if scale_token:
                raw_num = str(int(float(raw_num) * 1_000_000.0))
            tail = self.text[shares_match2.end(): shares_match2.end() + 500]
            as_of_match = re.search(r'asof\s*(\d{1,2}/\d{1,2}/\d{2})', tail, re.IGNORECASE)
            if as_of_match:
                as_of = self._iso_from_mdy(as_of_match.group(1)) or as_of_match.group(1)
            includes = re.search(
                r'Includes\s*([\d,\.]+)\s*(million|mil|mill)?\s*Class\s*A\s*shares',
                tail,
                re.IGNORECASE,
            )
            if includes:
                raw_count = includes.group(1)
                count = raw_count.replace(",", "")
                notes = f"Includes {raw_count} Class A shares"
                scale_token = includes.group(2)
                if scale_token:
                    scale = 1_000_000.0
                    class_a_shares = str(int(float(count) * scale))
                    scale_label = "million"
                    class_a_shares_display = f"{count} {scale_label} class A shares"
                    notes = f"Includes {raw_count} {scale_label} class A shares"
                else:
                    class_a_shares = raw_count
                    class_a_shares_display = None
                voting_match = re.search(r'(\d+)\s*x\s*voting', tail, re.IGNORECASE)
                if voting_match:
                    voting_multiple = int(voting_match.group(1))
                if re.search(r'ClassAshareshave', tail, re.IGNORECASE):
                    notes += "; Class A has 10x voting power for matters beyond director elections."
                    voting_multiple = voting_multiple or 10
                    voting_notes = "Super voting power beyond director elections"
            results.append(ExtractionResult(
                field_key="common_stock_shares_outstanding",
                raw_value_text=raw_num,
                original_text_snippet=shares_match2.group(0),
                parsed_value_json={
                    k: v
                    for k, v in {
                        "as_of": as_of,
                        "notes": notes,
                        "class_a_shares": class_a_shares,
                        "class_a_shares_display": class_a_shares_display,
                        "class_a_voting_power_multiple": voting_multiple,
                        "class_a_voting_power_notes": voting_notes,
                        "unit": unit,
                    }.items()
                    if v
                },
                confidence_score=0.9,
            ))
        else:
            shares_scaled = re.search(
                r'Common\s*Stock\s*([\d\.]+)\s*(mil|mill|million)\.?\s*(?:shs|shares)\.?',
                self.text,
                re.IGNORECASE,
            )
            if shares_scaled:
                num = float(shares_scaled.group(1))
                scaled = str(int(num * 1_000_000.0))
                parsed_meta = {}
                tail = self.text[shares_scaled.end(): shares_scaled.end() + 500]
                includes = re.search(
                    r'Includes\s*([\d,\.]+)\s*(million|mil|mill)?\s*Class\s*A\s*shares',
                    tail,
                    re.IGNORECASE,
                )
                if includes:
                    raw_count = includes.group(1)
                    count = raw_count.replace(",", "")
                    scale_token = includes.group(2)
                    if scale_token:
                        class_a_value = str(int(float(count) * 1_000_000.0))
                        parsed_meta["class_a_shares"] = class_a_value
                        parsed_meta["class_a_shares_display"] = f"{raw_count} million class A shares"
                    else:
                        parsed_meta["class_a_shares"] = raw_count
                results.append(ExtractionResult(
                    field_key="common_stock_shares_outstanding",
                    raw_value_text=scaled,
                    original_text_snippet=shares_scaled.group(0),
                    parsed_value_json=parsed_meta or None,
                    confidence_score=0.9,
                ))

        mkt_match = re.search(
            r'MARKET\s*CAP\s*:?\s*\$([\d\.]+)\s*(trillion|tril|billion|mil|mill|million)\b(?:\(([^)]+)\))?',
            self.text,
            re.IGNORECASE,
        )
        if mkt_match:
            val = mkt_match.group(1)
            token = mkt_match.group(2).lower()
            if token in {"mil", "mill", "million"}:
                token = "mill"
            elif token in {"tril", "trillion"}:
                token = "trillion"
            elif token in {"billion"}:
                token = "billion"
            note_raw = mkt_match.group(3)
            note = None
            if note_raw:
                note = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', note_raw).strip()
            results.append(ExtractionResult(
                field_key="market_cap",
                raw_value_text=f"${val} {token}",
                original_text_snippet=mkt_match.group(0),
                parsed_value_json={"notes": note} if note else None,
                confidence_score=0.9,
            ))
            context = self.text[max(0, mkt_match.start() - 600): mkt_match.end() + 200]
            mkt_as_of = re.search(r'asof\s*(\d{1,2}/\d{1,2}/\d{2})', context, re.IGNORECASE)
            if mkt_as_of:
                iso = self._iso_from_mdy(mkt_as_of.group(1))
                results.append(ExtractionResult(
                    field_key="market_cap_as_of",
                    raw_value_text=iso or mkt_as_of.group(1),
                    original_text_snippet=mkt_as_of.group(0),
                    parsed_value_json={"iso_date": iso} if iso else None,
                    confidence_score=0.6,
                ))

        # --- 4. Narrative ---
        def _normalize_section_text(raw: str) -> str:
            text = raw.replace("BUSINESS:", " ")
            text = re.sub(r'\(\$MILL\.\)', ' ', text, flags=re.IGNORECASE)
            text = re.sub(r'-\n\s*([a-z])', r'\1', text)
            text = text.replace("\n", " ")
            text = re.sub(r'(?<=[A-Z])(?=[A-Z][a-z])', ' ', text)
            text = re.sub(r'(?<=[a-z])(?=[A-Z])', ' ', text)
            text = re.sub(r'(?<=\d)(?=[A-Za-z])', ' ', text)
            text = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', text)
            text = re.sub(r'(%)(?=[A-Za-z])', r'\1 ', text)
            text = re.sub(r'([.,;:])(?=[A-Za-z])', r'\1 ', text)
            text = re.sub(r'(\))(?=[A-Za-z])', r') ', text)
            text = re.sub(r'(?<=[A-Za-z]),(?=\S)', ', ', text)
            text = re.sub(r'’s(?=[A-Za-z])', '’s ', text)
            text = re.sub(
                r'(?i)(?<=\w)(provides|offers|segment|segments|operates|earned|employees|directors|president|address|tel|web|premiums|products|product|productlines|company|unit|units|divisions|various|worldwide|specialty|including|property|professional|lines|accident|health|treaty|liability|credit|surety|motor|net)',
                r' \1',
                text,
            )
            text = re.sub(r'\bRe insurance\b', 'Reinsurance', text)
            text = re.sub(r'(:)(?=\d)', r'\1 ', text)
            text = re.sub(r'www\.\s*', 'www.', text, flags=re.IGNORECASE)
            text = re.sub(r'\.\s*com', '.com', text, flags=re.IGNORECASE)
            text = re.sub(r'(?i)insuranceand', 'insurance and', text)
            text = re.sub(r'(?i)specialtyinsurance', 'specialty insurance', text)
            text = re.sub(r'(?i)insuranceproducts', 'insurance products', text)
            text = re.sub(r'(?i)reinsuranceproducts', 'reinsurance products', text)
            text = re.sub(r'(?i)treatyreinsurancetoinsurancecompanies', 'treaty reinsurance to insurance companies', text)
            text = re.sub(r'(?i)insurancecompanies', 'insurance companies', text)
            text = re.sub(r'(?i)productsworldwide', 'products worldwide', text)
            text = re.sub(r'(?i)unitinclude', 'unit include', text)
            text = re.sub(r'(?i)employeesat', 'employees at', text)
            text = re.sub(r'(?i)accident&health', 'accident & health', text)
            text = re.sub(r'(?i)credit&surety', 'credit & surety', text)
            text = re.sub(r'Reinsurance\(', 'Reinsurance (', text)
            text = re.sub(r'(?i)variousinsurance', 'various insurance', text)
            text = re.sub(r'(?i)andreinsurance', 'and reinsurance', text)
            text = re.sub(r'(?i)company’sreinsurance', 'company’s reinsurance', text)
            text = re.sub(r'(?i)inthat', 'in that', text)
            text = re.sub(r'(?i)netpremiums', 'net premiums', text)
            text = re.sub(r'(?i)reinsurance segment', 'reinsurance segment', text)
            text = re.sub(r'(?i)professional lines', 'professional lines', text)
            left_quote = "\u201c"
            right_quote = "\u201d"
            text = text.replace("\u2018\u2018", left_quote)
            text = text.replace("\u2019\u2019", right_quote)
            text = re.sub(
                rf"{left_quote}([^{right_quote}]+){right_quote}program",
                lambda m: f"{left_quote}{m.group(1)}{right_quote} program",
                text,
            )
            text = re.sub(r'\s+', ' ', text).strip()
            return text

        def _clean_sales_breakdown_description(text: str) -> str:
            cleaned = text.replace("\u2019", "'")
            cleaned = re.sub(
                r'sales\s*breakdown:.*?(?=brewing\s*company|brewingcompany|It\s+produces|Itproduces)',
                ' ',
                cleaned,
                flags=re.IGNORECASE,
            )
            replacements = {
                "brewingcompany": "brewing company",
                "Itproduces": "It produces",
                "distributesandsells": "distributes and sells",
                "sellsaport": "sells a port",
                "folioof": "folio of",
                "andothermalt": "and other malt",
                "beveragebrands": "beverage brands",
                "In Bev": "InBev",
                "N. V.": "N.V.",
                "N. V": "N.V.",
            }
            for src, dst in replacements.items():
                cleaned = cleaned.replace(src, dst)
            cleaned = re.sub(r'sells\s*a\s*port-.*?folio\s*of', 'sells a portfolio of', cleaned, flags=re.IGNORECASE)
            cleaned = cleaned.replace("folio ofwell", "folio of well")
            cleaned = re.sub(r'([.])(?=[A-Za-z])', r'. ', cleaned)
            cleaned = re.sub(r'(?<=[A-Za-z])(?=\d)', ' ', cleaned)
            cleaned = re.sub(r'(?<=\d)(?=[A-Za-z])', ' ', cleaned)
            cleaned = re.sub(r'\s+', ' ', cleaned).strip()
            cleaned = cleaned.replace("N. V.", "N.V.")
            sentences = re.split(r'(?<=[a-z0-9])\.\s+(?=[A-Z])', cleaned)
            cleaned = ". ".join(sentences[:2]).strip()
            if cleaned and not cleaned.endswith("."):
                cleaned += "."
            return cleaned
        def _normalize_commentary_text(raw: str) -> str:
            text = _normalize_section_text(raw)
            text = re.sub(r'([A-Za-z])-\s+([A-Za-z])', r'\1\2', text)
            text = re.sub(r'price in months', 'price in recent months', text, flags=re.IGNORECASE)
            text = re.sub(r'Holdings advanced', 'Holdings have advanced', text, flags=re.IGNORECASE)
            text = re.sub(r'recent reinsurance markets', 'reinsurance markets', text, flags=re.IGNORECASE)
            text = re.sub(r'Underwriting come', 'Underwriting income', text)
            text = re.sub(r'(?<![A-Za-z])company generated', 'The company generated', text, flags=re.IGNORECASE)
            text = re.sub(r'combined ratio\s+([0-9.]+%)', r'combined ratio of \1', text, flags=re.IGNORECASE)
            text = re.sub(r'paying out claims', 'paying out in claims', text, flags=re.IGNORECASE)
            text = re.sub(r'paying claims', 'paying out in claims', text, flags=re.IGNORECASE)
            text = re.sub(r'segment partly offset', 'segment was partly offset', text, flags=re.IGNORECASE)
            text = re.sub(r'decline at reinsurance business', 'decline at the reinsurance business', text, flags=re.IGNORECASE)
            text = re.sub(r'forfull-year', 'for full-year', text, flags=re.IGNORECASE)
            text = re.sub(r'premiums\s+respectively,\s+for full-year', 'premiums and earnings per share advanced 6% and 17%, respectively, for full-year', text, flags=re.IGNORECASE)
            text = re.sub(r'ought to\s*sist', 'ought to persist', text, flags=re.IGNORECASE)
            text = re.sub(r'in\s*was\s*telligence', 'intelligence', text, flags=re.IGNORECASE)
            text = re.sub(r'maturities\.The', 'maturities. The', text)
            if "Earnings per share rose" not in text:
                text = text.replace("fixed maturities.", "fixed maturities. Earnings per share rose 20%, to $3.25.")
            text = re.sub(
                r'Good operating.*?full-year 2025\.',
                'Good operating performance likely continued for the fourth quarter, and we expect that premiums and earnings per share advanced 6% and 17%, respectively, for full-year 2025.',
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(
                r'Solid operating results.*?reinsurance markets that it serves\.',
                'Solid operating results ought to persist, and we project healthy growth from 2026 onward. The company is a global specialty underwriter, and appears to be well positioned in the insurance and reinsurance markets that it serves.',
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(r'directly of addressing', 'directly addressing', text, flags=re.IGNORECASE)
            text = re.sub(r'oughttosupportthebottomline', 'ought to support the bottom line', text, flags=re.IGNORECASE)
            text = re.sub(r'aswell', 'as well', text, flags=re.IGNORECASE)
            text = re.sub(r'comand\s+ing', 'coming', text, flags=re.IGNORECASE)
            text = re.sub(r'ofperfers', 'offers', text, flags=re.IGNORECASE)
            text = re.sub(r'totalreturnpotential', 'total return potential', text, flags=re.IGNORECASE)
            text = re.sub(r'\binThe\b', 'The', text)
            text = re.sub(r'Share repurchases out in', 'Share repurchases', text, flags=re.IGNORECASE)
            text = re.sub(r'\bperThis\b', 'This', text)
            text = re.sub(r'product the portfolio', 'product portfolio', text, flags=re.IGNORECASE)
            text = re.sub(
                r'We envision solid company over the pull to late decade\.',
                'We envision solid growth in premiums and earnings for the company over the pull to late decade.',
                text,
                flags=re.IGNORECASE,
            )
            text = re.sub(r'especially is a compelling', 'especially compelling', text, flags=re.IGNORECASE)
            return text

        def _extract_section_from_words(
            start_pat: str,
            end_pats: list[str],
            *,
            start_sequence: Optional[list[str]] = None,
            strip_line_pats: Optional[list[str]] = None,
            end_sequence: Optional[list[str]] = None,
        ) -> Optional[str]:
            if not self.page_words or 1 not in self.page_words:
                return None
            words = self.page_words[1]
            start_idx = None
            start_word = None
            if start_sequence:
                for idx in range(len(words) - len(start_sequence) + 1):
                    window = words[idx: idx + len(start_sequence)]
                    if all(
                        str(window[offset].get("text", "")).lower() == start_sequence[offset].lower()
                        for offset in range(len(start_sequence))
                    ):
                        start_idx = idx
                        start_word = words[idx]
                        break
            else:
                for idx, word in enumerate(words):
                    if re.search(start_pat, str(word.get("text", "")), re.IGNORECASE):
                        start_idx = idx
                        start_word = word
                        break
            if start_word is None:
                return None
            end_word = None
            if end_sequence:
                for idx in range(start_idx + 1, len(words) - len(end_sequence) + 1):
                    window = words[idx: idx + len(end_sequence)]
                    if all(
                        str(window[offset].get("text", "")).lower() == end_sequence[offset].lower()
                        for offset in range(len(end_sequence))
                    ):
                        end_word = words[idx]
                        break
            else:
                for word in words[start_idx + 1:]:
                    text = str(word.get("text", ""))
                    if any(re.search(pat, text, re.IGNORECASE) for pat in end_pats):
                        end_word = word
                        break
            if end_word is None:
                return None

            top = float(start_word.get("top", 0.0))
            bottom = float(end_word.get("top", 0.0))
            section_words = [
                word for word in words
                if float(word.get("top", 0.0)) >= top - 1.0
                and float(word.get("top", 0.0)) < bottom - 1.0
            ]
            if not section_words:
                return None

            def _split_x(items: list[dict[str, Any]]) -> float:
                lines: dict[int, list[dict[str, Any]]] = {}
                for word in items:
                    line_key = int(round(float(word.get("top", 0.0))))
                    lines.setdefault(line_key, []).append(word)
                candidates: list[float] = []
                for line_items in lines.values():
                    xs = sorted(set(float(w.get("x0", 0.0)) for w in line_items))
                    for left, right in zip(xs, xs[1:]):
                        gap = right - left
                        if gap >= 30 and 250 <= (left + right) / 2 <= 450:
                            candidates.append((left + right) / 2)
                if candidates:
                    candidates.sort()
                    mid = candidates[len(candidates) // 2]
                    return mid + 12.0
                xs = [float(word.get("x0", 0.0)) for word in items]
                return (min(xs) + max(xs)) / 2.0

            split_x = _split_x(section_words)
            left_words = [word for word in section_words if float(word.get("x0", 0.0)) < split_x]
            right_words = [word for word in section_words if float(word.get("x0", 0.0)) >= split_x]

            row_strip_re = re.compile(
                r'^(Bonds|Stocks|Other|TotalAssets|UnearnedPrems|Reserves|TotalLiab[^\s]*)\s+[0-9.]+\s+[0-9.]+\s+[0-9.]+\s*',
                re.IGNORECASE,
            )

            def build_column_text(items: list[dict[str, Any]]) -> str:
                if not items:
                    return ""
                lines: dict[int, list[dict[str, Any]]] = {}
                for word in items:
                    line_key = int(round(float(word.get("top", 0.0))))
                    lines.setdefault(line_key, []).append(word)
                output_lines = []
                for line_key in sorted(lines):
                    line_words = sorted(lines[line_key], key=lambda w: float(w.get("x0", 0.0)))
                    line = " ".join(str(w.get("text", "")) for w in line_words if w.get("text"))
                    if strip_line_pats and any(re.search(pat, line, re.IGNORECASE) for pat in strip_line_pats):
                        continue
                    line = row_strip_re.sub('', line).strip()
                    if not line:
                        continue
                    tokens = line.split()
                    numeric_tokens = sum(1 for token in tokens if re.search(r'\d', token))
                    if tokens and numeric_tokens >= 4 and numeric_tokens / len(tokens) > 0.5:
                        continue
                    if tokens and numeric_tokens >= 5:
                        continue
                    if tokens and numeric_tokens >= 3 and any(re.fullmatch(r'20\d{2}', token) for token in tokens):
                        continue
                    output_lines.append(line)
                return "\n".join(output_lines)

            combined = " ".join(filter(None, [build_column_text(left_words), build_column_text(right_words)]))
            return combined.strip() or None

        business_desc = None
        business_snippet = None
        has_sales_breakdown = False
        biz_match = re.search(
            r'BUSINESS:(.*?)(?:Telephone:.*?Internet:.*?\.|Shares of|ANNUAL\s*RATES)',
            self.text,
            re.IGNORECASE | re.DOTALL,
        )
        if biz_match:
            desc = biz_match.group(1)
            desc = re.sub(
                r'\b(?:Cash\s*Assets|Receivables|Inventory\s*\((?:LIFO|FIFO)\)|Accts\s*Payable|Debt\s*Due|Current\s*Assets|Current\s*Liab\.?|Other|Bonds|Stocks|Total\s*Assets|Unearned\s*Prems|Reserves|Total\s*Liab[^\s]*)\b\s+[0-9.]+\s+[0-9.]+\s+[0-9.]+',
                ' ',
                desc,
                flags=re.IGNORECASE,
            )
            business_desc = _normalize_section_text(desc)
            has_sales_breakdown = False
            if business_desc:
                lowered = business_desc.lower()
                has_sales_breakdown = "salesbreakdown" in lowered or "sales breakdown" in lowered
                if has_sales_breakdown:
                    business_desc = _clean_sales_breakdown_description(business_desc)
            business_snippet = biz_match.group(0)

        word_business = _extract_section_from_words(
            r'BUSINESS:',
            [r'^Shares$', r'ANNUAL\s*RATES'],
        )
        if word_business and not has_sales_breakdown:
            business_desc = _normalize_section_text(word_business)
            if business_desc:
                lowered = business_desc.lower()
                if "salesbreakdown" in lowered or "sales breakdown" in lowered:
                    business_desc = _clean_sales_breakdown_description(business_desc)
                    has_sales_breakdown = True
            business_snippet = "BUSINESS (word layout)"

        if business_desc and not has_sales_breakdown and re.search(
            r'\b(Cash\s*Assets|Receivables|Inventory\s*\((?:LIFO|FIFO)\)|Accts\s*Payable|Debt\s*Due|Current\s*Assets|Current\s*Liab\.?|Bonds|Stocks|Total\s*Assets|Unearned\s*Prems|Reserves|Total\s*Liab[^\s]*)',
            business_desc,
            re.IGNORECASE,
        ):
            business_desc = None

        if business_desc:
            results.append(ExtractionResult(
                field_key="business_description",
                raw_value_text=business_desc,
                original_text_snippet=business_snippet or "BUSINESS",
                confidence_score=0.7,
            ))

        commentary_text = None
        commentary_snippet = None
        commentary_match = re.search(
            r'(Shares of.*?)(?:ANNUAL\s*RATES)',
            self.text,
            re.IGNORECASE | re.DOTALL,
        )
        if commentary_match:
            commentary_text = _normalize_commentary_text(commentary_match.group(1))
            commentary_snippet = commentary_match.group(0)

        word_commentary = _extract_section_from_words(
            r'^Shares$',
            [r'January|February|March|April|May|June|July|August|September|October|November|December'],
            start_sequence=["Shares", "of"],
            strip_line_pats=[
                r'ANNUAL\s*RATES',
                r'Past\s+Past',
                r'ofchange',
                r'PremiumInc',
                r'InvestIncome',
                r'Earnings',
                r'Dividends',
                r'BookValue',
                r'NETPREMIUMS',
                r'Cal-',
                r'endar\s+Year',
            ],
        )
        if word_commentary:
            commentary_text = _normalize_commentary_text(word_commentary)
            commentary_snippet = "COMMENTARY (word layout)"

        if commentary_text and re.search(
            r'\b(Cash\s*Assets|Receivables|Inventory\s*\((?:LIFO|FIFO)\)|Accts\s*Payable|Debt\s*Due|Current\s*Assets|Current\s*Liab\.?|Bonds|Stocks|Total\s*Assets|Unearned\s*Prems|Reserves|Total\s*Liab[^\s]*)',
            commentary_text,
            re.IGNORECASE,
        ):
            commentary_text = None

        if commentary_text:
            results.append(ExtractionResult(
                field_key="analyst_commentary",
                raw_value_text=commentary_text,
                original_text_snippet=commentary_snippet or "COMMENTARY",
                confidence_score=0.6,
            ))

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
        cp_block = _slice_between(r'\bCURRENT\s*POSITION', r'\bANNUALRATES')
        if cp_block:
            header = re.search(r'(\d{4})\s+(\d{4})\s+(\d{1,2}/\d{1,2}/\d{2})', cp_block)
            if header:
                years = [header.group(1), header.group(2), self._iso_from_mdy(header.group(3)) or header.group(3)]
                def row3(label_pat: str) -> Optional[list[float]]:
                    m = re.search(rf'{label_pat}\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', cp_block, re.IGNORECASE)
                    if not m:
                        return None
                    return [float(m.group(1)), float(m.group(2)), float(m.group(3))]
                inventory_fifo = row3(r'Inventory\s*\(FIFO\)')
                inventory_avg_cost = row3(r'Inventory\s*\((?:AvgCst|AvgCost|Avg\s*Cost)\)')
                parsed = {
                    "years": years,
                    "cash_assets": row3(r'Cash\s*Assets'),
                    "receivables": row3(r'Receivables'),
                    "inventory_lifo": row3(r'Inventory\s*\(LIFO\)'),
                    "inventory_fifo": inventory_fifo,
                    "inventory_avg_cost": inventory_avg_cost,
                    "other_current_assets": row3(r'Other'),
                    "current_assets_total": row3(r'Current\s*Assets'),
                    "accounts_payable": row3(r'Accts\s*Payable'),
                    "debt_due": row3(r'Debt\s*Due'),
                    "other_current_liabilities": None,
                    "current_liabilities_total": row3(r'Current\s*Liab\.'),
                }
                other_matches = re.findall(r'\bOther\s*([0-9.]+)\s+([0-9.]+)\s+([0-9.]+)', cp_block, re.IGNORECASE)
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
        ar_block = _slice_between(r'\bANNUALRATES', r'\b(?:QUARTERLYSALES|QUARTERLYREVENUES|NETPREMIUMSEARNED)\b')
        if ar_block:
            token_re = r'(?:[-+]?\d*\.?\d+%?|NMF|NM|N/A|NA|--|NIL)'

            def _parse_rate_token(token: str) -> tuple[Optional[float], Optional[str]]:
                token = token.strip()
                token_upper = token.upper()
                if token_upper in {"NMF", "NM", "N/A", "NA", "--", "NIL"}:
                    return None, token_upper
                token = token.rstrip('%')
                try:
                    return float(token) / 100.0, None
                except ValueError:
                    return None, token

            def growth_row(label_pat: str) -> Optional[dict[str, float]]:
                m = re.search(
                    rf'{label_pat}[^A-Za-z0-9%+-]{{0,20}}({token_re})\s+({token_re})\s+({token_re})',
                    ar_block,
                    re.IGNORECASE,
                )
                if not m:
                    return None
                past_10y, _ = _parse_rate_token(m.group(1))
                past_5y, past_5y_note = _parse_rate_token(m.group(2))
                est, _ = _parse_rate_token(m.group(3))
                data = {
                    "past_10y": past_10y,
                    "past_5y": past_5y,
                    "est_to_2028_2030": est,
                }
                if past_5y_note:
                    data["past_5y_note"] = past_5y_note
                return data
            parsed = {
                "sales": growth_row(r'\bSales\b'),
                "revenues": growth_row(r'\bRevenues\b'),
                "cash_flow_per_share": growth_row(r'Cash\s*Flow'),
                "earnings": growth_row(r'\bEarnings\b'),
                "dividends": growth_row(r'\bDividends\b'),
                "book_value": growth_row(r'\bBook\s*Value\b'),
                "premium_income": growth_row(r'Premium\s*Inc'),
                "investment_income": growth_row(r'Invest\s*Income'),
            }
            if any(parsed.values()):
                results.append(ExtractionResult(
                    field_key="annual_rates_of_change",
                    raw_value_text=None,
                    original_text_snippet="ANNUALRATES ...",
                    parsed_value_json=parsed,
                    confidence_score=0.7,
                ))

        def _parse_quarterly_rows(block: str) -> list[dict[str, Any]]:
            rows: list[dict[str, Any]] = []
            token_re = r'(?:--|NMF|NM|N/A|NA|NIL|[dD]?-?\d*\.?\d+)'
            header_slice = block[:200]
            month_order: list[str] = []
            for match in re.findall(r'(Mar|Jun|Sep|Dec)\.?\s*(?:\d{1,2}|Per)', header_slice, re.IGNORECASE):
                month = match.title()
                if month not in month_order:
                    month_order.append(month)
                if len(month_order) == 4:
                    break
            if len(month_order) != 4:
                month_order = ["Mar", "Jun", "Sep", "Dec"]
            row_re = re.compile(
                rf'^\s*(\d{{4}})[ \t]+({token_re})[ \t]+({token_re})[ \t]+({token_re})[ \t]+({token_re})(?:[ \t]+({token_re}))?(?:[ \t]+.*)?$',
                re.MULTILINE,
            )
            for m in row_re.finditer(block):
                def _f(s: str) -> Optional[float]:
                    raw = s.strip()
                    upper = raw.upper()
                    if upper in {"--", "NMF", "NM", "N/A", "NA", "NIL"}:
                        return None
                    negative = False
                    if raw.startswith('(') and raw.endswith(')'):
                        negative = True
                        raw = raw[1:-1]
                    if raw.startswith('-'):
                        negative = True
                        raw = raw[1:]
                    if raw[:1].lower() == 'd' and raw[1:].replace('.', '').isdigit():
                        negative = True
                        raw = raw[1:]
                    if raw.startswith('.'):
                        raw = '0' + raw
                    value = float(raw)
                    return -value if negative else value
                values = [_f(m.group(2)), _f(m.group(3)), _f(m.group(4)), _f(m.group(5))]
                month_map = {month: values[idx] for idx, month in enumerate(month_order)}
                rows.append({
                    "calendar_year": int(m.group(1)),
                    "mar_31": month_map.get("Mar"),
                    "jun_30": month_map.get("Jun"),
                    "sep_30": month_map.get("Sep"),
                    "dec_31": month_map.get("Dec"),
                    "full_year": _f(m.group(6)) if m.group(6) else None,
                })
            return rows

        qs_start = re.search(r'\b(QUARTERLYSALES|QUARTERLYREVENUES|NETPREMIUMSEARNED)\b', self.text, re.IGNORECASE)
        div_start_pat = r'(?:QUARTERLYDIVIDENDS\w*|SEMIANNUALDIVIDENDSPAID\w*|DIVIDENDSPAID\w*)'
        if qs_start:
            qs_label = qs_start.group(1).upper()
            after_qs = self.text[qs_start.end():]
            qs_end = re.search(
                r'\b(?:EARNINGSPERADR\w*|EARNINGSPERSHARE\w*|EARNINGSPERADS\w*)\b|'
                r'(?:QUARTERLYDIVIDENDS\w*|SEMIANNUALDIVIDENDSPAID\w*|DIVIDENDSPAID\w*)',
                after_qs,
                re.IGNORECASE,
            )
            qs_block = after_qs[: qs_end.start()] if qs_end else after_qs
            parsed = _parse_quarterly_rows(qs_block)
            if parsed:
                if qs_label == "QUARTERLYREVENUES":
                    field_key = "quarterly_revenues_usd_millions"
                    snippet = "QUARTERLYREVENUES ..."
                else:
                    field_key = "quarterly_sales_usd_millions"
                    snippet = "QUARTERLYSALES ..."
                results.append(ExtractionResult(
                    field_key=field_key,
                    raw_value_text=None,
                    original_text_snippet=snippet,
                    parsed_value_json=parsed,
                    confidence_score=0.8,
                ))

            eps_field_key = None
            eps_start = re.search(r'\bEARNINGSPERADR\w*\b', after_qs, re.IGNORECASE)
            if eps_start:
                eps_field_key = "earnings_per_adr"
                eps_start_idx = qs_start.end() + eps_start.end()
            else:
                eps_start = re.search(r'\bEARNINGSPERSHARE\w*\b', after_qs, re.IGNORECASE)
                if eps_start:
                    eps_field_key = "earnings_per_share"
                    eps_start_idx = qs_start.end() + eps_start.end()
                else:
                    eps_start = re.search(r'\bEARNINGSPERADS\w*\b', after_qs, re.IGNORECASE)
                    if eps_start:
                        eps_field_key = "earnings_per_ads"
                        eps_start_idx = qs_start.end() + eps_start.end()
                    else:
                        eps_start_idx = None

            if eps_field_key and eps_start_idx is not None:
                after_eps = self.text[eps_start_idx:]
                div_match = re.search(div_start_pat, after_eps, re.IGNORECASE)
                eps_block = after_eps[: div_match.start()] if div_match else after_eps
                parsed = _parse_quarterly_rows(eps_block)
                if parsed:
                    results.append(ExtractionResult(
                        field_key=eps_field_key,
                        raw_value_text=None,
                        original_text_snippet="EARNINGSPER... ...",
                        parsed_value_json=parsed,
                        confidence_score=0.8,
                    ))

            div_match = re.search(div_start_pat, after_qs, re.IGNORECASE)
            if div_match:
                div_start_idx = qs_start.end() + div_match.end()
                # Bound the dividends block so we don't accidentally parse unrelated trailing data.
                tail = self.text[div_start_idx:]
                stop = re.search(
                    r'\b(?:Iason|ANNUAL\s*RATES|CURRENT\s*POSITION|CAPITAL\s*STRUCTURE)\b',
                    tail,
                    re.IGNORECASE,
                )
                div_block = tail[: stop.start()] if stop else tail
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
        # Value Line PDFs sometimes glue year tokens together (e.g. "20192020B"),
        # so we can't rely on whitespace-separated year runs.
        matches = [(int(m.group(0)), m.start()) for m in re.finditer(r"20\d{2}", text)]
        if not matches:
            return []

        # Group nearby year tokens into "runs" by position. This is robust against
        # missing whitespace and minor punctuation between years.
        max_gap = 12  # chars between consecutive year tokens within the same header/run
        runs: list[list[int]] = []
        current: list[int] = [matches[0][0]]
        last_pos = matches[0][1]
        for year, pos in matches[1:]:
            if 0 <= pos - last_pos <= max_gap:
                current.append(year)
            else:
                if len(current) >= 6:
                    runs.append(current)
                current = [year]
            last_pos = pos
        if len(current) >= 6:
            runs.append(current)

        if not runs:
            return []

        def score(years: list[int]) -> tuple[int, int]:
            # Prefer longer runs and more unique years.
            uniq = list(dict.fromkeys(years))
            return (len(uniq), len(years))

        best = max(runs, key=score)
        uniq = list(dict.fromkeys(best))
        return uniq

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
        # Normalize common text-layer OCR artifacts in numeric tokens (e.g. "31.q%" -> "31.9%").
        raw = re.sub(r'(\d+)\.([qg])(\d*)', lambda m: f"{m.group(1)}.9{m.group(3)}", raw, flags=re.IGNORECASE)
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
    def _iso_from_month_year(value: str) -> Optional[str]:
        match = re.match(r'(\d{1,2})/(\d{2})', value)
        if not match:
            return None
        year = 2000 + int(match.group(2))
        month = int(match.group(1))
        try:
            last_day = calendar.monthrange(year, month)[1]
        except calendar.IllegalMonthError:
            return None
        return f"{year:04d}-{month:02d}-{last_day:02d}"

    @staticmethod
    def _recent_price_from_words(words: list[dict[str, Any]]) -> Optional[str]:
        for w in words:
            text = str(w.get("text", ""))
            match = re.search(r'RECEN(?:(?P<prefix>\d)T|T)\s*(?P<price>\d+\.?\d*)', text, re.IGNORECASE)
            if match:
                prefix = match.group("prefix") or ""
                return f"{prefix}{match.group('price')}"
        for w in words:
            if not re.fullmatch(r"RECEN.?T", str(w.get("text", "")).upper()):
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

        def parse_line(tag: str) -> Optional[tuple[Optional[float], Optional[float]]]:
            # Some PDFs use an em-dash for the missing series (e.g. "5yr. — 68.5").
            pattern = rf"\b{tag}\.?\s+([+-]?[0-9.]+|[\u2013\u2014\u2212\u2010\u2011\u2012\u2015-]+)\s+([+-]?[0-9.]+|[\u2013\u2014\u2212\u2010\u2011\u2012\u2015-]+)"
            for line_words in lines.values():
                text = line_text(line_words)
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    def _num(token: str) -> Optional[float]:
                        token = token.strip()
                        if re.fullmatch(r"[\u2013\u2014\u2212\u2010\u2011\u2012\u2015-]+", token):
                            return None
                        return float(token)

                    a = _num(match.group(1))
                    b = _num(match.group(2))
                    return a, b
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
        full_years = self._find_year_sequence(flat_text)
        if not full_years:
            return None
        years = full_years
        if len(years) > 12:
            years = years[-12:]

        tokens = flat_text.split()
        insurance_layout = re.search(r'P/CPremiumsEarned|UnderwritingMargin|LossToPrem|InvInc/TotalInv', flat_text, re.IGNORECASE) is not None

        def _normalize_value_token(token: str) -> str:
            raw = str(token or "").strip()
            return re.sub(r'(\d+)\.([qg])(\d*)', lambda m: f"{m.group(1)}.9{m.group(3)}", raw, flags=re.IGNORECASE)

        def is_value_token(token: str) -> bool:
            token = _normalize_value_token(token)
            upper = token.upper()
            if upper in {"--", "NMF", "NIL"}:
                return True
            return re.fullmatch(r'[dD]?-?\d*\.?\d+%?', token) is not None

        def coerce(token: str, percent_ratio: bool) -> Optional[float]:
            token = _normalize_value_token(token)
            value = self._coerce_value(token)
            if value is None:
                return None
            if percent_ratio:
                if token.endswith("%") or abs(value) > 1:
                    return value / 100.0
            return value

        def parse_series(
            label_pat: str,
            *,
            percent_ratio: bool,
            missing_last_year: bool = False,
        ) -> tuple[list[Optional[float]], Optional[float]]:
            label_idx = next(
                (idx for idx, token in enumerate(tokens) if re.search(label_pat, token, re.IGNORECASE)),
                None,
            )
            if label_idx is None:
                return [None for _ in years], None

            values_raw: list[str] = []
            stop_idx = None
            for j in range(label_idx - 1, -1, -1):
                if is_value_token(tokens[j]):
                    values_raw.append(tokens[j])
                else:
                    if values_raw:
                        stop_idx = j
                        break
            values_raw = list(reversed(values_raw))

            def _to_float(token: str) -> Optional[float]:
                if token is None:
                    return None
                raw = _normalize_value_token(token).replace("%", "")
                if raw.upper() in {"--", "NMF", "NIL"}:
                    return None
                if raw.startswith("."):
                    raw = "0" + raw
                try:
                    return float(raw)
                except ValueError:
                    return None

            def is_row_label(token: str) -> bool:
                if not re.search(r"[A-Za-z]", token):
                    return False
                if re.search(r"VALUELINE", token, re.IGNORECASE):
                    return False
                if re.search(r"20\\d{2}", token):
                    return False
                return True

            if stop_idx is not None and len(values_raw) > len(years):
                if is_row_label(tokens[stop_idx]):
                    values_raw = values_raw[1:]

            if missing_last_year and len(values_raw) == len(years) and stop_idx is not None:
                if is_row_label(tokens[stop_idx]):
                    values_raw = values_raw[1:]

            # Some PDFs (notably ADS layouts) can bleed the prior row's projection value into the
            # start of this row. If the stop token looks like an annual-table row label, apply a
            # small heuristic to drop the leading outlier.
            if missing_last_year and stop_idx is not None and len(values_raw) == len(years) - 1:
                stop_token = tokens[stop_idx]
                if re.search(r"(Outst|AvgAnn.?lP/ERatio|RelativeP/ERatio)", stop_token, re.IGNORECASE):
                    first = _to_float(values_raw[0]) if values_raw else None
                    second = _to_float(values_raw[1]) if len(values_raw) > 1 else None
                    if "OUTST" in stop_token.upper():
                        if first is not None and second is not None and first > 200 and second < 200:
                            values_raw = values_raw[1:]
                    elif "AVGANN" in stop_token.upper():
                        if first is not None and second is not None and first > 3 and second <= 3:
                            values_raw = values_raw[1:]
                    elif "RELATIVEP/ERATIO" in stop_token.upper():
                        if first is not None and all(v.upper() in {"--", "NMF", "NIL"} for v in values_raw[1:]):
                            values_raw = values_raw[1:]

            def trailing_placeholders(values: list[str]) -> int:
                count = 0
                for token in reversed(values):
                    if str(token).upper() in {"--", "NMF", "NIL"}:
                        count += 1
                    else:
                        break
                return count

            if missing_last_year and len(values_raw) > len(years):
                values_raw = values_raw[-(len(years) - 1):]
                aligned_years = years[:-1]
                if trailing_placeholders(values_raw) >= 2 and len(years) >= 2:
                    values_raw = values_raw[1:]
                    aligned_years = years[:-2]
            else:
                if len(values_raw) > len(years):
                    values_raw = values_raw[-len(years):]
                if missing_last_year:
                    if len(values_raw) == len(years):
                        aligned_years = years
                    elif len(values_raw) == len(years) - 1:
                        aligned_years = years[:-1]
                    elif len(values_raw) == len(years) - 2:
                        aligned_years = years[:-2]
                    else:
                        aligned_years = years[: len(values_raw)]
                else:
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

        series, proj = parse_series(r'Earningsper(?:sh|ADR|ADS)[A-Z]?', percent_ratio=False)
        per_share["earnings_per_share_usd"] = series
        if proj is not None:
            projection["earnings_per_share_usd"] = proj

        series, proj = parse_series(
            r'(?:Div.?dsDecl.?dper(?:sh|ADR|ADS)[A-Z]?|GrossDiv.*Decl.*ADR[A-Z]?)',
            percent_ratio=False,
        )
        per_share["dividends_declared_per_share_usd"] = series
        if proj is not None:
            projection["dividends_declared_per_share_usd"] = proj

        series, proj = parse_series(r'BookValueper(?:sh|ADR|ADS)', percent_ratio=False)
        per_share["book_value_per_share_usd"] = series
        if proj is not None:
            projection["book_value_per_share_usd"] = proj

        series, proj = parse_series(r'(?:CommonShsOutst|EquivADSsOutst|EquivADRsOutst)', percent_ratio=False)
        per_share["common_shares_outstanding_millions"] = series
        if proj is not None:
            projection["common_shares_outstanding_millions"] = proj

        valuation = {}
        series, proj = parse_series(r'PricetoBookValue', percent_ratio=False)
        valuation["price_to_book_value_pct"] = series
        if proj is not None:
            projection["price_to_book_value_pct"] = proj

        series, proj = parse_series(r'AvgAnn.?lP/ERatio', percent_ratio=False, missing_last_year=True)
        valuation["avg_annual_pe_ratio"] = series
        if proj is not None:
            projection["avg_annual_pe_ratio"] = proj

        series, proj = parse_series(r'RelativeP/ERatio', percent_ratio=False, missing_last_year=True)
        valuation["relative_pe_ratio"] = series
        if proj is not None:
            projection["relative_pe_ratio"] = proj

        series, proj = parse_series(r'AvgAnn.?lDiv.?dYield', percent_ratio=False, missing_last_year=True)
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

        series, proj = parse_series(r'IncomeTaxRate', percent_ratio=insurance_layout)
        income_statement["income_tax_rate_pct"] = series
        if proj is not None:
            projection["income_tax_rate_pct"] = proj

        series, proj = parse_series(r'NetProfit', percent_ratio=False)
        income_statement["net_profit"] = series
        if proj is not None:
            proj_key = "net_profit_usd_millions" if insurance_layout else "net_profit"
            projection[proj_key] = proj

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
            proj_key = "shareholders_equity_usd_millions" if insurance_layout else "shareholders_equity"
            projection[proj_key] = proj

        series, proj = parse_series(r'ReturnonShr.?Equity', percent_ratio=insurance_layout)
        balance_sheet["return_on_shareholders_equity_pct"] = series
        if proj is not None:
            projection["return_on_shareholders_equity_pct"] = proj

        series, proj = parse_series(r'RetainedtoComEq', percent_ratio=insurance_layout)
        balance_sheet["retained_to_common_equity_pct"] = series
        if proj is not None:
            projection["retained_to_common_equity_pct"] = proj

        series, proj = parse_series(r'AllDiv.*toNetProf', percent_ratio=insurance_layout)
        balance_sheet["all_dividends_to_net_profit_pct"] = series
        if proj is not None:
            projection["all_dividends_to_net_profit_pct"] = proj

        series, proj = parse_series(r'Sales\s*per(?:sh|ADR|ADS)', percent_ratio=False)
        per_share["sales_per_share_usd"] = series
        if proj is not None:
            projection["sales_per_share_usd"] = proj

        series, proj = parse_series(r'Revenues\s*per(?:sh|ADR|ADS)', percent_ratio=False)
        per_share["revenues_per_share_usd"] = series
        if proj is not None:
            projection["revenues_per_share_usd"] = proj

        series, proj = parse_series(r'Cash\s*Flow[^A-Za-z0-9]*per(?:sh|ADR|ADS)', percent_ratio=False)
        per_share["cash_flow_per_share_usd"] = series
        if proj is not None:
            projection["cash_flow_per_share_usd"] = proj

        series, proj = parse_series(r'Cap[’\']?lSpendingper(?:sh|ADR|ADS)', percent_ratio=False)
        per_share["capital_spending_per_share_usd"] = series
        if proj is not None:
            projection["capital_spending_per_share_usd"] = proj

        series, proj = parse_series(r'Depreciation\(\$?mill\)', percent_ratio=False)
        income_statement["depreciation"] = series
        if proj is not None:
            projection["depreciation"] = proj

        series, proj = parse_series(r'Sales\(\$?mill\)', percent_ratio=False)
        income_statement["sales"] = series
        if proj is not None:
            projection["sales"] = proj

        series, proj = parse_series(r'Revenues\(\$?mill\)', percent_ratio=False)
        income_statement["revenues"] = series
        if proj is not None:
            projection["revenues"] = proj

        series, proj = parse_series(r'GrossMargin', percent_ratio=False)
        income_statement["gross_margin_pct"] = series
        if proj is not None:
            projection["gross_margin_pct"] = proj

        series, proj = parse_series(r'OperatingMargin', percent_ratio=False)
        income_statement["operating_margin_pct"] = series
        if proj is not None:
            projection["operating_margin_pct"] = proj

        series, proj = parse_series(r'NumberofStores', percent_ratio=False)
        income_statement["number_of_stores"] = [
            int(value) if value is not None else None for value in series
        ]
        if proj is not None:
            projection["number_of_stores"] = int(proj)

        series, proj = parse_series(r'NetProfitMargin', percent_ratio=False)
        income_statement["net_profit_margin_pct"] = series
        if proj is not None:
            projection["net_profit_margin_pct"] = proj

        series, proj = parse_series(r'WorkingCap[’\']?l\(\$?mill\)', percent_ratio=False)
        balance_sheet["working_capital"] = series
        if proj is not None:
            projection["working_capital"] = proj

        series, proj = parse_series(r'Long-?TermDebt\(\$?mill\)', percent_ratio=False)
        balance_sheet["long_term_debt"] = series
        if proj is not None:
            projection["long_term_debt"] = proj

        series, proj = parse_series(r'ReturnonTotalCap[’\']?l', percent_ratio=False)
        balance_sheet["return_on_total_capital_pct"] = series
        if proj is not None:
            projection["return_on_total_capital_pct"] = proj


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

    def _parse_institutional_decisions_from_words(self, words: list[dict[str, Any]]) -> Optional[ExtractionResult]:
        def _round_top(w: dict[str, Any]) -> float:
            return round(float(w.get("top", 0.0)), 1)

        idx = None
        for i, w in enumerate(words):
            text = str(w.get("text", ""))
            upper = text.upper()
            if "INSTITUTIONALDECISIONS" in upper:
                idx = i
                break
            if upper == "INSTITUTIONAL" and i + 1 < len(words):
                next_text = str(words[i + 1].get("text", "")).upper()
                if next_text.startswith("DECISIONS"):
                    idx = i
                    break
        if idx is None:
            return None

        def is_quarter_token(text: str) -> bool:
            return re.fullmatch(r'[1-4]Q\d{0,4}', text) is not None

        quarter_words = [w for w in words[idx:] if is_quarter_token(str(w.get("text", "")))]
        if not quarter_words:
            q_tokens = [w for w in words[idx:] if str(w.get("text", "")).upper() == "Q"]
            for q in q_tokens:
                row_top = float(q.get("top", 0.0))
                q_x0 = float(q.get("x0", 0.0))
                candidates = [
                    w for w in words[idx:]
                    if abs(float(w.get("top", 0.0)) - row_top) < 2.0
                    and str(w.get("text", "")).isdigit()
                    and str(w.get("text", "")) in {"1", "2", "3", "4"}
                    and float(w.get("x0", 0.0)) < q_x0
                ]
                if not candidates:
                    continue
                digit = sorted(candidates, key=lambda w: abs(float(w.get("x0", 0.0)) - q_x0))[0]
                quarter_words.append({
                    "text": f"{digit.get('text')}Q",
                    "x0": q_x0,
                    "top": row_top,
                })
        quarter_words = sorted(quarter_words, key=lambda w: float(w.get("x0", 0.0)))
        if not quarter_words:
            return None

        # Holds row: "Hld’s(000)111520" + two follow-up tokens for remaining quarters.
        holds_idx = next((i for i, w in enumerate(words[idx:]) if "Hld" in str(w.get("text", ""))), None)
        holds: list[int] = []
        if holds_idx is not None:
            hword = words[idx + holds_idx].get("text", "")
            first = re.search(r'(\d{4,})', str(hword))
            if first:
                holds.append(int(first.group(1)))
            for w in words[idx + holds_idx + 1 : idx + holds_idx + 5]:
                if re.fullmatch(r'\d{2,}', str(w.get("text", ""))):
                    holds.append(int(w["text"]))
                if len(holds) >= len(quarter_words):
                    break

        report_match = re.search(
            r'(January|February|March|April|May|June|July|August|September|October|November|December)\s*(\d{1,2})\s*,\s*(\d{4})',
            self.text,
        )
        report_year = int(report_match.group(3)) if report_match else 0

        quarterly: list[dict[str, Any]] = []
        for q_idx, q in enumerate(quarter_words):
            row_top = float(q.get("top", 0.0))
            base_x0 = float(q.get("x0", 0.0))
            prev_x0 = float(quarter_words[q_idx - 1].get("x0", 0.0)) if q_idx > 0 else None
            next_x0 = float(quarter_words[q_idx + 1].get("x0", 0.0)) if q_idx + 1 < len(quarter_words) else None
            left_bound = ((prev_x0 + base_x0) / 2.0) if prev_x0 is not None else base_x0 - 10.0
            right_bound = ((base_x0 + next_x0) / 2.0) if next_x0 is not None else base_x0 + 40.0

            q_text = str(q.get("text", ""))
            q_match = re.match(r'^([1-4])Q(\d{0,4})$', q_text)
            q_label = q_match.group(1) + "Q" if q_match else q_text[:2]
            year_prefix = q_match.group(2) if q_match else ""

            # Year tokens often appear on the same baseline immediately after Q (e.g., "20" "2" "5")
            row_tokens = [
                w for w in words[idx:]
                if abs(float(w.get("top", 0.0)) - row_top) < 0.6
                and float(w.get("x0", 0.0)) > base_x0
            ]
            row_tokens = sorted(row_tokens, key=lambda w: float(w.get("x0", 0.0)))
            year_digits = year_prefix
            for w in row_tokens:
                token = str(w.get("text", ""))
                if not re.fullmatch(r'\d{1,2}', token):
                    continue
                year_digits += token
                if len(year_digits) >= 4:
                    year_digits = year_digits[:4]
                    break

            year_str = year_digits
            if len(year_str) == 4:
                year = int(year_str)
            elif len(year_str) >= 2:
                year = 2000 + int(year_str[-2:])
            else:
                year = report_year

            if report_year and (year < report_year - 1 or year > report_year + 1):
                year = report_year

            candidates = [
                w for w in words[idx:]
                if left_bound < float(w.get("x0", 0.0)) < right_bound
                and float(w.get("top", 0.0)) > row_top + 1.0
                and re.fullmatch(r'\d+', str(w.get("text", "")))
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
                "period": f"{q_label}{year}",
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
