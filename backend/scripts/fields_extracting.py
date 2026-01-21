"""Open-world PDF field/module discovery for Value Line-style reports.

Goal
----
Given a PDF (single-company Value Line report), discover:
- page-level blocks (tables, key-value lines, narrative)
- higher-level modules/sections (e.g., CAPITAL STRUCTURE, FINANCIAL POSITION, etc.)
- candidate fields inside each module with anchors (label text + bbox + raw value text)

This is intentionally *spec-less*: it does not require a pre-defined extraction spec.
You can later refine the extraction spec / mapping spec based on this output.

Usage
-----
python -m backend.scripts.fields_extracting --pdf /path/to/file.pdf --out /tmp/out.json

Notes
-----
- Uses pdfplumber (built on pdfminer.six) to extract word-level boxes.
- Works best on text PDFs (not scanned images). For image-only PDFs you will need OCR.
- The output is *candidates* — downstream can decide which candidates to map.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import math
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


logger = logging.getLogger(__name__)


# -----------------------------
# Data structures
# -----------------------------


@dataclass(frozen=True)
class BBox:
    """PDF coordinate bounding box in pdfplumber space (x0, top, x1, bottom)."""

    x0: float
    top: float
    x1: float
    bottom: float

    def to_list(self) -> List[float]:
        return [float(self.x0), float(self.top), float(self.x1), float(self.bottom)]

    @staticmethod
    def union(boxes: Sequence["BBox"]) -> "BBox":
        x0 = min(b.x0 for b in boxes)
        top = min(b.top for b in boxes)
        x1 = max(b.x1 for b in boxes)
        bottom = max(b.bottom for b in boxes)
        return BBox(x0=x0, top=top, x1=x1, bottom=bottom)


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    size: Optional[float] = None
    fontname: Optional[str] = None

    @property
    def bbox(self) -> BBox:
        return BBox(self.x0, self.top, self.x1, self.bottom)


@dataclass
class Line:
    words: List[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words).strip()

    @property
    def bbox(self) -> BBox:
        return BBox.union([w.bbox for w in self.words])

    @property
    def y_center(self) -> float:
        b = self.bbox
        return (b.top + b.bottom) / 2.0

    @property
    def avg_font_size(self) -> Optional[float]:
        sizes = [w.size for w in self.words if w.size is not None]
        if not sizes:
            return None
        return float(sum(sizes) / len(sizes))


@dataclass
class Block:
    """A contiguous vertical group of lines."""

    lines: List[Line]

    @property
    def text(self) -> str:
        return "\n".join(l.text for l in self.lines).strip()

    @property
    def bbox(self) -> BBox:
        return BBox.union([ln.bbox for ln in self.lines])


# -----------------------------
# Helpers
# -----------------------------


_RE_SPACES = re.compile(r"\s+")
_RE_NUMERIC = re.compile(r"^[\(\-\$]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?[\)]?$|^[\-\$]?\d+(?:\.\d+)?%?$")
_RE_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_RE_QTR_DATE = re.compile(r"^(?:\d{1,2}/\d{1,2}/\d{2,4}|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\.?\s+\d{1,2})$",
                          re.IGNORECASE)


def clean_text(s: str) -> str:
    return _RE_SPACES.sub(" ", s or "").strip()


def looks_numeric(token: str) -> bool:
    t = token.strip()
    if not t:
        return False
    # pdf extraction sometimes yields "d3.15" for negative or special markers.
    t = t.lstrip("d")
    return bool(_RE_NUMERIC.match(t))


def is_mostly_upper(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    upp = sum(1 for c in letters if c.isupper())
    return upp / len(letters) >= 0.8


def normalize_label_key(label: str) -> str:
    """A conservative key normalizer for discovered field labels.

    We keep it snake_case here. Mapping spec can later map to dotted keys.
    """

    s = label.lower()
    s = s.replace("’", "'")
    s = re.sub(r"\((?:mill|mill\.|\$mill\.|\$m)\)", "", s)
    s = s.replace("/", " per ")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:128]


def split_by_x_gaps(words: Sequence[Word], gap: float) -> List[List[Word]]:
    """Split a line's words into 'cells' by x gaps."""

    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: w.x0)
    cells: List[List[Word]] = [[sorted_words[0]]]
    for w in sorted_words[1:]:
        prev = cells[-1][-1]
        if w.x0 - prev.x1 >= gap:
            cells.append([w])
        else:
            cells[-1].append(w)
    return cells



def cells_to_text(cells: Sequence[Sequence[Word]]) -> List[str]:
    out: List[str] = []
    for cell in cells:
        out.append(clean_text(" ".join(w.text for w in cell)))
    return out

# -----------------------------
# Table post-processing helpers
# -----------------------------

_RE_NUM_TOKEN = re.compile(r"^\(?d?[\$\-]?\d+(?:,\d{3})*(?:\.\d+)?%?\)?$", re.IGNORECASE)
_RE_YEAR_RANGE = re.compile(r"^\d{2}-\d{2}$")


def _is_numeric_token(tok: str) -> bool:
    t = (tok or "").strip()
    if not t:
        return False
    t = t.lstrip("d")
    if t.upper() in {"NMF", "--"}:
        return True
    return bool(_RE_NUM_TOKEN.match(t))


def _token_has_alpha(tok: str) -> bool:
    return any(ch.isalpha() for ch in (tok or ""))


def _is_label_token(tok: str) -> bool:
    t = (tok or "").strip()
    if not t:
        return False
    if t.upper() in {"NMF", "--"}:
        return False
    if _is_numeric_token(t) or _RE_YEAR.match(t) or _RE_YEAR_RANGE.match(t):
        return False
    return _token_has_alpha(t)


def _expand_numeric_only_cells(cells: List[str]) -> List[str]:
    """Split a cell like '1.4% 1.4% 2.1%' into separate numeric cells.

    We only expand when the cell is made entirely of numeric-like tokens (including NMF/--)
    so we don't accidentally split prose.
    """

    out: List[str] = []
    for c in cells:
        c_clean = clean_text(c)
        if not c_clean:
            continue
        toks = c_clean.split()
        if len(toks) >= 2 and all(_is_numeric_token(t) for t in toks):
            out.extend(toks)
        else:
            out.append(c_clean)
    return out


def _split_mixed_numeric_label_cells(cells: List[str]) -> List[str]:
    """Split cells that contain many numeric tokens plus a trailing label.

    Example:
      "9.0% 9.8% 9.5% 11.5% NetProfitMargin"
        -> ["9.0%", "9.8%", "9.5%", "11.5%", "NetProfitMargin"]
    """

    out: List[str] = []
    for c in cells:
        c_clean = clean_text(c)
        if not c_clean:
            continue
        toks = c_clean.split()
        if len(toks) < 3:
            out.append(c_clean)
            continue

        num_flags = []
        for t in toks:
            if _is_numeric_token(t) or _RE_YEAR.match(t) or _RE_YEAR_RANGE.match(t):
                num_flags.append(True)
            else:
                num_flags.append(False)

        if sum(num_flags) < 3 or not any(_is_label_token(t) for t in toks):
            out.append(c_clean)
            continue

        label_start = None
        numeric_seen = 0
        for i, t in enumerate(toks):
            if num_flags[i]:
                numeric_seen += 1
                continue
            if _is_label_token(t) and numeric_seen >= 3:
                label_start = i
                break

        if label_start is None:
            out.append(c_clean)
            continue

        tail_start = len(toks)
        i = len(toks) - 1
        while i > label_start and num_flags[i]:
            tail_start = i
            i -= 1

        leading = toks[:label_start]
        label_tokens = toks[label_start:tail_start]
        trailing = toks[tail_start:]

        if not any(_is_label_token(t) for t in label_tokens):
            out.append(c_clean)
            continue

        out.extend([clean_text(t) for t in leading if t])
        out.append(clean_text(" ".join(label_tokens)))
        out.extend([clean_text(t) for t in trailing if t])

    return out


def _normalize_institutional_decisions_row(cells: List[str]) -> List[str]:
    """Fix common Value Line Institutional Decisions row concatenation.

    Example bad parse:
      ['toBuy','257','250','192 shares','4']
    Desired:
      ['toBuy','257','250','192','shares','4']

    We also handle '259 traded' similarly.
    """

    if not cells:
        return cells

    head = cells[0].strip()
    if head not in {"toBuy", "toSell"}:
        return cells

    fixed: List[str] = []
    for c in cells:
        c0 = clean_text(c)
        m = re.match(r"^(\(?d?[\$\-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?\)?)\s+(shares|traded)$", c0, flags=re.IGNORECASE)
        if m:
            fixed.append(clean_text(m.group(1)))
            fixed.append(clean_text(m.group(2)))
        else:
            fixed.append(c0)

    return fixed


# -----------------------------
# Value truncation helper
# -----------------------------

def truncate_value_before_prose(value_text: str) -> str:
    """Trim a value string at the point where narrative prose begins.

    Value Line left-column financial position rows often sit next to BUSINESS prose.
    PDF extraction may concatenate both. We keep numeric/unit tokens and stop when
    we encounter sustained prose-like tokens.
    """

    allowed_words = {
        "nmf",
        "--",
        "nil",
        "none",
        "bill",
        "bill.",
        "billion",
        "mill",
        "mill.",
        "million",
        "thou",
        "thou.",
        "%",
    }

    tokens = clean_text(value_text).split()
    kept: List[str] = []
    prose_hits = 0

    for tok in tokens:
        t = tok.strip()
        tl = t.lower().strip(".,;:")
        # numeric-ish / symbols / known short units are safe
        if looks_numeric(t) or _RE_YEAR.match(t) or tl in allowed_words or re.fullmatch(r"[\d\-\$\(\)\.,%]+", t):
            kept.append(tok)
            prose_hits = 0
            continue

        # short footnote markers like "A"/"B"/"C" are OK
        if len(t) <= 2 and t.isalpha() and t.isupper():
            kept.append(tok)
            prose_hits = 0
            continue

        # otherwise it's likely prose
        prose_hits += 1
        if prose_hits >= 2:
            break

    return clean_text(" ".join(kept))


# -----------------------------
# Core extraction
# -----------------------------


def extract_words(pdf_path: str) -> List[List[Word]]:
    """Return words per page."""

    import pdfplumber  # local import to keep dependency optional at import time

    pages_words: List[List[Word]] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            # extra_attrs are not always available depending on pdfplumber version
            raw_words = page.extract_words(
                use_text_flow=False,
                keep_blank_chars=False,
                extra_attrs=["size", "fontname"],
            )
            words: List[Word] = []
            for w in raw_words:
                txt = (w.get("text") or "").strip()
                if not txt:
                    continue
                words.append(
                    Word(
                        text=txt,
                        x0=float(w["x0"]),
                        x1=float(w["x1"]),
                        top=float(w["top"]),
                        bottom=float(w["bottom"]),
                        size=float(w.get("size")) if w.get("size") is not None else None,
                        fontname=str(w.get("fontname")) if w.get("fontname") is not None else None,
                    )
                )
            pages_words.append(words)
    return pages_words


def group_words_into_lines(words: Sequence[Word], y_tol: float = 2.0) -> List[Line]:
    """Group words into lines using their 'top' coordinates."""

    if not words:
        return []

    # Sort by y then x
    ws = sorted(words, key=lambda w: (w.top, w.x0))

    lines: List[List[Word]] = []
    cur: List[Word] = []
    cur_y: Optional[float] = None

    for w in ws:
        if cur_y is None:
            cur_y = w.top
            cur = [w]
            continue
        if abs(w.top - cur_y) <= y_tol:
            cur.append(w)
            # keep a running average y
            cur_y = (cur_y * 0.8) + (w.top * 0.2)
        else:
            lines.append(cur)
            cur = [w]
            cur_y = w.top

    if cur:
        lines.append(cur)

    # Within each line, sort by x
    out = [Line(words=sorted(lw, key=lambda w: w.x0)) for lw in lines]
    return out


def group_lines_into_blocks(lines: Sequence[Line], gap_tol: float = 10.0) -> List[Block]:
    """Group lines into blocks by vertical gaps."""

    if not lines:
        return []

    # sort by y
    ls = sorted(lines, key=lambda l: l.bbox.top)

    blocks: List[List[Line]] = [[ls[0]]]
    for ln in ls[1:]:
        prev = blocks[-1][-1]
        gap = ln.bbox.top - prev.bbox.bottom
        if gap >= gap_tol:
            blocks.append([ln])
        else:
            blocks[-1].append(ln)

    return [Block(lines=b) for b in blocks if b]




# --- layout helpers (two-column pages) ---

def _kmeans_1d_two_clusters(xs: List[float], iters: int = 12) -> Optional[Tuple[float, float]]:
    """Very small 1D k-means for k=2. Returns (c1, c2) sorted, or None if not enough data."""

    if len(xs) < 50:
        return None
    x_min = min(xs)
    x_max = max(xs)
    if x_max - x_min < 1e-6:
        return None

    # init: quartiles
    xs_sorted = sorted(xs)
    c1 = xs_sorted[len(xs_sorted) // 4]
    c2 = xs_sorted[(len(xs_sorted) * 3) // 4]
    if abs(c2 - c1) < 1e-6:
        return None

    for _ in range(iters):
        g1: List[float] = []
        g2: List[float] = []
        for x in xs:
            if abs(x - c1) <= abs(x - c2):
                g1.append(x)
            else:
                g2.append(x)
        if not g1 or not g2:
            return None
        c1_new = sum(g1) / len(g1)
        c2_new = sum(g2) / len(g2)
        if abs(c1_new - c1) < 0.05 and abs(c2_new - c2) < 0.05:
            c1, c2 = c1_new, c2_new
            break
        c1, c2 = c1_new, c2_new

    if c1 > c2:
        c1, c2 = c2, c1
    return (float(c1), float(c2))


def split_words_into_columns(
    words: Sequence[Word],
    page_width: float,
) -> Tuple[List[Word], List[Word], Optional[float]]:
    """Split page words into (left, right, x_split) for common two-column Value Line layouts.

    If no reliable split is found, returns (all_words, [], None).
    """

    if not words:
        return [], [], None

    # Use word x-centers for clustering.
    xs = [((w.x0 + w.x1) / 2.0) for w in words]
    centers = _kmeans_1d_two_clusters(xs)
    if centers is None:
        return list(words), [], None

    c1, c2 = centers
    # Require meaningful separation between columns.
    if (c2 - c1) < (page_width * 0.22):
        return list(words), [], None

    x_split = (c1 + c2) / 2.0

    left: List[Word] = []
    right: List[Word] = []
    for w in words:
        x_center = (w.x0 + w.x1) / 2.0
        if x_center <= x_split:
            left.append(w)
        else:
            right.append(w)

    # Sanity: both sides need enough content.
    if len(left) < max(40, int(len(words) * 0.15)) or len(right) < max(40, int(len(words) * 0.15)):
        return list(words), [], None

    return left, right, float(x_split)


# --- heading filters / whitelist ---


_HEADING_WHITELIST = {
    # canonical Value Line section anchors (loose; spec-less helper)
    "CAPITAL STRUCTURE",
    "CURRENT POSITION",
    "FINANCIAL POSITION",
    "ANNUAL RATES",
    "QUARTERLY SALES",
    "EARNINGS PER",
    "QUARTERLY DIVIDENDS PAID",
    "BUSINESS",
    "INSTITUTIONAL DECISIONS",
    "TARGET PRICE RANGE",
    "PROJECTIONS",
    "%TOT.RETURN",
}


def _compact_upper(s: str) -> str:
    """Uppercase text with whitespace removed; helps match concatenated headings."""

    return re.sub(r"\s+", "", (s or "").upper())


def _is_financials_unit_anchor(text: str) -> bool:
    """Detect the small unit tag that often starts the financial statement table block.

    In Value Line pages, the financial-statement-style table frequently starts with a
    standalone line like "($MILL.)" (or similar). We use it as a section boundary even
    though it is not a heading.
    """

    t = clean_text(text)
    if not t:
        return False
    # Common variants
    if re.fullmatch(r"\(\$?\s*MILL\.?\)\.?", t, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"\(\$?\s*BILL\.?\)\.?", t, flags=re.IGNORECASE):
        return True
    if re.fullmatch(r"\(\$?\s*THOU\.?\)\.?", t, flags=re.IGNORECASE):
        return True
    return False


def _is_quarter_header_like(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    # e.g. "1Q2025 2Q2025 3Q2025 STOCK INDEX"
    q_tokens = re.findall(r"\b[1-4]Q\d{4}\b", t)
    if len(q_tokens) >= 2:
        return True
    # e.g. "Cal- QUARTERLYSALES($mill.) Full" should still pass (handled by whitelist-ish)
    return False


def _looks_like_small_label(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    # small unit tags like "($MILL.)"
    if re.fullmatch(r"\(\$?\s*MILL\.?\)\.?", t, flags=re.IGNORECASE):
        return True
    if len(t) <= 6 and all(not ch.isalpha() for ch in t):
        return True
    return False

def has_long_upper_run(s: str, min_run: int = 6) -> bool:
    """Return True if string contains a contiguous run of uppercase letters of length >= min_run.

    Helps detect headings that are concatenated without spaces, e.g. "CAPITALSTRUCTUREasof6/30/25".
    """

    run = 0
    for ch in s:
        if ch.isalpha() and ch.isupper():
            run += 1
            if run >= min_run:
                return True
        else:
            run = 0
    return False


def detect_heading_line(line: Line, page_width: float) -> bool:
    """Heuristic heading detector.

    Value Line PDFs often have section headers that are:
    - mostly uppercase ("CURRENT POSITION") OR
    - concatenated uppercase runs with small lowercase glue ("CAPITALSTRUCTUREasof6/30/25")

    We treat a line as a heading if it is short-ish, not mostly numeric, and is aligned
    either left-ish or centered.
    """

    text = clean_text(line.text)
    if not text:
        return False

    # Minimum signal: avoid tiny tags like "($MILL.)"
    if _looks_like_small_label(text):
        return False

    # Prevent over-splitting on table headers (quarters/stock index header lines)
    if _is_quarter_header_like(text):
        return False

    # Keep headings reasonably short.
    if len(text) > 70:
        return False

    # Allow known section anchors even if casing is imperfect.
    up = text.upper()
    up_compact = _compact_upper(text)
    for kw in _HEADING_WHITELIST:
        if kw in up:
            return True
        # Also match concatenated headings like "CAPITALSTRUCTUREasof...".
        kw_compact = _compact_upper(kw)
        if kw_compact and kw_compact in up_compact:
            return True

    # Must look like a heading by casing.
    if not (is_mostly_upper(text) or has_long_upper_run(text) or text.endswith(":")):
        return False

    # Require some alpha content.
    tokens = text.split()
    if len(tokens) < 1:
        return False

    # Extra guard: reject headings that are dominated by numeric/ratio tokens (common in metric rows)
    numeric_like = 0
    for t in tokens:
        tt = t.strip()
        if tt in {"NMF", "--"}:
            numeric_like += 1
            continue
        # strip common pdf marker prefix
        tt = tt.lstrip("d")
        if looks_numeric(tt) or _RE_YEAR.match(tt) or _RE_QTR_DATE.match(tt) or re.fullmatch(r"[\d\.\-/%$()]+", tt):
            numeric_like += 1
    numeric_like_ratio = numeric_like / max(1, len(tokens))

    # Avoid headings that are basically years / numeric strings.
    if tokens and all(_RE_YEAR.match(t) for t in tokens):
        return False

    numeric_ratio = sum(1 for t in tokens if looks_numeric(t)) / max(1, len(tokens))
    # If either ratio is high, it's almost certainly a metric row, not a section heading.
    if numeric_ratio > 0.30 or numeric_like_ratio > 0.45:
        return False

    bbox = line.bbox
    x_center = (bbox.x0 + bbox.x1) / 2.0
    centered = abs(x_center - (page_width / 2.0)) <= (page_width * 0.20)
    leftish = bbox.x0 <= (page_width * 0.18)

    return centered or leftish


def classify_block(block: Block) -> str:
    """Classify a block into one of: heading, table, kv, narrative."""

    lines = block.lines
    if not lines:
        return "unknown"

    # If it is a single strong heading-like line, call it heading
    if len(lines) == 1:
        t = clean_text(lines[0].text)
        if t and (is_mostly_upper(t) or t.endswith(":")) and len(t) <= 45:
            return "heading"

    # Heuristic: build a grid by splitting each line into cells
    row_cells: List[List[str]] = []
    numeric_cells = 0
    total_cells = 0
    max_cols = 0
    for ln in lines:
        # A larger gap splits columns; tuneable
        cells = split_by_x_gaps(ln.words, gap=12.0)
        texts = [c for c in cells_to_text(cells) if c]
        if not texts:
            continue
        row_cells.append(texts)
        max_cols = max(max_cols, len(texts))
        for cell in texts:
            total_cells += 1
            if looks_numeric(cell) or _RE_YEAR.match(cell) or _RE_QTR_DATE.match(cell):
                numeric_cells += 1

    if not row_cells:
        return "narrative"

    numeric_ratio = numeric_cells / max(1, total_cells)

    # Table-ish: at least 3 columns in many rows, and lots of numeric-like cells.
    if max_cols >= 4 and numeric_ratio >= 0.45:
        return "table"
    if max_cols >= 3 and numeric_ratio >= 0.60 and len(row_cells) >= 3:
        return "table"

    # KV-ish: many lines of the form "Label ... Value" with one numeric cell.
    kv_hits = 0
    for row in row_cells:
        if len(row) >= 2 and any(looks_numeric(x) for x in row[1:]):
            kv_hits += 1
    if kv_hits >= max(2, math.ceil(len(row_cells) * 0.5)):
        return "kv"

    return "narrative"


def parse_kv_candidates(block: Block) -> List[Dict[str, Any]]:
    """Parse candidate label/value pairs from a KV-like block."""

    out: List[Dict[str, Any]] = []
    # Multi-field KV pattern: e.g. "LTDebt $72.0bill. LTInterest $4.1bill." on one physical line.
    # We keep it permissive; values may include $, %, parentheses, d-prefix, and short unit suffixes.
    multi_kv_re = re.compile(
        r"(?P<label>[A-Za-z][A-Za-z0-9’'\-\.\/\s]{1,40}?)\s+"
        r"(?P<val>\$?\(?d?[\d]{1,3}(?:,[\d]{3})*(?:\.[\d]+)?%?\)?(?:\s*(?:bill\.|mill\.|billion|million))?)",
        flags=re.IGNORECASE,
    )
    for ln in block.lines:
        cells = split_by_x_gaps(ln.words, gap=12.0)
        texts = [c for c in cells_to_text(cells) if c]
        if len(texts) < 2:
            continue

        joined_line = clean_text(" ".join(texts))
        # Normalize common broken tokens produced by PDF extraction
        # e.g. "Duein5 Yrs" -> "Duein5Yrs" so we keep the semantic label intact.
        joined_line = joined_line.replace("’", "'")
        joined_line = re.sub(r"\bDue\s*in\s*(\d+)\s*Yrs\b", r"Duein\1Yrs", joined_line, flags=re.IGNORECASE)
        joined_line = re.sub(r"\bDuein(\d+)\s*Yrs\b", r"Duein\1Yrs", joined_line, flags=re.IGNORECASE)

        # Guard: skip known table header lines (they are not key-value facts)
        up = joined_line.upper()
        if ("ANNUALRATES" in up) or ("ANNUAL RATES" in up) or ("OFCHANGE(" in up) or ("OF CHANGE(" in up):
            continue

        # Guard: if the line looks like a dense year/time-series row, don't treat it as KV.
        year_tokens = re.findall(r"\b(?:19|20)\d{2}\b", joined_line)
        if len(year_tokens) >= 6:
            continue

        # Guard: reject labels that are dominated by numeric tokens (common in financial grids).
        toks = joined_line.split()
        if toks:
            num_like = 0
            for tt in toks:
                ttt = tt.strip().lstrip("d")
                if looks_numeric(ttt) or _RE_YEAR.match(ttt) or _RE_QTR_DATE.match(ttt) or ttt in {"NMF", "--"}:
                    num_like += 1
            if (num_like / max(1, len(toks))) >= 0.60:
                continue

        # Try multi-field KV extraction first (common in CAPITAL STRUCTURE lines).
        multi = list(multi_kv_re.finditer(joined_line))
        if len(multi) >= 2:
            for m in multi:
                label = clean_text(m.group("label"))
                value = clean_text(m.group("val"))
                if not label or not value:
                    continue
                # Require a meaningful label (avoid tiny fragments like "Yrs")
                alpha_cnt = sum(1 for ch in label if ch.isalpha())
                if alpha_cnt < 4:
                    continue
                # Avoid labels that are actually numeric grids
                if sum(1 for t in label.split() if looks_numeric(t) or _RE_YEAR.match(t)) > 1:
                    continue
                out.append(
                    {
                        "label": label,
                        "label_key": normalize_label_key(label),
                        "value_text": value,
                        "bbox": ln.bbox.to_list(),
                        "method": "multi_kv_regex",
                    }
                )
            continue

        # Strategy: treat leftmost non-numeric chunk as label; rightmost numeric-ish chunk as value.
        # Example: "TotalDebt $1316.9 mill." or "MarketCap: $8.4 billion"
        label_parts: List[str] = []
        value_parts: List[str] = []

        # If there is a ':' we can split reliably
        joined = clean_text(" ".join(texts))
        if ":" in joined:
            left, right = joined.split(":", 1)
            label = clean_text(left)
            value = truncate_value_before_prose(clean_text(right))
            if not value:
                continue
            if label and value:
                # Avoid garbage labels that are mostly numeric.
                if sum(1 for t in label.split() if looks_numeric(t) or _RE_YEAR.match(t)) <= 1 and any(ch.isalpha() for ch in label):
                    out.append(
                        {
                            "label": label,
                            "label_key": normalize_label_key(label),
                            "value_text": value,
                            "bbox": ln.bbox.to_list(),
                            "method": "colon_split",
                        }
                    )
            continue

        # Otherwise use cell-based heuristic
        # Find last numeric-ish cell (or last cell), everything before becomes label
        last_val_idx = None
        for i in range(len(texts) - 1, 0, -1):
            if looks_numeric(texts[i]) or any(ch.isdigit() for ch in texts[i]):
                last_val_idx = i
                break
        if last_val_idx is None:
            continue

        label_parts = texts[:last_val_idx]
        value_parts = texts[last_val_idx:]

        label = clean_text(" ".join(label_parts))
        value = truncate_value_before_prose(clean_text(" ".join(value_parts)))
        if not value:
            continue

        # joined_line already computed above
        multi = list(multi_kv_re.finditer(joined_line))

        # Avoid accidentally treating year rows as kv
        if label and value and not _RE_YEAR.fullmatch(label):
            # Reject accidental labels made from numeric grids.
            label_tokens = label.split()
            label_num_like = sum(1 for t in label_tokens if looks_numeric(t) or _RE_YEAR.match(t) or _RE_QTR_DATE.match(t) or t in {"NMF", "--"})
            if any(ch.isalpha() for ch in label) and (label_num_like <= 1) and (len(label) <= 60):
                out.append(
                    {
                        "label": label,
                        "label_key": normalize_label_key(label),
                        "value_text": value,
                        "bbox": ln.bbox.to_list(),
                        "method": "cell_split",
                    }
                )

    return out


def parse_table_candidates(block: Block) -> Dict[str, Any]:
    """Parse a table-like block into rows/cells with inferred header row (best-effort)."""

    rows: List[Dict[str, Any]] = []

    for ln in block.lines:
        cells = split_by_x_gaps(ln.words, gap=12.0)
        texts = [c for c in cells_to_text(cells) if c]
        if not texts:
            continue

        # Post-process: expand numeric-only cells (fixes '1.4% 1.4% 2.1%' sticking together)
        texts = _expand_numeric_only_cells(texts)

        # Post-process: split cells with numeric runs plus trailing labels
        texts = _split_mixed_numeric_label_cells(texts)

        # Post-process: fix common Institutional Decisions concatenation ('192 shares', '259 traded')
        texts = _normalize_institutional_decisions_row(texts)

        rows.append({"cells": texts, "bbox": ln.bbox.to_list()})

    # Header inference: first row with low numeric ratio
    header: Optional[List[str]] = None
    header_idx: Optional[int] = None
    for i, r in enumerate(rows[: min(len(rows), 4)]):
        cells = r["cells"]
        if not cells:
            continue
        num_ratio = sum(1 for c in cells if looks_numeric(c) or _RE_YEAR.match(c)) / len(cells)
        if num_ratio <= 0.25:
            header = cells
            header_idx = i
            break

    return {
        "bbox": block.bbox.to_list(),
        "header": header,
        "header_row_index": header_idx,
        "rows": rows,
    }


# --- Table splitting helper: split STOCK INDEX table from year grid ---
def split_table_on_year_row(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Split a parsed table into sub-tables when a dense year header row is detected.

    Value Line right-column areas often contain a small "%TOT.RETURN / STOCK INDEX" table above
    a yearly financial grid whose first row includes many years (e.g., 2015..2026).

    We split at the first row that contains >= 6 year tokens.
    """

    if not table or not table.get("rows"):
        return [table]

    rows = table.get("rows", [])

    def year_token_count(cells: List[str]) -> int:
        toks: List[str] = []
        for c in cells:
            toks.extend(clean_text(c).split())
        return sum(1 for t in toks if _RE_YEAR.match(t))

    split_idx: Optional[int] = None
    for i, r in enumerate(rows):
        cells = r.get("cells") or []
        if year_token_count(cells) >= 6:
            split_idx = i
            break

    if split_idx is None or split_idx <= 0 or split_idx >= len(rows):
        return [table]

    def build_sub(rows_slice: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not rows_slice:
            return {}
        # Recompute bbox union from row bboxes
        bxs: List[BBox] = []
        for rr in rows_slice:
            bb = rr.get("bbox")
            if isinstance(bb, list) and len(bb) == 4:
                bxs.append(BBox(float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])))
        bbox = BBox.union(bxs).to_list() if bxs else table.get("bbox")

        # Infer header row again (same logic as parse_table_candidates)
        header = None
        header_idx = None
        for j, rr in enumerate(rows_slice[: min(len(rows_slice), 4)]):
            cells = rr.get("cells") or []
            if not cells:
                continue
            num_ratio = sum(1 for c in cells if looks_numeric(c) or _RE_YEAR.match(c)) / max(1, len(cells))
            if num_ratio <= 0.25:
                header = cells
                header_idx = j
                break

        return {
            "bbox": bbox,
            "header": header,
            "header_row_index": header_idx,
            "rows": rows_slice,
        }

    top = build_sub(rows[:split_idx])
    bottom = build_sub(rows[split_idx:])

    out: List[Dict[str, Any]] = []
    if top:
        out.append(top)
    if bottom:
        out.append(bottom)
    return out or [table]


def assign_blocks_to_modules(
    blocks: Sequence[Block],
    page_width: float,
) -> List[Dict[str, Any]]:
    """Create modules by finding heading blocks and attaching subsequent blocks until next heading.

    Note: the main pipeline prefers line-based module splitting (`assign_lines_to_modules`) because
    Value Line pages are dense and block grouping can collapse too much.
    """

    indexed = list(enumerate(blocks))
    heading_idxs: List[int] = []
    for i, b in indexed:
        first_line = b.lines[0] if b.lines else None
        if not first_line:
            continue
        if detect_heading_line(first_line, page_width=page_width):
            txt = clean_text(first_line.text)
            if any(x in txt for x in ["NYSE", "NASDAQ", "P/E", "RELATIVE", "VALUE LINE", "RECENT"]):
                continue
            heading_idxs.append(i)

    heading_idxs = sorted(set(heading_idxs))

    if not heading_idxs:
        return [
            {
                "name": "__page__",
                "anchor_text": None,
                "bbox": None,
                "blocks": [serialize_block(b) for b in blocks],
            }
        ]

    modules: List[Dict[str, Any]] = []
    for pos, h_idx in enumerate(heading_idxs):
        h_block = blocks[h_idx]
        h_text = clean_text(h_block.lines[0].text) if h_block.lines else ""
        start = h_idx
        end = heading_idxs[pos + 1] if pos + 1 < len(heading_idxs) else len(blocks)
        body_blocks = blocks[start:end]
        modules.append(
            {
                "name": normalize_module_name(h_text) or h_text or "__module__",
                "anchor_text": h_text,
                "bbox": h_block.bbox.to_list(),
                "blocks": [serialize_block(b) for b in body_blocks],
            }
        )

    return modules

def assign_lines_to_modules(
    lines: Sequence[Line],
    page_width: float,
    page_height: float,
    *,
    top_header_cutoff: float = 0.12,
    block_gap_tol: float = 4.0,
) -> List[Dict[str, Any]]:
    """Create modules by scanning *lines* for headings.

    This is more robust than heading-as-block detection because many pages are dense and
    block grouping can collapse the entire page into one large block.

    - We ignore heading candidates in the top header region (ticker/price strip).
    - We split the page into sections by heading line positions.
    """

    if not lines:
        return []

    ls = sorted(lines, key=lambda l: l.bbox.top)

    # Identify heading line indices.
    heading_idxs: List[int] = []
    for i, ln in enumerate(ls):
        if ln.bbox.top <= (page_height * top_header_cutoff):
            continue
        if detect_heading_line(ln, page_width=page_width):
            txt = clean_text(ln.text)
            # Avoid the very top header-ish fragments if they slip through.
            if any(x in txt for x in ["NYSE", "NASDAQ", "P/E", "RELATIVE", "VALUE LINE", "RECENT"]):
                continue
            heading_idxs.append(i)

    heading_idxs = sorted(set(heading_idxs))

    # Also split on the financials unit anchor, which is not a heading but is a reliable table boundary.
    unit_anchor_idxs: List[int] = []
    for i, ln in enumerate(ls):
        if ln.bbox.top <= (page_height * top_header_cutoff):
            continue
        if _is_financials_unit_anchor(ln.text):
            unit_anchor_idxs.append(i)

    split_idxs = sorted(set(heading_idxs + unit_anchor_idxs))

    if not split_idxs:
        # No headings detected; return one implicit module.
        blocks = group_lines_into_blocks(ls, gap_tol=block_gap_tol)
        return [
            {
                "name": "__page__",
                "anchor_text": None,
                "bbox": None,
                "blocks": [serialize_block(b) for b in blocks],
            }
        ]

    modules: List[Dict[str, Any]] = []

    # If the first heading is not the first line, prepend an implicit __page_header__ section.
    if split_idxs[0] != 0:
        pre_lines = ls[: split_idxs[0]]
        pre_blocks = group_lines_into_blocks(pre_lines, gap_tol=block_gap_tol)
        modules.append(
            {
                "name": "__page_header__",
                "anchor_text": None,
                "bbox": None,
                "blocks": [serialize_block(b) for b in pre_blocks],
            }
        )

    for pos, s_i in enumerate(split_idxs):
        s_line = ls[s_i]
        s_text = clean_text(s_line.text)
        start = s_i
        end = split_idxs[pos + 1] if pos + 1 < len(split_idxs) else len(ls)
        seg_lines = ls[start:end]
        seg_blocks = group_lines_into_blocks(seg_lines, gap_tol=block_gap_tol)

        if _is_financials_unit_anchor(s_text):
            name = "__financials_table__"
            anchor_text = s_text
        else:
            name = normalize_module_name(s_text) or s_text or "__module__"
            anchor_text = s_text

        modules.append(
            {
                "name": name,
                "anchor_text": anchor_text,
                "bbox": s_line.bbox.to_list(),
                "blocks": [serialize_block(b) for b in seg_blocks],
            }
        )

    return modules

    # (Unreachable dead code removed)


def normalize_module_name(s: str) -> str:
    s = clean_text(s)
    s = s.replace("’", "'")
    # strip trailing ':'
    if s.endswith(":"):
        s = s[:-1].strip()
    # common PDF artifacts
    s = re.sub(r"\s{2,}", " ", s)
    return s


def serialize_block(block: Block) -> Dict[str, Any]:
    kind = classify_block(block)
    payload: Dict[str, Any] = {
        "type": kind,
        "bbox": block.bbox.to_list(),
        "text": block.text,
    }

    if kind == "kv":
        payload["kv_candidates"] = parse_kv_candidates(block)
    elif kind == "table":
        payload["table"] = parse_table_candidates(block)
    elif kind == "heading":
        payload["heading"] = clean_text(block.lines[0].text) if block.lines else None

    # Fallback: dense financial sections often get classified as narrative due to mixed text.
    # Still attempt to extract row-level kv candidates so we don't miss key fields.
    if kind == "narrative":
        kv_fallback = parse_kv_candidates(block)
        if kv_fallback:
            payload["kv_candidates"] = kv_fallback

    return payload

# -----------------------------
# Table merge helpers
# -----------------------------

def _table_year_set(table: Dict[str, Any]) -> set:
    years: set = set()
    for r in table.get("rows", [])[:3]:
        cells = r.get("cells") or []
        for c in cells:
            for t in clean_text(c).split():
                if _RE_YEAR.match(t):
                    years.add(t)
    return years


def _is_label_cell(text: str) -> bool:
    t = clean_text(text)
    if not t:
        return False
    up = t.upper()
    if up in {"NMF", "--"}:
        return False
    if _is_numeric_token(t) or _RE_YEAR.match(t) or _RE_YEAR_RANGE.match(t):
        return False
    return _token_has_alpha(t)


def _split_row_cells_for_label(cells: List[str]) -> Tuple[List[str], Optional[str], List[str]]:
    if not cells:
        return [], None, []

    label_end = None
    for i in range(len(cells) - 1, -1, -1):
        if _is_label_cell(cells[i]):
            label_end = i
            break

    if label_end is None:
        return list(cells), None, []

    label_start = label_end
    while label_start - 1 >= 0 and _is_label_cell(cells[label_start - 1]):
        label_start -= 1

    pre = list(cells[:label_start])
    label = clean_text(" ".join(cells[label_start : label_end + 1]))
    post = list(cells[label_end + 1 :])
    return pre, label, post


def _row_label_key(row: Dict[str, Any], idx: int) -> str:
    cells = row.get("cells") or []
    _, label, _ = _split_row_cells_for_label(cells)
    if label:
        return normalize_label_key(label)
    return f"__idx_{idx}"


def merge_cross_column_year_tables(modules: List[Dict[str, Any]], x_split: float) -> None:
    """Merge left/right tables that are actually one logical year grid split by columns.

    We look for a left-side table and a right-side table whose vertical spans overlap
    strongly and whose year sets are disjoint/adjacent.

    The merged table is appended to the `__right_column__` module's `table_candidates`
    (discovery-only; mapping can later choose it).
    """

    if not modules or not x_split:
        return

    right_mod = next((m for m in modules if m.get("name") == "__right_column__"), None)
    if not right_mod:
        return

    left_tables: List[Dict[str, Any]] = []
    for m in modules:
        if m.get("name") == "__right_column__":
            continue
        for t in (m.get("table_candidates") or []):
            bb = t.get("bbox")
            if isinstance(bb, list) and len(bb) == 4 and float(bb[2]) <= (x_split + 2.0):
                left_tables.append(t)

    right_tables: List[Dict[str, Any]] = []
    for t in (right_mod.get("table_candidates") or []):
        bb = t.get("bbox")
        if isinstance(bb, list) and len(bb) == 4 and float(bb[0]) >= (x_split - 2.0):
            right_tables.append(t)

    def y_overlap(a: List[float], b: List[float]) -> float:
        a_top, a_bot = float(a[1]), float(a[3])
        b_top, b_bot = float(b[1]), float(b[3])
        inter = max(0.0, min(a_bot, b_bot) - max(a_top, b_top))
        union = max(a_bot, b_bot) - min(a_top, b_top)
        return inter / union if union > 0 else 0.0

    merged: List[Dict[str, Any]] = []
    used_right: set = set()

    def label_overlap_count(lt: Dict[str, Any], rt: Dict[str, Any]) -> int:
        lrows = lt.get("rows") or []
        rrows = rt.get("rows") or []
        lkeys = { _row_label_key(r, i) for i, r in enumerate(lrows) }
        rkeys = { _row_label_key(r, i) for i, r in enumerate(rrows) }
        lkeys = {k for k in lkeys if not k.startswith("__idx_")}
        rkeys = {k for k in rkeys if not k.startswith("__idx_")}
        return len(lkeys.intersection(rkeys))

    for lt in left_tables:
        lbb = lt.get("bbox")
        if not (isinstance(lbb, list) and len(lbb) == 4):
            continue
        ly = _table_year_set(lt)
        if len(ly) < 2:
            ly = set()

        best_rt = None
        best_ov = 0.0
        best_score = 0.0
        for r_idx, rt in enumerate(right_tables):
            if r_idx in used_right:
                continue
            rbb = rt.get("bbox")
            if not (isinstance(rbb, list) and len(rbb) == 4):
                continue
            ov = y_overlap(lbb, rbb)
            if ov < 0.45:
                continue
            ry = _table_year_set(rt)
            if len(ry) < 2:
                ry = set()

            label_hits = label_overlap_count(lt, rt)
            years_disjoint = bool(ly and ry and (len(ly.intersection(ry)) <= 1))
            if label_hits < 2 and not years_disjoint:
                continue

            score = (label_hits * 2.0) + (1.0 if years_disjoint else 0.0) + ov
            if score > best_score:
                best_score = score
                best_ov = ov
                best_rt = (r_idx, rt)

        if not best_rt:
            continue

        r_idx, rt = best_rt
        rbb = rt.get("bbox")

        def merge_row_cells(lrow: Dict[str, Any], rrow: Dict[str, Any]) -> Dict[str, Any]:
            lcells = lrow.get("cells") or []
            rcells = rrow.get("cells") or []
            lpre, llabel, lpost = _split_row_cells_for_label(lcells)
            rpre, rlabel, rpost = _split_row_cells_for_label(rcells)
            label = llabel or rlabel
            merged_cells = list(lpre) + list(rpre)
            if label:
                merged_cells.append(label)
            if lpost:
                merged_cells.extend(lpost)
            elif rpost:
                merged_cells.extend(rpost)
            return {"cells": merged_cells, "bbox": lrow.get("bbox") or rrow.get("bbox")}

        lrows = lt.get("rows") or []
        rrows = rt.get("rows") or []
        r_map: Dict[str, Dict[str, Any]] = {}
        for i, row in enumerate(rrows):
            key = _row_label_key(row, i)
            if key not in r_map:
                r_map[key] = row

        rows: List[Dict[str, Any]] = []
        used_keys: set = set()
        for i, lrow in enumerate(lrows):
            key = _row_label_key(lrow, i)
            if key in r_map:
                rows.append(merge_row_cells(lrow, r_map[key]))
                used_keys.add(key)
            else:
                rows.append(lrow)

        for key, rrow in r_map.items():
            if key in used_keys:
                continue
            rows.append(rrow)

        merged_bbox = [
            float(min(lbb[0], rbb[0])),
            float(min(lbb[1], rbb[1])),
            float(max(lbb[2], rbb[2])),
            float(max(lbb[3], rbb[3])),
        ]

        merged.append(
            {
                "bbox": merged_bbox,
                "header": None,
                "header_row_index": None,
                "rows": rows,
                "merged_from": {"left_bbox": lbb, "right_bbox": rbb},
            }
        )
        used_right.add(r_idx)

    if merged:
        right_mod.setdefault("table_candidates", [])
        right_mod["table_candidates"].extend(merged)

def discover_pdf_structure(pdf_path: str) -> Dict[str, Any]:
    """Main entry point: discover modules/blocks/fields in a PDF."""

    import pdfplumber

    pages_words = extract_words(pdf_path)

    result: Dict[str, Any] = {
        "pdf": os.path.basename(pdf_path),
        "pages": [],
    }

    with pdfplumber.open(pdf_path) as pdf:
        for page_idx, page in enumerate(pdf.pages):
            words = pages_words[page_idx] if page_idx < len(pages_words) else []

            # Split into left/right columns (Value Line is typically 2-column below the header).
            left_words, right_words, x_split = split_words_into_columns(words, page_width=float(page.width))

            left_lines = group_words_into_lines(left_words, y_tol=2.0)
            modules = assign_lines_to_modules(
                left_lines,
                page_width=float(page.width),
                page_height=float(page.height),
                top_header_cutoff=0.12,
                block_gap_tol=4.0,
            )

            # Keep right column as a separate module; it often contains narrative + some structured tables.
            if right_words:
                right_lines = group_words_into_lines(right_words, y_tol=2.0)
                right_blocks = group_lines_into_blocks(right_lines, gap_tol=4.0)
                modules.append(
                    {
                        "name": "__right_column__",
                        "anchor_text": None,
                        "bbox": None,
                        "blocks": [serialize_block(b) for b in right_blocks],
                    }
                )

            # For each module, add a flattened list of candidate fields
            for m in modules:
                fields: List[Dict[str, Any]] = []
                tables: List[Dict[str, Any]] = []
                for b in m.get("blocks", []):
                    if b.get("type") == "kv":
                        fields.extend(b.get("kv_candidates", []))
                    # Also accept fallback kv candidates from narrative blocks.
                    if b.get("type") == "narrative" and b.get("kv_candidates"):
                        fields.extend(b.get("kv_candidates", []))
                    if b.get("type") == "table":
                        t = b.get("table")
                        if t:
                            tables.extend(split_table_on_year_row(t))

                m["field_candidates"] = fields
                m["table_candidates"] = tables

            # Best-effort: merge year-grid tables that are split across left/right columns.
            if x_split is not None:
                merge_cross_column_year_tables(modules, float(x_split))

            result["pages"].append(
                {
                    "page": page_idx + 1,
                    "width": float(page.width),
                    "height": float(page.height),
                    "modules": modules,
                }
            )

    return result


# -----------------------------
# CLI
# -----------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Discover modules/fields from a PDF (open-world).")
    p.add_argument("--pdf", required=True, help="Path to PDF")
    p.add_argument("--out", required=False, help="Output JSON path. If omitted, prints to stdout.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    p.add_argument("--log", default="INFO", help="Log level (DEBUG/INFO/WARN/ERROR)")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(level=getattr(logging, str(args.log).upper(), logging.INFO))

    pdf_path = args.pdf
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(pdf_path)

    data = discover_pdf_structure(pdf_path)

    indent = 2 if args.pretty else None
    out_json = json.dumps(data, ensure_ascii=False, indent=indent)

    if args.out:
        os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_json)
        logger.info("Wrote %s", args.out)
    else:
        print(out_json)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
