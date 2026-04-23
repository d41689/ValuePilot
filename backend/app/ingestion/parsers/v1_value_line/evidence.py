import re
from typing import Any, Optional


def parse_rating_event_notes(notes: Optional[str]) -> Optional[dict[str, Any]]:
    if not notes:
        return None
    match = re.search(r"(Lowered|Raised|New)\s*(\d{1,2}/\d{1,2}/\d{2})", notes, re.IGNORECASE)
    if not match:
        return None
    iso = _iso_from_mdy(match.group(2))
    return {
        "type": match.group(1).lower(),
        "date": iso,
        "raw": notes,
    }


def _iso_from_mdy(value: str) -> Optional[str]:
    match = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2})", value.strip())
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    year = 2000 + int(match.group(3))
    return f"{year:04d}-{month:02d}-{day:02d}"
