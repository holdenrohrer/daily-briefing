from __future__ import annotations

import calendar
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import feedparser  # type: ignore

from tools import cache
from tools.util import escape_sile
from .pluralistic import is_pluralistic_host, extract_content_and_toc


def _slugify(s: str) -> str:
    s = unescape(s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"




def _ensure_local(dt: datetime | None) -> datetime | None:
    """
    Ensure a timezone-aware datetime in the local timezone.
    - If dt is None, returns None.
    - If dt is naive, it is assumed to be in UTC, then converted to local time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _safe_datetime(date_str: str) -> datetime:
    """
    Parse a date string into a timezone-aware datetime in the local timezone.

    Accepts ISO-8601/RFC 3339 and RFC 2822 formats.
    Raises ValueError if the input is empty or cannot be parsed.
    """
    s = (date_str or "").strip()
    if not s:
        raise ValueError("date_str must be a non-empty string")
    # Try ISO-8601 / RFC 3339 first
    try:
        iso = s[:-1] + "+00:00" if s.endswith("Z") else s
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone()
    except Exception:
        pass
    # Fallback to RFC 2822 parsing
    dt = parsedate_to_datetime(s)
    if dt is None:
        raise ValueError(f"Unparseable date string: {s!r}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def _truncate_words(s: str, limit: int) -> str:
    """
    Truncate a string to the first 'limit' words, collapsing whitespace.
    """
    if limit <= 0:
        return s.strip()
    words = re.findall(r"\S+", s)
    if len(words) <= limit:
        return " ".join(words)
    return " ".join(words[:limit]) + "…"


def _format_published_for_subtitle(published_dt: datetime | None) -> str:
    """
    Format a datetime into a friendly subtitle string in local time.
    Example: "Published 24 June 2027 3pm".
    If None is provided, uses current local time.
    """
    dt = _ensure_local(published_dt) or datetime.now().astimezone()
    hour = dt.hour
    hour12 = hour % 12 or 12
    ampm = "am" if hour < 12 else "pm"
    return f"Published {dt.day} {dt.strftime('%B')} {dt.year} {hour12}{ampm}"


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


def fetch_rss(
    feeds: List[str] | None = None,
    per_feed_limit: int = 5,
    total_limit: int = 10,
    ttl_s: int | None = None,
    since: datetime | None = None,
    official: bool = False,
) -> Dict[str, Any]:
    """
    Fetch and normalize RSS/Atom feeds into a structure:
    {
      "items": [
        { title, link, source, source_slug, source_host, slug, published (datetime, local tz), summary },
        ...
      ],
      "groups": {
        <source_slug>: { "source": str, "source_slug": str, "items": [ ... ] },
        ...
      },
      "meta": { "cache_hits": int, "cache_misses": int, "ttl_s": int, "sources": int }
    }
    Uses a simple file cache under data/.cache/rss with TTL to avoid repeated network calls.

    Notes:
    - Uses 'feedparser' to parse feeds.
    - If 'feeds' is None or empty, defaults are taken from $RSS_FEEDS (comma-separated)
      or a built-in set of popular feeds.
    - If 'since' is provided, only include items with published >= since (both must be timezone-aware).
      The response meta will include 'cutoff' and 'official'.
    """
    ttl = int(ttl_s if ttl_s is not None else int(os.getenv("RSS_TTL", "1800")))

    all_items: List[Dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    for url in feeds:
        def fetch_and_parse_feed():
            items = []
            raw = _fetch_url(url, timeout=10.0)
            parsed_items: List[Dict[str, Any]] = []

            d = feedparser.parse(raw)
            source_host = urlparse(url).netloc
            source_title = (getattr(d, "feed", {}) or {}).get("title") or source_host
            source_slug = _slugify(source_title or source_host)
            is_pluralistic = is_pluralistic_host(source_host)
            entries = list(getattr(d, "entries", []) or [])
            if entries:
                for entry in entries:
                    title = unescape((entry.get("title") or "(untitled)")).strip()
                    link = entry.get("link") or entry.get("id") or url
                    if entry.get("published_parsed"):
                        published = datetime.fromtimestamp(
                            calendar.timegm(entry["published_parsed"]),
                            tz=timezone.utc,
                        ).astimezone()
                    elif entry.get("updated_parsed"):
                        published = datetime.fromtimestamp(
                            calendar.timegm(entry["updated_parsed"]),
                            tz=timezone.utc,
                        ).astimezone()
                    else:
                        published = _safe_datetime(entry.get("published") or entry.get("updated") or "")
                    assert isinstance(published, datetime) and published.tzinfo is not None, "published must be a timezone-aware datetime"
                    summary_raw = unescape(entry.get("summary") or entry.get("description") or "")
                    # Strip simple HTML tags and collapse whitespace before truncation
                    summary_text = re.sub(r"<[^>]+>", " ", summary_raw)
                    summary_text = re.sub(r"\s+", " ", summary_text).strip()
                    summary = _truncate_words(summary_text, 100)

                    # Build subtitles list:
                    # - For pluralistic: use ToC items (if any)
                    # - For others: use the truncated summary
                    # In all cases, append a friendly published timestamp.
                    published_note = _format_published_for_subtitle(published)
                    subtitles: List[str] = []
                    content_html = None
                    toc_items: List[str] = []
                    if is_pluralistic:
                        content_html, toc_items = extract_content_and_toc(entry)
                        subtitles = list(toc_items) if toc_items else []
                    else:
                        if summary:
                            subtitles = [summary]
                    subtitles.append(published_note)

                    item = {
                        "title": title or "(untitled)",
                        "link": link,
                        "source": source_title,
                        "source_slug": source_slug,
                        "source_host": source_host,
                        "slug": _slugify(title),
                        "published": published,
                        "summary": summary,
                        "subtitles": subtitles,
                    }
                    if content_html:
                        item["content"] = content_html
                    if toc_items:
                        item["toc"] = toc_items
                    parsed_items.append(item)

            items = parsed_items
            return items

        items = cache.get(f"rss:{url}", fetch_and_parse_feed, ttl)
        # Apply 'since' filtering (timezone-aware comparison)
        if since is not None:
            assert isinstance(since, datetime), "since must be a datetime"
            assert since.tzinfo is not None, "since must be timezone-aware"
            items = [
                it for it in items
                if isinstance(it.get("published"), datetime)
                and it["published"].tzinfo is not None
                and it["published"] >= since
            ]

        all_items.extend(items)


    # Group by source (non-breaking addition for consumers that only read "items")
    groups: Dict[str, Dict[str, Any]] = {}
    for it in all_items:
        src = str(it.get("source") or "")
        host = str(it.get("source_host") or urlparse(it.get("link", "")).netloc)
        sslug = str(it.get("source_slug") or _slugify(src or host))
        grp = groups.setdefault(sslug, {"source": src or host, "source_slug": sslug, "items": []})
        grp["items"].append(it)

    meta: Dict[str, Any] = {
        "cache_hits": cache_hits,
        "cache_misses": cache_misses,
        "ttl_s": ttl,
        "sources": len(groups),
    }
    if since is not None:
        assert isinstance(since, datetime), "since must be a datetime"
        assert since.tzinfo is not None, "since must be timezone-aware"
        meta["cutoff"] = since
    if official:
        meta["official"] = True

    return {
        "title": "RSS Highlights",
        "items": all_items,
        "groups": groups,
        "meta": meta,
    }


def generate_sil(
    since: datetime | None = None,
    official: bool = False,
    **kwargs
) -> str:
    """
    Generate SILE code directly for the RSS section.
    Gets feeds from config.py, only needs build-time args.
    """
    from tools import config
    data = fetch_rss(feeds=config.RSS_FEEDS, since=since, official=official)
    items = data.get("items", [])

    def _render_item_group(source: str, group_items: List[Dict[str, Any]]) -> str:
        """Render a group of items from the same source."""
        lines = [f"    \\sectiontitle{{{escape_sile(source)}}}"]

        for item in group_items:
            title = escape_sile(str(item.get("title", "(untitled)")))
            lines.append(f"    \\rssItemTitle{{{title}}}\\cr")

            for subtitle in item.get("subtitles", []):
                if subtitle:
                    escaped_subtitle = escape_sile(str(subtitle))
                    lines.append(f" \\rssSubtitle{{{escaped_subtitle}}}\\cr")

            lines.append("    \\rssItemSeparator")

        return "\n".join(lines)

    # Group items by source while preserving order
    grouped_items = groupby(items, key=lambda x: str(x.get("source", "Blog")))

    item_groups = [
        _render_item_group(source, list(group_items))
        for source, group_items in grouped_items
    ]

    content = "\n  }\n  \\sectionbox{\n".join(item_groups)

    return f"""\\define[command=rsssection]{{
  \\sectionbox{{
    {content}
  }}
}}"""
