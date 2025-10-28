from __future__ import annotations

import calendar
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import unescape
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import feedparser  # type: ignore
import requests
from litellm import completion  # type: ignore

from tools import cache
from tools import config
from tools.util import escape_sile


class ComicExtraction(TypedDict):
    """
    Structured result for a webcomic extraction.

    Keys:
    - url: Source URL (non-empty).
    - title_text: The comic's title or header text (may be empty if unavailable).
    - images: Ordered list of image URLs (0 or more).
    - extra_text: Any extra descriptive text blocks (0 or more).
    - hidden_image: Optional "hidden" second comic image (SMBC often has one).

    Fails fast inside extraction helpers; callers should catch exceptions per-item.
    """
    url: str
    title_text: str
    images: List[str]
    extra_text: List[str]
    hidden_image: Optional[str]


def _slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = unescape(s)
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
        from email.utils import parsedate_to_datetime

        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return _iso_now()


def _condense_html(html: str, max_chars: int = 50000) -> str:
    """
    Collapse whitespace to reduce token usage, then truncate.
    Raises AssertionError if html is empty after cleaning.
    """
    cleaned = re.sub(r"\s+", " ", html or "").strip()
    assert cleaned != "", "Empty HTML provided to _condense_html()"
    return cleaned[:max_chars]


def fetch_html(url: str, timeout: float = 15.0) -> str:
    """
    Fetch a URL and return its HTML as text.
    - Requires http/https URL.
    - Raises exceptions from requests on network or status errors.
    """
    assert isinstance(url, str) and url.startswith(("http://", "https://")), "URL must be http(s)"
    headers = {"User-Agent": "daily-briefing/comics/0.1 (+https://example.local)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    assert isinstance(text, str) and text != "", "Fetched empty response body"
    return text


def _llm_extract_comic(url: str, html: str, model: Optional[str] = None) -> ComicExtraction:
    """
    Use a small, inexpensive model via OpenRouter (through LiteLLM) to extract
    webcomic structure from HTML.

    Requirements:
    - config.OPENROUTER_API_TOKEN must be a non-empty string.
    - html must be non-empty.

    Fails fast with AssertionError on invalid inputs or missing config.
    """
    assert isinstance(url, str) and url != "", "url must be a non-empty str"
    assert isinstance(html, str) and html != "", "html must be a non-empty str"
    token = getattr(config, "OPENROUTER_API_TOKEN", "")
    assert isinstance(token, str) and token.strip() != "", (
        "OPENROUTER_API_TOKEN must be set in tools/config.py"
    )

    cheap_model = model or getattr(config, "LLM", "openrouter/qwen/qwen3-8b")

    system_prompt = (
        "You are a precise webcomic extraction assistant. Parse the provided HTML for a webcomic page "
        "and return a STRICT JSON object with the following keys:\n"
        '  - "title_text": string (comic title/header; empty if not found)\n'
        '  - "images": array of strings (absolute image URLs in reading order, excluding hidden_image)\n'
        '  - "extra_text": array of strings (short descriptive text blocks, in order)\n'
        '  - "hidden_image": string or null (SMBC often includes a second hidden comic)\n'
        "Rules:\n"
        "- Only include the main text content specific to this comic. Do not include text which is on every comic page.\n"
        "- Do NOT include transcript. Do NOT include alt-text.\n"
        "- ALWAYS include mouseover text. ALWAYS include explanation text.\n"
        "- Include multiple images if the comic has panels split across <img> tags.\n"
        "- If unsure about a hidden second comic, set hidden_image to null.\n"
        "- Output ONLY valid JSON. No markdown fences, no prose.\n"
        "- VERY IMPORTANT: INCLUDE NO TEXT EXCEPT JSON. YOUR RESPONSE WILL FAIL TO PARSE IF IT IS NOT A VALID JSON OBJECT"
    )

    condensed = _condense_html(html)
    user_prompt = f"URL: {url}\nHTML:\n{condensed}"

    resp = completion(
        model=cheap_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        api_base="https://openrouter.ai/api/v1",
        api_key=token,
        temperature=0,
        max_tokens=800,
        extra_headers={
            "X-Title": "Comics Extractor",
            "X-OpenRouter-Zero-Data-Retention": "true",
        },
        num_retries=5,
    )

    try:
        content = resp["choices"][0]["message"]["content"]  # type: ignore[index]
    except Exception as e:
        raise RuntimeError(f"Unexpected LLM response structure: {type(resp)}; error: {e}")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\n---\n{content}")

    if not isinstance(parsed, dict):
        raise TypeError("Parsed LLM output is not a JSON object")

    title_text = str(parsed.get("title_text") or "")
    images = parsed.get("images") or []
    extra_text = parsed.get("extra_text") or []
    hidden_image = parsed.get("hidden_image", None)

    if not isinstance(images, list) or any(not isinstance(u, str) for u in images):
        raise TypeError('"images" must be a list of strings')
    if not isinstance(extra_text, list) or any(not isinstance(t, str) for t in extra_text):
        raise TypeError('"extra_text" must be a list of strings')
    if hidden_image is not None and not isinstance(hidden_image, str):
        raise TypeError('"hidden_image" must be a string or null')

    result: ComicExtraction = {
        "url": url,
        "title_text": title_text,
        "images": list(images),
        "extra_text": list(extra_text),
        "hidden_image": hidden_image if hidden_image is not None else None,
    }
    return result


def _extract_webcomic_cached(url: str) -> ComicExtraction:
    """
    Cached wrapper around LLM extraction. Caches the final parsed structure.
    """
    def _do() -> ComicExtraction:
        html = fetch_html(url)
        return _llm_extract_comic(url=url, html=html, model=getattr(config, "LLM", None))

    ttl = int(getattr(config, "COMICS_EXTRACTION_TTL_S", 86400))
    return cache.get(f"comics:extract:{url}", _do, ttl)


def _fetch_url(url: str, timeout: float = 10.0) -> bytes:
    req = Request(url, headers={"User-Agent": "daily-briefing/0.1 (+https://example.local)"})
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_comics(
    feeds: List[str] | None = None,
    per_feed_limit: int = 5,
    total_limit: int = 20,
    ttl_s: int | None = None,
    since: datetime | None = None,
    official: bool = False,
) -> Dict[str, Any]:
    """
    Fetch and normalize comics RSS/Atom feeds into a structure:
    {
      "items": [
        { title, link, source, source_slug, source_host, slug, published (ISO8601 UTC) },
        ...
      ],
      "groups": {
        <source_slug>: { "source": str, "source_slug": str, "items": [ ... ] },
        ...
      },
      "meta": { "cache_hits": int, "cache_misses": int, "ttl_s": int, "sources": int }
    }

    Notes:
    - Uses 'feedparser' to parse feeds.
    - If 'feeds' is None or empty, defaults are taken from tools.config.COMIC_FEEDS.
    - If 'since' is provided, only include items with published >= since (UTC).
    """
    if feeds is None or len(feeds) == 0:
        feeds = list(getattr(config, "COMIC_FEEDS", []) or [])
    assert isinstance(feeds, list) and len(feeds) > 0, "No COMIC_FEEDS configured in tools/config.py"

    ttl = int(ttl_s if ttl_s is not None else int(getattr(config, "COMICS_FEED_TTL_S", 1800)))

    all_items: List[Dict[str, Any]] = []
    cache_hits = 0
    cache_misses = 0

    for url in feeds:
        def fetch_and_parse_feed() -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []
            try:
                raw = _fetch_url(url, timeout=10.0)
                d = feedparser.parse(raw)
                source_host = urlparse(url).netloc
                source_title = (getattr(d, "feed", {}) or {}).get("title") or source_host
                source_slug = _slugify(source_title or source_host)
                entries = list(getattr(d, "entries", []) or [])
                for entry in entries[: per_feed_limit or len(entries)]:
                    title = unescape((entry.get("title") or "(untitled)")).strip()
                    link = entry.get("link") or entry.get("id") or url

                    if entry.get("published_parsed"):
                        published = datetime.fromtimestamp(
                            calendar.timegm(entry["published_parsed"]), tz=timezone.utc
                        ).isoformat()
                    elif entry.get("updated_parsed"):
                        published = datetime.fromtimestamp(
                            calendar.timegm(entry["updated_parsed"]), tz=timezone.utc
                        ).isoformat()
                    else:
                        published = _safe_iso(entry.get("published") or entry.get("updated") or "")

                    item = {
                        "title": title or "(untitled)",
                        "link": link,
                        "source": source_title,
                        "source_slug": source_slug,
                        "source_host": source_host,
                        "slug": _slugify(title),
                        "published": published,
                    }
                    items.append(item)

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
            return items

        items = cache.get(f"comics:feed:{url}", fetch_and_parse_feed, ttl)

        if since is not None:
            filtered_items: List[Dict[str, Any]] = []
            for it in items:
                pub_dt = _parse_iso(str(it.get("published") or ""))
                if pub_dt is not None and pub_dt >= since:
                    filtered_items.append(it)
            items = filtered_items

        all_items.extend(items)

        # Enforce total limit if requested
        if total_limit and len(all_items) >= total_limit:
            all_items = all_items[:total_limit]
            break

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
        "title": "Comics",
        "items": all_items,
        "groups": groups,
        "meta": meta,
    }


def _sile_img(src: str) -> str:
    """
    Render a SILE image command for the given URL.
    We escape double-quotes to keep attribute quoting intact.
    """
    safe = src.replace('"', "%22")
    return f'    \\img[src="{safe}"]'


def generate_sil(
    since: datetime | None = None,
    official: bool = False,
    **kwargs: Any,
) -> str:
    """
    Generate SILE code directly for the Comics section.
    Pulls feeds from tools.config.COMIC_FEEDS and renders each comic.
    If extraction fails for an item, emits "{Title} couldn't be parsed".
    """
    data = fetch_comics(
        feeds=list(getattr(config, "COMIC_FEEDS", []) or []),
        since=since,
        official=official,
    )
    items: List[Dict[str, Any]] = data.get("items", [])

    def _render_item_group(source: str, group_items: List[Dict[str, Any]]) -> str:
        lines: List[str] = [f"    \\rssGroupTitle{{{escape_sile(source)}}}"]
        for item in group_items:
            title = escape_sile(str(item.get("title", "(untitled)")))
            link = str(item.get("link") or "")
            try:
                extraction = _extract_webcomic_cached(link)
                # Title line
                lines.append(f"    \\rssItemTitle{{{title}}}")
                if extraction.get("title_text"):
                    lines.append(f"    \\rssSubtitle{{{escape_sile(str(extraction['title_text']))}}}")
                # Images
                for img_url in extraction.get("images", []):
                    if isinstance(img_url, str) and img_url:
                        lines.append(_sile_img(img_url))
                # Extra text
                for txt in extraction.get("extra_text", []):
                    if isinstance(txt, str) and txt.strip():
                        lines.append(f"    \\rssSubtitle{{{escape_sile(txt)}}}")
                # Hidden image (e.g., SMBC)
                hidden = extraction.get("hidden_image")
                if isinstance(hidden, str) and hidden.strip():
                    lines.append(_sile_img(hidden))
            except Exception:
                # On any failure, emit the fallback message only.
                lines.append(f"    \\rssItemTitle{{{title} couldn't be parsed}}")

            # Separator between items
            lines.append("    \\rssItemSeparator")
        return "\n".join(lines)

    # Group items by source while preserving order
    grouped_items = groupby(items, key=lambda x: str(x.get("source", "Comic")))

    item_groups = [
        _render_item_group(source, list(group_items))
        for source, group_items in grouped_items
    ]

    content = "\n    \\rssGroupSeparator\n".join(item_groups)

    return f"""\\define[command=comicssection]{{
  \\sectionbox{{
    \\sectiontitle{{Comics}}
    {content}
  }}
}}"""


if __name__ == "__main__":
    """Generate build/comics.sil when run directly."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    out = Path("build/comics.sil")
    out.parent.mkdir(exist_ok=True)
    sil = generate_sil()
    out.write_text(sil, encoding="utf-8")
    print(f"Generated {out}")
