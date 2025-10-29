from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone, timedelta
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Optional

import requests
from PIL import Image  # type: ignore


def escape_sile(text: str) -> str:
    """
    Escape text for SILE by escaping backslashes, braces, and other problematic characters.
    """
    return (
        text.replace("\\", "\\\\")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("%", "\\%")
    )


# -----------------------------
# General time/metadata helpers
# -----------------------------

def get_official_cutoff_time(oldest: timedelta = timedelta(hours=48)) -> datetime:
    """
    Helper for --official filtering. Returns the later of (last official timestamp, now-oldest).
    """
    now = datetime.now(timezone.utc)
    default_cutoff = now - oldest

    official_file = Path("data/cache/official.json")
    try:
        if official_file.exists():
            with official_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            last_official_str = data.get("last_official")
            if last_official_str:
                last_official = datetime.fromisoformat(last_official_str)
                if last_official.tzinfo is None:
                    last_official = last_official.replace(tzinfo=timezone.utc)
                else:
                    last_official = last_official.astimezone(timezone.utc)
                return max(last_official, default_cutoff)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    return default_cutoff


def record_official_timestamp(timestamp: datetime | None = None) -> None:
    """
    Record the timestamp for an official release to data/cache/official.json.
    """
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    official_file = Path("data/cache/official.json")
    official_file.parent.mkdir(parents=True, exist_ok=True)

    data = {"last_official": timestamp.isoformat()}
    with official_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)


# -----------------------------
# Printing cost helper
# -----------------------------

def calculate_pdf_printing_cost(pdf_path: Path) -> dict[str, Any]:
    """
    Calculate the printing cost of a PDF using ghostscript inkcov utility.

    Assumes duplex printing: (pages+1)//2 sheets at $0.013/sheet and $0.045 per 5% coverage.
    """
    if not pdf_path.exists():
        return {
            "error": f"PDF file not found: {pdf_path}",
            "paper_cost": 0.0,
            "ink_cost": 0.0,
            "total_cost": 0.0,
        }

    try:
        cmd = [
            "gs",
            "-q",
            "-o",
            "-",
            "-sDEVICE=inkcov",
            str(pdf_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            return {
                "error": f"Ghostscript failed: {result.stderr}",
                "paper_cost": 0.0,
                "ink_cost": 0.0,
                "total_cost": 0.0,
            }

        lines = result.stdout.strip().split("\n")
        page_coverages: list[float] = []

        for line in lines:
            values = [x for x in line.split()]
            if len(values) >= 4:
                c, m, y, k = values[:4]
                total_coverage = (float(c) + float(m) + float(y) + float(k)) / 4 * 100
                page_coverages.append(total_coverage)

        page_count = len(page_coverages)
        if page_count == 0:
            return {
                "error": "Could not parse ink coverage data",
                "paper_cost": 0.0,
                "ink_cost": 0.0,
                "total_cost": 0.0,
            }

        sheets_used = (page_count + 1) // 2
        paper_cost = sheets_used * 0.013

        total_coverage = sum(page_coverages)
        ink_cost = total_coverage * 0.045 / 5.0

        total_cost = paper_cost + ink_cost

        return {
            "page_count": page_count,
            "sheets_used": sheets_used,
            "total_coverage_percent": total_coverage,
            "average_coverage_percent": total_coverage / page_count if page_count > 0 else 0.0,
            "paper_cost": round(paper_cost, 4),
            "ink_cost": round(ink_cost, 4),
            "total_cost": round(total_cost, 4),
        }

    except Exception as e:
        return {
            "error": f"Exception during cost calculation: {e}",
            "paper_cost": 0.0,
            "ink_cost": 0.0,
            "total_cost": 0.0,
        }


# -----------------------------
# Secrets helpers
# -----------------------------

def get_password_from_store(pass_path: str) -> str:
    """Retrieve password from password-store using pass command."""
    result = subprocess.run(["pass", "show", pass_path], capture_output=True, text=True, check=True)
    return result.stdout.strip().split("\n")[0]


def get_key_from_store(pass_path: str, key: str) -> str:
    """Retrieve specific key from password-store entry using pass command."""
    result = subprocess.run(["pass", "show", pass_path], capture_output=True, text=True, check=True)
    key_section = result.stdout.strip().split("\n")[1:]
    key_pairs = [kv.split(":", 1) for kv in key_section]
    kvs = {k: v.strip() for k, v in key_pairs}
    return kvs[key]


# -----------------------------
# Generic utilities shared across sections
# -----------------------------

def slugify(s: str) -> str:
    s = (s or "").lower().strip()
    s = unescape(s)
    s = __import__("re").sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s or "untitled"


def cache_get(key: str, fun: Callable[[], Any], ttl: int) -> Any:
    """Project-wide write-through cache wrapper."""
    from tools.cache import get as _cache_get  # Local import to avoid cycles

    return _cache_get(key, fun, ttl)


def fetch_html(url: str, timeout: float = 15.0) -> str:
    """
    Fetch a URL and return its HTML as text. Raises for HTTP errors or empty content.
    """
    assert isinstance(url, str) and url.startswith(("http://", "https://")), "URL must be http(s)"
    headers = {"User-Agent": "daily-briefing/0.1 (+https://example.local)"}
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    assert isinstance(text, str) and text != "", "Fetched empty response body"
    return text


async def llm_json(
    *,
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    api_base: str = "https://openrouter.ai/api/v1",
    temperature: float = 0,
) -> Any:
    """
    Call an LLM via OpenRouter (through LiteLLM) and return parsed JSON content.
    """
    from litellm import completion  # type: ignore
    from tools import config

    mdl = model or config.LLM
    token = api_key or config.OPENROUTER_API_TOKEN
    assert isinstance(mdl, str) and mdl.strip(), "LLM model must be configured"
    assert isinstance(token, str) and token.strip(), "OPENROUTER_API_TOKEN must be configured"

    resp = await acompletion(
        model=mdl,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        api_base=api_base,
        api_key=token,
        temperature=temperature,
        extra_body={"zdr": True},
        num_retries=5,
    )
    content = resp["choices"][0]["message"]["content"]  # type: ignore[index]
    return json.loads(content)


def cached_png_for_url(url: str, out_dir: str | Path = "build/images", ttl: Optional[int] = None) -> str:
    """
    Download an image URL and cache a converted PNG under out_dir.
    Uses project write-through cache to control re-fetch frequency.
    Returns the filesystem path (string) to the PNG file.
    """
    from tools import config

    out_path_dir = Path(out_dir)
    out_path_dir.mkdir(parents=True, exist_ok=True)

    effective_ttl = int(ttl if ttl is not None else getattr(config, "IMAGE_CACHE_TTL_S", 86400))

    def _do() -> str:
        headers = {"User-Agent": "daily-briefing/image-fetch/0.1 (+https://example.local)"}
        r = requests.get(url, headers=headers, timeout=20.0)
        r.raise_for_status()
        data = r.content
        assert isinstance(data, (bytes, bytearray)) and len(data) > 0, "Downloaded empty image"

        # Hash content to deduplicate across identical images
        digest = hashlib.sha256(data).hexdigest()[:16]
        out_path = out_path_dir / f"{digest}.png"
        if not out_path.exists():
            with Image.open(BytesIO(data)) as im:
                if im.mode not in ("RGB", "RGBA"):
                    im = im.convert("RGBA")
                im.save(out_path, format="PNG", optimize=True)
        return str(out_path)

    # If the cached path points to a file that was removed, force a refresh
    def _safe_get() -> str:
        p = cache_get(f"img:png:{url}", _do, effective_ttl)
        if not Path(p).exists():
            return _do()
        return p

    return _safe_get()


def build_sile_image_from_local(local_png_path: str | Path, max_width_in: float, max_height_in: float) -> str:
    """
    Build a SILE \\img command for a local PNG, preserving aspect ratio within the given bounds.
    """
    local = str(local_png_path)
    assert local.endswith(".png") and Path(local).exists(), "Local PNG missing"

    with Image.open(local) as im:
        w, h = im.size
        # Assume 72.27 px per inch for SILE points; this is heuristic
        w_in = w / 72.27
        h_in = h / 72.27

    if w_in > max_width_in:
        ratio = max_width_in / w_in
        w_in *= ratio
        h_in *= ratio
    if h_in > max_height_in:
        ratio = max_height_in / h_in
        w_in *= ratio
        h_in *= ratio

    safe = local.replace('"', "%22")
    return f'    \\img[src="{safe}", width={w_in:.3f}in, height={h_in:.3f}in]'


def sile_img_from_url(
    url: str,
    max_width_in: float,
    max_height_in: float,
    out_dir: str | Path = "build/images",
    ttl: Optional[int] = None,
) -> str:
    """Fetch an image URL (cached) and return a SILE \\img command string sized to fit."""
    local = cached_png_for_url(url, out_dir=out_dir, ttl=ttl)
    return build_sile_image_from_local(local, max_width_in=max_width_in, max_height_in=max_height_in)
