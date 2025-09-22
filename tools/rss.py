from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_iso(date_str: str) -> str:
    if not date_str:
        return _iso_now()
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        # Fall back to current time if parsing fails
        return _iso_now()


def _fetch_url(url: str, timeout: float = 10.0) -> bytes:
    req = Request(url, headers={"User-Agent": "daily-briefing/0.1 (+https://example.local)"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _text(el: ET.Element | None, tag: str) -> str:
    if el is None:
        return ""
    child = el.find(tag)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def _parse_rss(root: ET.Element, feed_url: str) -> tuple[str, List[Dict[str, Any]]]:
    channel = root.find("channel")
    source_title = _text(channel, "title") if channel is not None else urlparse(feed_url).netloc
    items: List[Dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = _text(item, "title") or "(untitled)"
        link = _text(item, "link") or feed_url
        pub = _text(item, "pubDate")
        desc = _text(item, "description")
        items.append(
            {
                "title": unescape(title),
                "link": link,
                "source": source_title,
                "published": _safe_iso(pub),
                "summary": unescape(desc or ""),
            }
        )
    return source_title, items


def _parse_atom(root: ET.Element, feed_url: str) -> tuple[str, List[Dict[str, Any]]]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_el = root.find("atom:title", ns)
    source_title = (title_el.text or "").strip() if title_el is not None and title_el.text else urlparse(feed_url).netloc
    items: List[Dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        etitle = entry.find("atom:title", ns)
        title = (etitle.text or "").strip() if etitle is not None and etitle.text else "(untitled)"
        link = feed_url
        for l in entry.findall("atom:link", ns):
            rel = l.get("rel", "alternate")
            href = l.get("href")
            if rel == "alternate" and href:
                link = href
                break
            if href:
                link = href
        published = entry.find("atom:published", ns)
        updated = entry.find("atom:updated", ns)
        pub = (published.text or "").strip() if published is not None and published.text else (
            (updated.text or "").strip() if updated is not None and updated.text else ""
        )
        summary_el = entry.find("atom:summary", ns) or entry.find("atom:content", ns)
        summary = (summary_el.text or "").strip() if summary_el is not None and summary_el.text else ""
        items.append(
            {
                "title": unescape(title),
                "link": link,
                "source": source_title,
                "published": _safe_iso(pub),
                "summary": unescape(summary),
            }
        )
    return source_title, items


def fetch_rss(feeds: List[str], per_feed_limit: int = 5, total_limit: int = 10) -> List[Dict[str, Any]]:
    """
    Fetch and normalize RSS/Atom feeds into a list of items:
    { title, link, source, published (ISO8601 UTC), summary }
    """
    all_items: List[Dict[str, Any]] = []
    for url in feeds or []:
        try:
            raw = _fetch_url(url, timeout=10.0)
            root = ET.fromstring(raw)
            tag = root.tag.lower()
            if tag.endswith("rss") or root.find("channel") is not None:
                _, items = _parse_rss(root, url)
            else:
                _, items = _parse_atom(root, url)
            if per_feed_limit and per_feed_limit > 0:
                items = items[:per_feed_limit]
            all_items.extend(items)
        except (HTTPError, URLError) as e:
            all_items.append(
                {
                    "title": f"Error fetching feed",
                    "link": url,
                    "source": urlparse(url).netloc,
                    "published": _iso_now(),
                    "summary": f"{e.__class__.__name__}: {e.reason if hasattr(e, 'reason') else str(e)}",
                }
            )
        except ET.ParseError as e:
            all_items.append(
                {
                    "title": "Error parsing feed XML",
                    "link": url,
                    "source": urlparse(url).netloc,
                    "published": _iso_now(),
                    "summary": str(e),
                }
            )
        except Exception as e:
            all_items.append(
                {
                    "title": "Unexpected error fetching feed",
                    "link": url,
                    "source": urlparse(url).netloc,
                    "published": _iso_now(),
                    "summary": str(e),
                }
            )
    if total_limit and total_limit > 0:
        return all_items[:total_limit]
    return all_items
