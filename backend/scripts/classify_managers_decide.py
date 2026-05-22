"""Produce a manager_type first-pass classification from the extract dump.

Input: the JSON from classify_managers_extract.py (argv[1]).
Output: decisions JSON to stdout — one row per manager, ready for
classify_managers_apply.py.

Method (see docs/tasks/2026-05-21_manager-type-classification.md):
  * EXPLICIT — managers whose type is decided by web research (activists,
    quant, multi-strategy, high-turnover) or, for managers with no 13F
    holdings ingested, by their documented strategy. Hand-curated below.
  * MECHANICAL — every other manager (all are long-only fundamental value
    managers from the Dataroma universe). The system's own behaviour rule
    is reused: a portfolio with top-10 weight >= 0.50 AND <= 25 holdings is
    `value_concentrated`, otherwise `long_term_fundamental`. Both carry an
    identical 1.00 Oracle's Lens signal weight, so this split has no scoring
    impact — it is purely descriptive.

This is a first pass. Every row is written with reviewed_by_user_id = NULL and
a note that says so; the team refines via the admin editor.
"""
from __future__ import annotations

import json
import sys

WIKI = "https://en.wikipedia.org"

# id -> (manager_type, confidence, basis_text, evidence_url_or_None)
# Researched 2026-05-21; see the task doc for the per-call evidence.
EXPLICIT: dict[int, tuple[str, str, str, str | None]] = {
    # --- Activists (signal weight 0.80) ---
    5: ("activist", "high", "documented activist hedge fund — Bill Ackman runs concentrated activist campaigns (McDonald's, Herbalife, etc.)", f"{WIKI}/wiki/Pershing_Square_Capital_Management"),
    10: ("activist", "high", "the archetypal activist investor — Carl Icahn takes large stakes and forces board/capital-allocation change", f"{WIKI}/wiki/Carl_Icahn"),
    17: ("activist", "high", "event-driven activist hedge fund — Daniel Loeb is known for activist campaigns and board pressure", f"{WIKI}/wiki/Third_Point"),
    31: ("activist", "high", "constructive activist fund — Glenn Welling runs small/mid-cap activist campaigns (37+ to date)", "https://engagedcapital.com/"),
    52: ("activist", "high", "activist fund — Nelson Peltz takes concentrated stakes and runs proxy/board campaigns", f"{WIKI}/wiki/Nelson_Peltz"),
    74: ("activist", "high", "constructive activist fund — ValueAct takes board seats and drives turnarounds from the inside", f"{WIKI}/wiki/Jeffrey_W._Ubben"),
    # --- Quant (0.40) ---
    86: ("quant", "high", "systematic global-macro firm — Bridgewater codifies its views into back-tested algorithms / computerised decision systems", f"{WIKI}/wiki/Bridgewater_Associates"),
    # --- Multi-strategy (0.60) ---
    22: ("multi_strategy", "high", "event-driven / distressed-debt / credit / macro hedge fund (David Tepper) — a multi-strategy book, not a long-only equity manager", f"{WIKI}/wiki/Appaloosa_Management"),
    38: ("multi_strategy", "high", "credit / distressed-debt / private-equity alternative manager (Howard Marks) — the 13F equity book is one sleeve of a multi-strategy firm", f"{WIKI}/wiki/Oaktree_Capital_Management"),
    # --- High turnover (0.30) ---
    50: ("high_turnover", "high", "Michael Burry / Scion rebuilds the portfolio almost completely each quarter (~250% churn), options-heavy contrarian trading", f"{WIKI}/wiki/Michael_Burry"),
    # --- TCI: activist heritage, but the current book is a stable, highly
    #     concentrated quality-growth portfolio; Hohn says activism is now
    #     "opportunistic". Classified on current behaviour (judgement call). ---
    12: ("value_concentrated", "medium", "highly concentrated quality-growth portfolio (~10 names, low turnover); activist heritage but Chris Hohn describes activism as now 'opportunistic' rather than core", f"{WIKI}/wiki/Chris_Hohn"),
    # --- Tiger Cub long/short equity funds: fundamental bottom-up stock
    #     pickers, moderate turnover — not quant/activist/passive. ---
    11: ("long_term_fundamental", "medium", "fundamental, research-driven long/short equity (Tiger Cub) — long-term approach to category-leading companies", f"{WIKI}/wiki/Tiger_Global_Management"),
    44: ("long_term_fundamental", "medium", "fundamental long/short equity (Tiger Cub, Lee Ainslie) — bottom-up high-quality longs", f"{WIKI}/wiki/Maverick_Capital"),
    64: ("long_term_fundamental", "medium", "fundamental bottom-up long/short equity (Tiger Cub, Stephen Mandel) — patient multi-year holdings", f"{WIKI}/wiki/Lone_Pine_Capital"),
    75: ("long_term_fundamental", "medium", "fundamental bottom-up long/short equity (Tiger Cub, Andreas Halvorsen) — long-term focused", f"{WIKI}/wiki/Viking_Global_Investors"),
    # --- Managers with no 13F holdings ingested: classified on documented
    #     strategy only (no prod behaviour data available). ---
    84: ("value_concentrated", "high", "concentrated value fund (David Abrams); no 13F holdings ingested for this CIK — duplicate of manager 18", None),
    81: ("value_concentrated", "high", "concentrated quality-compounder investing (Chuck Akre); no 13F holdings ingested for this CIK — duplicate of manager 15", None),
    34: ("value_concentrated", "high", "concentrated long-term value (Guy Spier, ~8-12 names); no 13F holdings ingested", None),
    63: ("value_concentrated", "high", "concentrated deep-value / special-situations (Seth Klarman, Baupost); no 13F holdings ingested", None),
    85: ("value_concentrated", "high", "concentrated deep-value (Seth Klarman, Baupost); no 13F holdings ingested — duplicate CIK of manager 63", None),
    7: ("long_term_fundamental", "high", "diversified long-term value mutual fund (Oakmark / Harris Associates, Bill Nygren); no 13F holdings ingested", None),
    28: ("value_concentrated", "high", "concentrated deep-value (Francis Chou); no 13F holdings ingested", None),
    14: ("long_term_fundamental", "high", "long-term value, diversified (Christopher Davis / Davis Advisors); no 13F holdings ingested", None),
    82: ("long_term_fundamental", "high", "permanent buy-and-hold equity portfolio (Charlie Munger's Daily Journal Corp); no 13F holdings ingested", None),
    24: ("long_term_fundamental", "high", "diversified long-term value, low turnover (Dodge & Cox); no 13F holdings ingested", None),
    27: ("long_term_fundamental", "high", "value-oriented, diversified (First Pacific Advisors / FPA); no 13F holdings ingested", None),
    65: ("long_term_fundamental", "high", "quality, very-low-turnover long-term investing (Terry Smith / Fundsmith); no 13F holdings ingested", None),
    19: ("value_concentrated", "high", "concentrated value-oriented long/short (David Einhorn / Greenlight); no 13F holdings ingested", None),
    37: ("long_term_fundamental", "medium", "value fund (Hillman Capital); no 13F holdings ingested — obscure, lower confidence", None),
    83: ("value_concentrated", "high", "ultra-concentrated long-term value (Li Lu / Himalaya Capital); no 13F holdings ingested — duplicate CIK of manager 46", None),
    45: ("long_term_fundamental", "high", "long-biased value, diversified (Leon Cooperman, ex-Omega family office); no 13F holdings ingested", None),
    48: ("long_term_fundamental", "high", "long-term quality, very low turnover (Mairs & Power); no 13F holdings ingested", None),
    51: ("value_concentrated", "high", "ultra-concentrated value (Mohnish Pabrai, ~5-10 names); no 13F holdings ingested", None),
    59: ("value_concentrated", "high", "concentrated long-term value (Robert Vinall / RV Capital); no 13F holdings ingested", None),
    60: ("value_concentrated", "high", "concentrated quality value (Ruane Cunniff / Sequoia Fund); no 13F holdings ingested", None),
    66: ("long_term_fundamental", "high", "deep-value / distressed-value, diversified (Third Avenue, Marty Whitman legacy); no 13F holdings ingested", None),
    70: ("long_term_fundamental", "medium", "long-term value, low turnover (Torray Funds); no 13F holdings ingested", None),
    # --- Makaira: prod extract returned only 1 holding (incomplete data) ---
    69: ("value_concentrated", "medium", "concentrated value fund (Tom Bancroft / Makaira Partners); prod 13F behaviour data is incomplete (1 holding ingested) — classified on documented strategy", None),
}

# Manual ids with a 13F-behaviour body so the note can still cite prod data.
EXPLICIT_WITH_BEHAVIOUR = {5, 11, 12, 17, 31, 38, 44, 50, 64, 75}


def mechanical(rec: dict) -> tuple[str, str]:
    """Return (manager_type, basis_text) for a long-only fundamental manager."""
    hc = rec.get("latest_holdings_count")
    top10 = rec.get("top10_concentration")
    if hc is None or top10 is None:
        return "long_term_fundamental", "fundamental value manager (Dataroma superinvestor); no usable 13F behaviour data"
    pct = round(top10 * 100, 1)
    if top10 >= 0.50 and hc <= 25:
        return (
            "value_concentrated",
            f"concentrated value portfolio — {hc} holdings, top-10 weight {pct}% "
            f"(prod 13F, {rec.get('latest_quarter')})",
        )
    return (
        "long_term_fundamental",
        f"diversified fundamental value portfolio — {hc} holdings, top-10 weight {pct}% "
        f"(prod 13F, {rec.get('latest_quarter')})",
    )


def main() -> None:
    extract = json.load(open(sys.argv[1]))
    decisions = []
    for rec in extract:
        mid = rec["id"]
        if mid in EXPLICIT:
            mtype, conf, basis, url = EXPLICIT[mid]
            if mid in EXPLICIT_WITH_BEHAVIOUR and rec.get("latest_holdings_count") is not None:
                basis += (
                    f" [prod 13F: {rec['latest_holdings_count']} holdings, "
                    f"top-10 {round(rec['top10_concentration'] * 100, 1)}%]"
                )
            method = "web_research" if url else "documented_strategy"
        else:
            mtype, basis = mechanical(rec)
            conf = "high" if rec.get("latest_holdings_count") else "low"
            url = None
            method = "prod_13f_behavior"
        note = (
            f"[auto-classified by Claude, first pass — pending human review] "
            f"{mtype}: {basis}. Confidence: {conf}."
        )
        evidence: dict = {"classified_by": "claude_first_pass", "method": method}
        if url:
            evidence["url"] = url
        decisions.append(
            {
                "manager_id": mid,
                "canonical_name": rec["canonical_name"],
                "manager_type": mtype,
                "confidence": conf,
                "note": note,
                "evidence_json": evidence,
            }
        )
    print(json.dumps(decisions, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
