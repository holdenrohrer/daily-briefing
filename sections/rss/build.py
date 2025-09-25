from __future__ import annotations

import calendar
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List
from .pluralistic import is_pluralistic_host, extract_content_and_toc
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import feedparser  # type: ignore

from tools.cache import read_cache, write_cache, make_key


def _slugify(s: str) -> str:
    s = unescape(s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        s = ts.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


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


def _format_published_for_subtitle(published_iso: str) -> str:
    """
    Format an ISO8601 timestamp into a friendly subtitle string.
    Example: "Published 24 June 2027 3pm".
    If parsing fails, uses current UTC time.
    """
    dt = _parse_iso(published_iso)
    if dt is None:
        dt = datetime.now(timezone.utc)
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
        { title, link, source, source_slug, source_host, slug, published (ISO8601 UTC), summary },
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
    - If 'since' is provided, only include items with published >= since (UTC).
      The response meta will include 'cutoff_iso' and 'official'.
    """
    ttl = int(ttl_s if ttl_s is not None else int(os.getenv("RSS_TTL", "1800")))

    all_items: List[Dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    for url in feeds:
        key = make_key(url)
        cached, _meta = read_cache("rss", key, ttl)
        if cached is not None:
            items = cached
            cache_hits += 1
        else:
            cache_misses += 1
            items = []
            try:
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
                            ).isoformat()
                        elif entry.get("updated_parsed"):
                            published = datetime.fromtimestamp(
                                calendar.timegm(entry["updated_parsed"]),
                                tz=timezone.utc,
                            ).isoformat()
                        else:
                            published = _safe_iso(entry.get("published") or entry.get("updated") or "")
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

                # Write successful fetch to cache
                write_cache("rss", key, items, ttl)
            except (HTTPError, URLError) as e:
                host = urlparse(url).netloc
                items.append(
                    {
                        "title": "Error fetching feed",
                        "link": url,
                        "source": host,
                        "source_slug": _slugify(host),
                        "source_host": host,
                        "slug": "error-fetching-feed",
                        "published": _iso_now(),
                        "summary": f"{e.__class__.__name__}: {e.reason if hasattr(e, 'reason') else str(e)}",
                    }
                )
            except ET.ParseError as e:
                host = urlparse(url).netloc
                items.append(
                    {
                        "title": "Error parsing feed XML",
                        "link": url,
                        "source": host,
                        "source_slug": _slugify(host),
                        "source_host": host,
                        "slug": "error-parsing-feed",
                        "published": _iso_now(),
                        "summary": str(e),
                    }
                )
            except Exception as e:
                host = urlparse(url).netloc
                items.append(
                    {
                        "title": "Unexpected error fetching feed",
                        "link": url,
                        "source": host,
                        "source_slug": _slugify(host),
                        "source_host": host,
                        "slug": "unexpected-error",
                        "published": _iso_now(),
                        "summary": str(e),
                    }
                )
        # Apply 'since' filtering and enforce per-feed limit after filtering
        if since is not None:
            filtered_items: List[Dict[str, Any]] = []
            for it in items:
                pub_dt = _parse_iso(str(it.get("published") or ""))
                if pub_dt is not None and pub_dt >= since:
                    filtered_items.append(it)
            items = filtered_items

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
        meta["cutoff_iso"] = since.isoformat()
    if official:
        meta["official"] = True

    return {
        "title": "RSS Highlights",
        "items": all_items,
        "groups": groups,
        "meta": meta,
    }
