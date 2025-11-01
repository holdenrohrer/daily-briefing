from __future__ import annotations

import calendar
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from itertools import groupby
from pathlib import Path
from typing import Any, Dict, List, Optional, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
import asyncio

import feedparser  # type: ignore

from tools import config
from tools.util import escape_sile, slugify, fetch_html, llm, sile_img_from_url
import tools.cache as cache


class ComicExtraction(TypedDict):
    images: List[str]
    extra_text: List[str]


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
    cleaned = __import__("re").sub(r"\s+", " ", html or "").strip()
    assert cleaned != "", "Empty HTML provided to _condense_html()"
    return cleaned[:max_chars]


async def _llm_extract_comic(url: str, html: str) -> ComicExtraction:
    assert isinstance(url, str) and url != "", "url must be a non-empty str"
    assert isinstance(html, str) and html != "", "html must be a non-empty str"

    system_prompt = (
        "You are a precise webcomic extraction assistant. Parse the provided HTML for a webcomic page "
        "and return a STRICT JSON object with the following keys:\n"
        '  - "images": array of strings (absolute image URLs with schema in reading order)\n'
        '  - "extra_text": Any mouseover text (title= tag) or explanation or news text. Remove any html-coding. Normalize to UTF-8.\n'
        "Rules:\n"
        "- If a higher resolution image is available in srcset, use that instead\n"
        "- Do NOT include transcript. Do NOT include alt-text. Do NOT include navigation text. Do NOT include tags.\n"
        "- extra_text should be human-readable and include annotations.\n"
        "  For example, ['Title text: this is the comic\'s title text today', 'Explanation: Some people think like this comic suggests they do', 'Line two of explanation.', 'News: I\'m on a booktour']\n"
        "- Include multiple images if the comic has panels split across <img> tags.\n"
        "- Output ONLY valid JSON. No markdown fences, no prose.\n"
        "- VERY IMPORTANT: INCLUDE NO TEXT EXCEPT JSON. YOUR RESPONSE WILL FAIL TO PARSE IF IT IS NOT A VALID JSON OBJECT"
    )

    condensed = _condense_html(html)
    user_prompt = f"URL: {url}\nHTML:\n{condensed}"

    parsed = await llm(system_prompt=system_prompt, user_prompt=user_prompt, return_json=True)

    if not isinstance(parsed, dict):
        raise TypeError("Parsed LLM output is not a JSON object")

    images = parsed.get("images") or []
    extra_text = parsed.get("extra_text") or []

    if not isinstance(images, list) or any(not isinstance(u, str) for u in images):
        raise TypeError('"images" must be a list of strings')
    if not isinstance(extra_text, list) or any(not isinstance(t, str) for t in extra_text):
        raise TypeError('"extra_text" must be a list of strings')

    return {"images": list(images), "extra_text": list(extra_text)}


async def extract_webcomic_cached(url: str) -> ComicExtraction:
    async def _do() -> ComicExtraction:
        html = fetch_html(url)
        return await _llm_extract_comic(url=url, html=html)

    ttl = config.COMICS_EXTRACTION_TTL_S
    return await cache.get_async(f"comics:extract:{url}", _do, ttl)


def fetch_comics(
    feeds: Optional[List[str]] = None,
    since: Optional[datetime] = None,
    official: bool = False,
) -> Dict[str, Any]:
    """
    Fetch and normalize comics RSS/Atom feeds into a structure:
    {
      "items": [
        { title, link, source, source_slug, source_host, slug, published (ISO8601 UTC) },
        ...
      ],
      "groups": { <source_slug>: { "source": str, "source_slug": str, "items": [ ... ] }, ... },
      "meta": { "ttl_s": int, "sources": int, "cutoff_iso"?, "official"? }
    }

    - If 'feeds' is None or empty, defaults are taken from tools.config.COMIC_FEEDS.
    - If 'since' is provided, only include items with published >= since (UTC).
    """
    ttl = config.COMICS_FEED_TTL_S

    all_items: List[Dict[str, Any]] = []

    for url in feeds:
        def fetch_and_parse_feed() -> List[Dict[str, Any]]:
            items: List[Dict[str, Any]] = []
            try:
                d = feedparser.parse(url)
                source_host = urlparse(url).netloc
                source_title = (getattr(d, "feed", {}) or {}).get("title") or source_host
                source_slug = slugify(source_title or source_host)
                entries = list(getattr(d, "entries", []) or [])
                for entry in entries:
                    title = (entry.get("title") or "(untitled)").strip()
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

                    items.append(
                        {
                            "title": title or "(untitled)",
                            "link": link,
                            "source": source_title,
                            "source_slug": source_slug,
                            "source_host": source_host,
                            "slug": slugify(title),
                            "published": published,
                        }
                    )

            except (HTTPError, URLError) as e:
                host = urlparse(url).netloc
                items.append(
                    {
                        "title": "Error fetching feed",
                        "link": url,
                        "source": host,
                        "source_slug": slugify(host),
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
                        "source_slug": slugify(host),
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
        sslug = str(it.get("source_slug") or slugify(src or host))
        grp = groups.setdefault(sslug, {"source": src or host, "source_slug": sslug, "items": []})
        grp["items"].append(it)

    meta: Dict[str, Any] = {
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



def _outersperse(lst: List[str], sep: str) -> List[str]:
    return [sep if i % 2 == 0 else lst[i // 2] for i in range(2 * len(lst) + 1)]


def generate_sil(
    since: Optional[datetime] = None,
    official: bool = False,
    **kwargs: Any,
) -> str:
    """
    Generate SILE code directly for the Comics section.
    Pulls feeds from tools.config.COMIC_FEEDS and renders each comic.
    If extraction fails for an item, emits "{Title} couldn't be parsed".
    """
    data = fetch_comics(
        feeds = config.COMIC_FEEDS,
        since = since,
        official = official,
    )
    items: List[Dict[str, Any]] = data.get("items", [])

    def _render_item_group(source: str, group_items: List[Dict[str, Any]]) -> str:
        lines: List[str] = [f"    \\vfil\\sectiontitle{{{escape_sile(source)}}}"]
        extractions = []

        for item in group_items:
            title = escape_sile(str(item.get("title", "(untitled)")))
            link = str(item.get("link") or "")
            extraction = extract_webcomic_cached(link)
            extractions.append(extraction)

        async def gather():
            return await asyncio.gather(*extractions)

        for extraction in asyncio.run(gather()):
            # Title line
            lines.append(f"    \\rssGroupTitle{{{title}}}")
            lines.append("    \\par")
            # Images
            max_h = config.COMICS_IMAGE_MAX_HEIGHT_IN
            max_w = config.COMICS_IMAGE_MAX_WIDTH_IN
            img_ttl = config.COMICS_IMAGE_TTL_S
            image_includes = [
                sile_img_from_url(
                    img_url,
                    max_width_in=max_w,
                    max_height_in=max_h,
                    out_dir="build/comics_images",
                    ttl=img_ttl,
                )
                for img_url in extraction.get("images", [])
            ]
            lines.extend(_outersperse(image_includes, "\\vfil\\vpenalty[penalty=-5]"))
            # Extra text
            lines.extend(_outersperse(extraction.get("extra_text", []), "\\par"))
            lines.append("    \\skip[height=1em]\\vpenalty[penalty=-5]")

            # Separator between items
            lines.append("    \\rssItemSeparator")
        return "\n".join(lines)

    # Group items by source while preserving order
    grouped_items = groupby(items, key=lambda x: str(x.get("source", "Comic")))

    item_groups = [
        _render_item_group(source, list(group_items))
        for source, group_items in grouped_items
    ]

    content = "\n  }\n  \\vfill\\sectionbox{\n".join(item_groups)

    return f"""\\define[command=comicssection]{{
  \\begin{{raggedright}}\\vfill\\sectionbox{{
{content}
  }}\\end{{raggedright}}
}}"""


if __name__ == "__main__":
    # Generate build/comics.sil when run directly.
    out = Path("build/comics.sil")
    out.parent.mkdir(exist_ok=True, parents=True)
    sil = generate_sil()
    out.write_text(sil, encoding="utf-8")
    print(f"Generated {out}")
