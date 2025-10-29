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
import hashlib
from io import BytesIO

import feedparser  # type: ignore
import requests
from PIL import Image
from litellm import completion  # type: ignore

from tools import cache
from tools import config
from tools.util import escape_sile


class ComicExtraction(TypedDict):
    """
    Structured result for a webcomic extraction.

    Keys:
    - url: Source URL (non-empty).
    - images: Ordered list of image URLs (0 or more).
    - extra_text: Any extra descriptive text blocks (0 or more).

    Fails fast inside extraction helpers; callers should catch exceptions per-item.
    """
    url: str
    images: List[str]
    extra_text: List[str]


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

    system_prompt = (
        "You are a precise webcomic extraction assistant. Parse the provided HTML for a webcomic page "
        "and return a STRICT JSON object with the following keys:\n"
        '  - "images": array of strings (absolute image URLs with schema in reading order)\n'
        '  - "extra_text": Any mouseover text (title= tag) or explanation'
        ' or news text. Remove any html-coding. Normalize to UTF-8.\n'
        "Rules:\n"
        "- If a higher resolution image is available in srcset, use that instead"
        "- Do NOT include transcript. Do NOT include alt-text. Do NOT"
        " include navigation text. Do NOT include date-posted. Do NOT"
        " include tags.\n"
        "- extra_text should be human-readable and include annotations."
        " For example, ['Title text: this is the comic's title text"
        " today', 'Explanation: Some people think like this comic suggests"
        " they do', 'Line two of explanation.' 'News: I'm on a booktour']"
        "- Include multiple images if the comic has panels split across <img> tags.\n"
        "- Output ONLY valid JSON. No markdown fences, no prose.\n"
        "- VERY IMPORTANT: INCLUDE NO TEXT EXCEPT JSON. YOUR RESPONSE WILL FAIL TO PARSE IF IT IS NOT A VALID JSON OBJECT"
    )

    condensed = _condense_html(html)
    user_prompt = f"URL: {url}\nHTML:\n{condensed}"

    resp = completion(
        model=config.LLM,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        api_base="https://openrouter.ai/api/v1",
        api_key=token,
        temperature=0,
        extra_body={
            "zdr": True
        },
        num_retries=5,
    )

    content = resp['choices'][0]['message']['content']  # type: ignore[index]
    parsed = json.loads(content)

    if not isinstance(parsed, dict):
        raise TypeError("Parsed LLM output is not a JSON object")

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

    ttl = config.COMICS_EXTRACTION_TTL_S
    return cache.get(f"comics:extract:{url}", _do, ttl)


def _fetch_url(url: str, timeout: float = 10.0) -> bytes:
    req = Request(url)
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_comics(
    feeds: List[str] | None = None,
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
    feeds = config.COMIC_FEEDS

    ttl = config.COMICS_FEED_TTL_S

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
                for entry in entries:
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


def _cached_local_png_for_url(url: str, timeout: float = 20.0) -> str:
    """
    Download an image URL and cache a converted PNG under build/comics_images/.
    - Uses tools.cache.get with key "comics:image:<url>" and ttl config.COMIC_IMAGE_TTL_S.
    - Hashes the downloaded bytes (sha256) to deduplicate filenames across identical content.
    - Always writes PNG. If the original is not PNG, converts via Pillow; if it is PNG, re-encodes.
    Raises AssertionError for invalid input or empty responses.
    Returns the filesystem path (string) to the PNG file.
    """
    digest = hashlib.sha256(url.encode()).hexdigest()[:16]
    out_dir = Path("build/comics_images")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{digest}.png"

    if not out_path.exists():
        headers = {"User-Agent": "daily-briefing/comics-image/0.1 (+https://example.local)"}
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        data = r.content
        assert isinstance(data, (bytes, bytearray)) and len(data) > 0, "Downloaded empty image"


        with Image.open(BytesIO(data)) as im:
            if im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGBA")
            im.save(out_path, format="PNG", optimize=True)

    return str(out_path)



def _sile_img(url: str) -> str:
    """
    Render a SILE image command for a remote image URL by downloading to build/.
    Preserves aspect ratio and constrains to config.COMICS_IMAGE_MAX_WIDTH_IN x
    config.COMICS_IMAGE_MAX_HEIGHT_IN. Fails fast on invalid inputs.
    """
    assert isinstance(url, str) and url.strip() != "", "url must be a non-empty str"
    local = _cached_local_png_for_url(url)
    assert isinstance(local, str) and local.endswith(".png") and Path(local).exists(), "Local PNG missing"

    max_h = getattr(config, "COMICS_IMAGE_MAX_HEIGHT_IN")
    max_w = getattr(config, "COMICS_IMAGE_MAX_WIDTH_IN")
    assert isinstance(max_h, (int, float)) and max_h > 0, "Invalid COMICS_IMAGE_MAX_HEIGHT_IN"
    assert isinstance(max_w, (int, float)) and max_w > 0, "Invalid COMICS_IMAGE_MAX_WIDTH_IN"

    with Image.open(local) as im:
        w, h = im.size
        w /= 72.27
        h /= 72.27 # 72.27pt = 1in

    if w > max_w:
        resize_ratio = max_w/w
        h *= resize_ratio
        w *= resize_ratio
    if h > max_h:
        resize_ratio = max_h/h
        h *= resize_ratio
        w *= resize_ratio

    safe = local.replace('"', "%22")
    return f'    \\img[src="{safe}", width={w:.3f}in, height={h:.3f}in]'

def _outersperse(lst, sep):
    return [sep if i % 2 == 0 else lst[i // 2] for i in range(2 * len(lst) + 1)]

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
        lines: List[str] = [f"    \\vfil\\sectiontitle{{{escape_sile(source)}}}"]
        for item in group_items:
            title = escape_sile(str(item.get("title", "(untitled)")))
            link = str(item.get("link") or "")
            try:
                extraction = _extract_webcomic_cached(link)
                # Title line
                lines.append(f"    \\rssGroupTitle{{{title}}}")
                lines.append("    \\par")
                # Images
                image_includes = [_sile_img(img_url) for img_url in extraction.get("images")]
                lines.extend(_outersperse(image_includes, "\\vfil"))
                # Extra text
                lines.extend(_outersperse(extraction.get("extra_text"),
                                          "\\par"))
                lines.append("    \\skip[height=1em]\\vpenalty[penalty=-5]")
            except Exception as e:
                # On any failure, emit the fallback message only.
                lines.append(f"    \\rssItemTitle{{{title} couldn't be parsed}}")
                raise e

            # Separator between items
            lines.append("    \\rssItemSeparator")
        return "\n".join(lines)

    # Group items by source while preserving order
    grouped_items = groupby(items, key=lambda x: str(x.get("source", "Comic")))

    item_groups = [
        _render_item_group(source, list(group_items))
        for source, group_items in grouped_items
    ]

    content = "\n  }\n  \\sectionbox{\n".join(item_groups)

    return f"""\\define[command=comicssection]{{
  \\begin{{raggedright}}\\sectionbox{{
{content}
  }}\\end{{raggedright}}
}}"""


if __name__ == "__main__":
    """Generate build/comics.sil when run directly."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    out = Path("build/comics.sil")
    out.parent.mkdir(exist_ok=True)
    sil = generate_sil()
    out.write_text(sil, encoding="utf-8")
    print(f"Generated {out}")
