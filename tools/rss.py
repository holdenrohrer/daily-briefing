from __future__ import annotations

import calendar
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Dict, List
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

try:
    import feedparser  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    feedparser = None  # type: ignore

from tools.cache import read_cache, write_cache, make_key


def _default_feeds() -> List[str]:
    feeds_env = os.getenv("RSS_FEEDS", "")
    if feeds_env.strip():
        feeds = [s.strip() for s in feeds_env.split(",") if s.strip()]
        if feeds:
            return feeds
    return [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://pluralistic.net/feed/",
        "https://astralcodexten.substack.com/feed",
        "https://thezvi.substack.com/feed",
    ]


def _slugify(s: str) -> str:
    s = unescape(s or "").lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


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
    source_host = urlparse(feed_url).netloc
    source_slug = _slugify(source_title or source_host)
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
                "source_slug": source_slug,
                "source_host": source_host,
                "slug": _slugify(title),
                "published": _safe_iso(pub),
                "summary": unescape(desc or ""),
            }
        )
    return source_title, items


def _parse_atom(root: ET.Element, feed_url: str) -> tuple[str, List[Dict[str, Any]]]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    title_el = root.find("atom:title", ns)
    source_title = (title_el.text or "").strip() if title_el is not None and title_el.text else urlparse(feed_url).netloc
    source_host = urlparse(feed_url).netloc
    source_slug = _slugify(source_title or source_host)
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
                "source_slug": source_slug,
                "source_host": source_host,
                "slug": _slugify(title),
                "published": _safe_iso(pub),
                "summary": unescape(summary),
            }
        )
    return source_title, items


def fetch_rss(
    feeds: List[str] | None = None,
    per_feed_limit: int = 5,
    total_limit: int = 10,
    ttl_s: int | None = None,
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
    - If the optional 'feedparser' module is available, it will be used to parse feeds.
      Otherwise, a minimal XML parser fallback is used.
    - If 'feeds' is None or empty, defaults are taken from $RSS_FEEDS (comma-separated)
      or a built-in set of popular feeds.
    """
    ttl = int(ttl_s if ttl_s is not None else int(os.getenv("RSS_TTL", "1800")))
    feeds = feeds or _default_feeds()

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

                if feedparser is not None:
                    d = feedparser.parse(raw)
                    source_host = urlparse(url).netloc
                    source_title = (getattr(d, "feed", {}) or {}).get("title") or source_host
                    source_slug = _slugify(source_title or source_host)
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
                            summary = unescape(entry.get("summary") or entry.get("description") or "")
                            parsed_items.append(
                                {
                                    "title": title or "(untitled)",
                                    "link": link,
                                    "source": source_title,
                                    "source_slug": source_slug,
                                    "source_host": source_host,
                                    "slug": _slugify(title),
                                    "published": published,
                                    "summary": summary,
                                }
                            )

                if not parsed_items:
                    # Fallback to minimal XML parsing
                    root = ET.fromstring(raw)
                    tag = root.tag.lower()
                    if tag.endswith("rss") or root.find("channel") is not None:
                        _, parsed_items = _parse_rss(root, url)
                    else:
                        _, parsed_items = _parse_atom(root, url)

                items = parsed_items
                if per_feed_limit and per_feed_limit > 0:
                    items = items[:per_feed_limit]

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
        all_items.extend(items)

    if total_limit and total_limit > 0:
        all_items = all_items[:total_limit]

    # Group by source (non-breaking addition for consumers that only read "items")
    groups: Dict[str, Dict[str, Any]] = {}
    for it in all_items:
        src = str(it.get("source") or "")
        host = str(it.get("source_host") or urlparse(it.get("link", "")).netloc)
        sslug = str(it.get("source_slug") or _slugify(src or host))
        grp = groups.setdefault(sslug, {"source": src or host, "source_slug": sslug, "items": []})
        grp["items"].append(it)

    return {
        "items": all_items,
        "groups": groups,
        "meta": {
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "ttl_s": ttl,
            "sources": len(groups),
        },
    }
