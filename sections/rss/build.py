from __future__ import annotations

import calendar
import os
import re
import sys
from datetime import datetime, timezone
from html import unescape
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import feedparser  # type: ignore
from dateutil import parser as dateutil_parser

from tools import cache
from tools.util import escape_sile
import tools.lm_filter as lm_filter
import asyncio


def _ensure_local_timezone(dt: datetime | None) -> datetime | None:
    """Convert datetime to timezone-aware local time. Assumes UTC if naive."""
    if dt is None:
        return None
    return dt.astimezone()


def _safe_datetime(date_input: str | datetime) -> datetime:
    """Parse date string or datetime to timezone-aware datetime in local timezone."""
    if isinstance(date_input, datetime):
        return _ensure_local_timezone(date_input)

    if not (date_input or "").strip():
        raise ValueError("date_input must be a non-empty string or datetime")

    dt = dateutil_parser.parse(date_input)
    return _ensure_local_timezone(dt)


def _fetch_url(url: str, timeout: float = 10.0) -> bytes:
    req = Request(url, headers={"User-Agent": "daily-briefing/0.1 (+https://example.local)"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


async def fetch_rss(
    feeds: List[str | Dict[str, Any]] | None = None,
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

    all_items: List[Dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    async def fetch_and_parse_feed(feed_config):
        if isinstance(feed_config, str):
            url = feed_config
            parser_func = lm_filter.default_rss
        else:
            url = feed_config.get('url')
            parser_func = feed_config.get('parser')

        try:
            d = cache.get(f'rss:url:{url}',
                          lambda: feedparser.parse(_fetch_url(url)),
                          ttl=ttl_s)

            source_host = urlparse(url).netloc
            source_title = d['feed']['title']
            entries = d["entries"]

            async def entry_parse(entry):
                title = unescape((entry.get("title") or "(untitled)")).strip()
                link = entry.get("link")

                # Parse published date
                if entry.get("published_parsed"):
                    published = _ensure_local_timezone(
                        datetime.fromtimestamp(calendar.timegm(entry["published_parsed"]), tz=timezone.utc)
                    )
                elif entry.get("updated_parsed"):
                    published = _ensure_local_timezone(
                        datetime.fromtimestamp(calendar.timegm(entry["updated_parsed"]), tz=timezone.utc)
                    )
                else:
                    published = _safe_datetime(entry.get("published") or entry.get("updated") or "")

                assert isinstance(published, datetime) and published.tzinfo is not None

                if since is not None:
                    if published < since:
                        return

                # Store item with metadata (no parser_func to avoid JSON serialization issues)
                item = {
                    "title": title,
                    "link": link,
                    "source": source_title,
                    "published": _safe_datetime(published),
                    "description": entry.get("description", '') or entry.get('summary', ''),
                    "summary": entry.get('summary', ''),
                    "content": entry.get("content", ''),
                }
                item['summary'] = title
                item['summary'] = await parser_func(item)
                return item

            out = await asyncio.gather(*[entry_parse(entry) for entry in entries])
            return {'title': source_title, 'items': [it for it in out if it is not None]}

        except Exception as e:
            import traceback
            print(f"Failed to fetch RSS feed {url}:")
            if not isinstance(e, HTTPError):
                traceback.print_exc()
            return {'title': url,
                    'items': [{
                        "title": f"Feed failed to parse: {urlparse(url).netloc}",
                        "slug": "feed-parse-error",
                        "summary": f"Error fetching feed: {str(e)}",
                    }]}

    sections = await asyncio.gather(*[fetch_and_parse_feed(feed_config) for feed_config in feeds])
    sections = [section for section in sections if len(section['items']) > 0]
    return sections


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
    sections = asyncio.run(fetch_rss(feeds=config.RSS_FEEDS, since=since, official=official, ttl_s=config.RSS_FEED_TTL_S))

    def _render_section(section) -> str:
        """Render a group of items from the same source."""
        title = section['title']
        lines = ["\\sectionbox{", f"\\sectiontitle{{{escape_sile(title)}}}"]

        for item in section['items']:
            lines.append(item['summary'])
            lines.append("\\par")

        lines.append("}")
        return "\n".join(lines)

    rendered = map(_render_section, sections)
    content = "\n".join(rendered)

    return f"""\\define[command=rsssection]{{
{content}
}}"""
