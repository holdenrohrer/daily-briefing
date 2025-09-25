from __future__ import annotations

from typing import Any, List, Tuple
from html.parser import HTMLParser

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:  # pragma: no cover
    BeautifulSoup = None  # type: ignore


def is_pluralistic_host(host: str | None) -> bool:
    return isinstance(host, str) and "pluralistic.net" in host


def _get_entry_content_html(entry: dict[str, Any]) -> str | None:
    """
    Try to extract the main HTML content from a feedparser entry.
    Prefer entry.content[0].value; fall back to summary_detail.value; else None.
    """
    try:
        content_list = entry.get("content") or []
        if isinstance(content_list, list) and content_list:
            first = content_list[0] or {}
            val = first.get("value")
            if isinstance(val, str) and val.strip():
                return val
    except Exception:
        pass

    try:
        sd = entry.get("summary_detail") or {}
        val = sd.get("value")
        if isinstance(val, str) and val.strip():
            return val
    except Exception:
        pass

    return None


class _PluralisticTocParser(HTMLParser):
    """
    Fallback HTML parser when BeautifulSoup is not available.
    Extracts text from:
      <ul class="toc"> <li class="xToc"> ... </li> ... </ul>
    Case-insensitive on class tokens.
    """
    def __init__(self) -> None:
        super().__init__()
        self.in_toc_ul = False
        self.capture_li = False
        self.current: list[str] = []
        self.items: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        attrs_dict = {k.lower(): (v or "") for k, v in attrs}
        cls_vals = " ".join(str(attrs_dict.get("class", ""))).strip().lower()
        classes = set(cls_vals.split()) if cls_vals else set()
        if t == "ul" and "toc" in classes:
            self.in_toc_ul = True
        elif self.in_toc_ul and t == "li":
            if "xtoc" in classes:
                self.capture_li = True
                self.current = []

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "ul" and self.in_toc_ul:
            self.in_toc_ul = False
        elif t == "li" and self.capture_li:
            text = " ".join("".join(self.current).split())
            if text:
                self.items.append(text)
            self.capture_li = False
            self.current = []

    def handle_data(self, data: str) -> None:
        if self.capture_li and data:
            self.current.append(data)


def _extract_toc_with_bs4(content_html: str) -> List[str]:
    if not BeautifulSoup:
        return []
    try:
        soup = BeautifulSoup(content_html, "html.parser")
        toc_ul = None
        for ul in soup.find_all("ul"):
            classes = [c.lower() for c in (ul.get("class") or [])]
            if "toc" in classes:
                toc_ul = ul
                break
        if not toc_ul:
            return []
        items: List[str] = []
        for li in toc_ul.find_all("li"):
            classes = [c.lower() for c in (li.get("class") or [])]
            if "xtoc" in classes:
                text = li.get_text(" ", strip=True)
                text = " ".join((text or "").split())
                if text:
                    items.append(text)
        return items
    except Exception:
        return []


def extract_content_and_toc(entry: dict[str, Any]) -> Tuple[str | None, List[str]]:
    """
    Extract full content HTML and a list of ToC items for pluralistic.net entries.
    - content: raw HTML (string) if found, else None
    - toc: list[str] of items from <ul class="toc"><li class="xToc">…</li>…</ul> with tags stripped
    """
    content_html = _get_entry_content_html(entry)
    toc_items: List[str] = []

    if content_html:
        # Prefer BeautifulSoup if available; fall back to a lightweight HTMLParser
        toc_items = _extract_toc_with_bs4(content_html)
        if not toc_items:
            parser = _PluralisticTocParser()
            parser.feed(content_html or "")
            parser.close()
            toc_items = parser.items

    return content_html, toc_items
