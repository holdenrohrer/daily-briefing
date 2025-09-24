from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from urllib.parse import urlencode
import urllib.error
import urllib.request


GRAPH_API_BASE = "https://graph.facebook.com/v18.0"


def _env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def _first_n_words(text: str, n: int = 150) -> str:
    words = re.findall(r"\S+", text or "")
    if len(words) <= n:
        return " ".join(words)
    return " ".join(words[:n]) + " …"


def _parse_fb_time(s: str) -> datetime | None:
    """
    Parse Facebook's created_time (ISO-8601, sometimes with no colon in tz).
    """
    if not s:
        return None
    try:
        # Handles "...+00:00" and "Z"
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    try:
        # Handles "...+0000"
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def _time_12h(dt: datetime) -> str:
    dt_local = dt.astimezone()  # local time
    h = dt_local.hour
    m = dt_local.minute
    ampm = "pm" if h >= 12 else "am"
    h12 = h % 12
    if h12 == 0:
        h12 = 12
    return f"{h12}:{m:02d}{ampm}"


def _friendly_day_phrase(dt: datetime, now: datetime | None = None) -> str:
    if now is None:
        now = datetime.now(timezone.utc)
    dt_local = dt.astimezone()
    now_local = now.astimezone()
    if dt_local.date() == now_local.date():
        return "today"
    if dt_local.date() == (now_local.date() - timedelta(days=1)):
        return "yesterday"
    return f"on {dt_local.date().isoformat()}"


def _http_get_json(path: str, params: Dict[str, str], timeout: float = 10.0) -> Dict[str, Any]:
    token = (
        _env("FACEBOOK_ACCESS_TOKEN")
        or _env("FACEBOOK_GRAPH_TOKEN")
        or _env("FB_GRAPH_TOKEN")
        or ""
    )
    if not token:
        raise RuntimeError(
            "Missing FACEBOOK_ACCESS_TOKEN (or FACEBOOK_GRAPH_TOKEN/FB_GRAPH_TOKEN)"
        )
    q = params.copy()
    q["access_token"] = token
    url = f"{GRAPH_API_BASE}{path}?{urlencode(q)}"
    req = urllib.request.Request(url, headers={"User-Agent": "holden-report/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
        return json.loads(data.decode("utf-8"))


def _resolve_page(page: str) -> Tuple[str | None, str | None]:
    """
    Resolve a page alias/username/ID to (id, name).
    """
    try:
        data = _http_get_json(f"/{page}", {"fields": "id,name"})
        pid = data.get("id")
        name = data.get("name")
        if pid and name:
            return str(pid), str(name)
    except Exception:
        return None, None
    return None, None


def _fetch_page_posts(pid: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch latest posts for a page id.
    """
    fields = "message,created_time,permalink_url,story"
    try:
        data = _http_get_json(f"/{pid}/posts", {"limit": str(limit), "fields": fields})
    except Exception:
        return []
    return list(data.get("data") or [])


def _normalize_post(
    raw: Dict[str, Any], page_name: str, page_id: str
) -> Dict[str, Any]:
    created_s = (raw.get("created_time") or "").strip()
    dt = _parse_fb_time(created_s) or datetime.now(timezone.utc)
    item: Dict[str, Any] = {
        "id": str(raw.get("id") or ""),
        "page": page_name,
        "page_id": page_id,
        "title": str(raw.get("story") or "").strip(),
        "text": str(raw.get("message") or "").strip(),
        "published": dt.astimezone(timezone.utc).isoformat(),
        "link": str(raw.get("permalink_url") or "").strip(),
    }
    # Summary = first 150 words of the text (fallback to title+text if only title)
    base_text = item["text"] or f"{item['title']}".strip()
    item["summary"] = _first_n_words(base_text, 150) if base_text else ""

    # Fallback when no title and no text
    if not item["title"] and not item["text"]:
        t = _time_12h(dt)
        dayp = _friendly_day_phrase(dt)
        item["fallback"] = f"Post from {t} {dayp} (no body)"
    return item


def fetch_posts(pages: List[str]) -> Dict[str, Any]:
    """
    Fetch latest posts from public Facebook pages via Graph API.

    Configuration:
    - Requires an access token via one of:
      FACEBOOK_ACCESS_TOKEN, FACEBOOK_GRAPH_TOKEN, or FB_GRAPH_TOKEN

    Behavior:
    - Defaults to ['Negativland'] if no pages provided.
    - Fetches up to 5 posts per page.
    - Truncates displayed text to the first 150 words (in 'summary').
    """
    pages = pages or ["Negativland"]
    items: List[Dict[str, Any]] = []
    for page in pages:
        pid, name = _resolve_page(page)
        if not pid or not name:
            continue
        posts = _fetch_page_posts(pid, limit=5)
        for p in posts:
            items.append(_normalize_post(p, name, pid))

    # Sort newest first by published time
    def _key(x: Dict[str, Any]) -> str:
        return x.get("published") or ""

    items.sort(key=_key, reverse=True)

    return {
        "title": "Facebook",
        "items": items,
        "meta": {"fetched": datetime.now(timezone.utc).isoformat()},
    }
