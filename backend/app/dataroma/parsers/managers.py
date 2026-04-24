"""Parse Dataroma managers.php HTML → superinvestor whitelist.

Each row in the managers table has:
  - Manager name (link text)
  - dataroma_code extracted from href  e.g. holdings.php?m=BRK → 'BRK'
"""
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Optional


@dataclass
class DataromaManager:
    name: str
    dataroma_code: str


_HREF_CODE_RE = re.compile(r"[?&]m=([A-Za-z0-9_\-]+)", re.IGNORECASE)


class _ManagerParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.managers: list[DataromaManager] = []
        self._in_link = False
        self._current_code: Optional[str] = None
        self._current_name_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return
        attr_dict = dict(attrs)
        href = attr_dict.get("href", "") or ""
        m = _HREF_CODE_RE.search(href)
        if m:
            self._in_link = True
            self._current_code = m.group(1).upper()
            self._current_name_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_link:
            name = " ".join(self._current_name_parts).strip()
            if name and self._current_code:
                self.managers.append(
                    DataromaManager(name=name, dataroma_code=self._current_code)
                )
            self._in_link = False
            self._current_code = None

    def handle_data(self, data: str) -> None:
        if self._in_link:
            self._current_name_parts.append(data)


def parse_managers(html: bytes) -> list[DataromaManager]:
    """Parse managers.php HTML and return list of DataromaManager."""
    text = html.decode("utf-8", errors="replace")
    parser = _ManagerParser()
    parser.feed(text)

    # Deduplicate by dataroma_code (keep first occurrence)
    seen: set[str] = set()
    result: list[DataromaManager] = []
    for mgr in parser.managers:
        if mgr.dataroma_code not in seen:
            seen.add(mgr.dataroma_code)
            result.append(mgr)
    return result
