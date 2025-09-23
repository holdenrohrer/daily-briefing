#!/usr/bin/env python3
"""
Build orchestrator: prepares per-section JSON files and optionally invokes SILE
to render output/brief.pdf from sile/main.sil.

No external dependencies; standard library only.

Usage:
  python tools/build.py
  python tools/build.py --skip-sile
  python tools/build.py --sile sile/main.sil --output output/brief.pdf
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Callable
# Ensure project root is on sys.path when running as a script (python tools/build.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tools import caldav, facebook, rss, spend, weather as weather_mod, wiki, youtube, config


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)


def _official_state_path() -> Path:
    return Path("data/.cache/official.json")


def _read_last_official() -> datetime | None:
    p = _official_state_path()
    try:
        with p.open("r", encoding="utf-8") as fh:
            obj = json.load(fh)
        ts = obj.get("last_official")
        if not isinstance(ts, str) or not ts:
            return None
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return None


def _write_last_official(iso_ts: str) -> None:
    p = _official_state_path()
    _ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as fh:
        json.dump({"last_official": iso_ts}, fh, indent=2, sort_keys=True, ensure_ascii=False)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _build_placeholder_data() -> Dict[str, Any]:
    """
    Placeholder normalized structure for all sections.
    Includes titles and minimal items to make SILE output visibly change.
    """
    now = _iso_now()
    yesterday = datetime.now(timezone.utc).date().isoformat()
    data: Dict[str, Any] = {
        "generated_at": now,
        "version": 2,
        "sections": {
            "rss": {
                "title": "RSS Highlights",
                "items": [
                    {
                        "title": "Placeholder: Ars Technica",
                        "link": "https://feeds.arstechnica.com/arstechnica/index",
                        "source": "Ars Technica",
                        "published": now,
                        "summary": "This is a placeholder RSS item to demo layout.",
                    }
                ],
            },
            "wikipedia": {
                "title": "Wikipedia Front Page",
                "summary": "Placeholder summary of Wikipedia's main page.",
                "link": "https://en.wikipedia.org/wiki/Main_Page",
                "updated": now,
            },
            "api_spend": {
                "title": "API Spend (Yesterday)",
                "date": yesterday,
                "total_usd": 0.0,
                "by_service": [],
                "top_endpoints": [],
            },
            "youtube": {
                "title": "YouTube",
                "items": [
                    {
                        "title": "Placeholder Video",
                        "channel": "Example Channel",
                        "published": now,
                        "link": "https://youtube.com/",
                    }
                ],
            },
            "facebook": {
                "title": "Facebook",
                "items": [],
            },
            "caldav": {
                "title": "Today’s Events",
                "items": [],
            },
            "weather": {
                "title": "Weather",
                "svg_path": "assets/charts/weather.svg",
                "items": [],
            },
        },
        "sources": [
            {"name": "Ars Technica RSS", "url": "https://feeds.arstechnica.com/arstechnica/index"},
            {"name": "Pluralistic RSS", "url": "https://pluralistic.net/feed/"},
        ],
        "notes": [
            "This is placeholder data. Populate via tools/* modules as they land."
        ],
    }
    return data

def _write_per_section_jsons(verbose: bool = False, cutoff_dt: datetime | None = None, official: bool = False) -> None:
    """
    Write per-section JSON files under data/.
    Time-based filtering (e.g., RSS) is handled inside tools/rss.py; pass cutoff_dt
    to limit items published at or after that moment. When 'official' is True,
    rss metadata will be annotated accordingly.
    """
    def _fetch_json(file: str | Path, getter: Callable[..., Any], *args, **kwargs) -> Dict[str, Any]:
        data = getter(*args, **kwargs)
        if not isinstance(data, dict):
            data = {"items": data}
        _write_json(Path(file), data)
        if verbose:
            print(f"[build] Wrote {file}")
        return data

    # RSS
    rss_data = _fetch_json("data/rss.json", rss.fetch_rss, feeds=config.RSS_FEEDS, since=cutoff_dt, official=official)

    # Wikipedia
    wiki_data = _fetch_json("data/wikipedia.json", wiki.fetch_front_page)

    # API Spend
    yesterday = datetime.now(timezone.utc).date().isoformat()
    spend_data = _fetch_json("data/api_spend.json", spend.summarize_spend, yesterday)

    # YouTube
    yt_data = _fetch_json("data/youtube.json", youtube.fetch_videos, config.YOUTUBE_CHANNELS)

    # Facebook
    fb_data = _fetch_json("data/facebook.json", facebook.fetch_posts, config.FACEBOOK_PAGES)

    # CALDAV
    cal_data = _fetch_json("data/caldav.json", caldav.fetch_events, yesterday)

    # Weather (ensure placeholder SVG exists)
    weather_data = _fetch_json("data/weather.json", weather_mod.build_daily_svg, config.WEATHER_SVG_PATH)

    # Metadata (for end-of-document display)
    def _git_rev() -> str | None:
        try:
            out = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            rev = (out.stdout or "").strip()
            return rev or None
        except Exception:
            return None

    metadata: Dict[str, Any] = {
        "title": "Metadata",
        "created_iso": _iso_now(),
        "cutoff_iso": cutoff_dt.isoformat() if cutoff_dt else None,
        "official": bool(official),
        "python_version": sys.version,
        "git_rev": _git_rev(),
        "sections": {
            "rss": {
                "items": len(rss_data.get("items", [])) if isinstance(rss_data, dict) else 0,
                "sources": (rss_data.get("meta", {}) or {}).get("sources") if isinstance(rss_data, dict) else None,
            },
            "wikipedia": {
                "updated": (wiki_data or {}).get("updated") if isinstance(wiki_data, dict) else None,
            },
            "api_spend": {
                "date": (spend_data or {}).get("date") if isinstance(spend_data, dict) else None,
                "total_usd": (spend_data or {}).get("total_usd") if isinstance(spend_data, dict) else None,
            },
            "youtube": {
                "items": len(yt_data.get("items", [])) if isinstance(yt_data, dict) else 0,
            },
            "facebook": {
                "items": len(fb_data.get("items", [])) if isinstance(fb_data, dict) else 0,
            },
            "caldav": {
                "items": len(cal_data.get("items", [])) if isinstance(cal_data, dict) else 0,
            },
            "weather": {
                "svg_path": (weather_data or {}).get("svg_path") if isinstance(weather_data, dict) else None,
            },
        },
    }
    _fetch_json("data/metadata.json", lambda: metadata)

    # Also write a simple SILE snippet for typesetting the metadata at document end
    def _write_metadata_sil_file(md: Dict[str, Any]) -> None:
        p = Path("data/metadata.sil")
        _ensure_dir(p.parent)
        lines: list[str] = []
        lines.append("Metadata")
        lines.append("\\par")
        lines.append(f"Created: {md.get('created_iso') or ''}")
        if md.get("cutoff_iso") is not None:
            lines.append("\\par")
            lines.append(f"Cutoff: {md.get('cutoff_iso')}")
        lines.append("\\par")
        lines.append(f"Official build: {'Yes' if md.get('official') else 'No'}")
        if md.get("git_rev"):
            lines.append("\\par")
            lines.append(f"Git rev: {md.get('git_rev')}")
        if md.get("python_version"):
            pyver = str(md.get("python_version")).splitlines()[0]
            lines.append("\\par")
            lines.append(f"Python: {pyver}")
        secs = md.get("sections") or {}
        def _sec_count(key: str) -> int | None:
            try:
                sec = secs.get(key) or {}
                val = sec.get("items")
                return int(val) if isinstance(val, int) else None
            except Exception:
                return None
        for key, label in (("rss","RSS"), ("youtube","YouTube"), ("facebook","Facebook"), ("caldav","CALDAV")):
            cnt = _sec_count(key)
            if cnt is not None:
                lines.append("\\par")
                lines.append(f"{label} items: {cnt}")
        weather_sec = secs.get("weather") or {}
        if "svg_path" in weather_sec and weather_sec.get("svg_path"):
            lines.append("\\par")
            lines.append(f"Weather SVG: {weather_sec.get('svg_path')}")
        with p.open("w", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
        if verbose:
            print("[build] Wrote data/metadata.sil")

    _write_metadata_sil_file(metadata)


def _run_sile(sile_main: Path, output_pdf: Path, verbose: bool = False) -> int:
    env = os.environ.copy()
    _ensure_dir(output_pdf.parent)
    cmd = ["sile", "--luarocks-tree", "sile/lua_modules", "-o", str(output_pdf), '--', str(sile_main)]
    if verbose:
        print(f"[build] Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        print(
            "[build] ERROR: 'sile' not found on PATH. "
            "Ensure you are in the Nix dev shell (nix develop).",
            file=sys.stderr,
        )
        return 127

    # Capture SILE output (print only on error or verbose)
    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    # Heuristic: Treat known SILE error patterns as failure even if exit code is 0
    def _looks_like_sile_error(s: str) -> bool:
        if not s:
            return False
        return (
            "Error:" in s
            or "runtime error" in s
            or "\n! " in s
            or s.startswith("! ")
            or "Unknown command" in s
        )

    rc = proc.returncode
    if rc == 0 and (_looks_like_sile_error(stdout) or _looks_like_sile_error(stderr)):
        print(
            "[build] Detected SILE error patterns but exit code was 0; treating as failure",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0 and not verbose:
        print(f"[build] OK: {output_pdf}")
    else:
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        print(f"[build] SILE exited with {rc}", file=sys.stderr)
    return rc


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build data JSON and (optionally) render PDF via SILE."
    )
    p.add_argument(
        "--sile",
        default="sile/main.sil",
        type=str,
        help="Path to SILE entrypoint (.sil).",
    )
    p.add_argument(
        "--output",
        default="output/brief.pdf",
        type=str,
        help="Output PDF path.",
    )
    p.add_argument(
        "--skip-sile",
        action="store_true",
        help="Only build data JSON; do not run SILE.",
    )
    p.add_argument(
        "--official",
        action="store_true",
        help="Record this build as an official edition; filter content since last official or 48h ago.",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose logging (print detailed progress and SILE output).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sile_main = Path(args.sile)
    output_pdf = Path(args.output)

    # Ensure basic project directories exist
    for d in (
        Path("data"),
        Path("data/.cache"),
        Path("assets/charts"),
        Path("output"),
    ):
        _ensure_dir(d)


    # Determine cutoff for time-based sections: since last --official or 48h ago, whichever is later
    now_dt = datetime.now(timezone.utc)
    last_official_dt = _read_last_official()
    default_cutoff_dt = now_dt - timedelta(hours=48)
    if last_official_dt and last_official_dt > default_cutoff_dt:
        cutoff_dt = last_official_dt
    else:
        cutoff_dt = default_cutoff_dt

    _write_per_section_jsons(verbose=bool(args.verbose), cutoff_dt=cutoff_dt, official=bool(args.official))

    # If this is an official build, persist the timestamp
    if args.official:
        _write_last_official(now_dt.isoformat())
        if args.verbose:
            print(f"[build] Recorded official timestamp: {now_dt.isoformat()}")

    if args.skip_sile:
        if not args.verbose:
            print("[build] Done (data only).")
        return 0

    if not sile_main.exists():
        print(
            f"[build] ERROR: SILE entrypoint not found: {sile_main}",
            file=sys.stderr,
        )
        return 2

    return _run_sile(
        sile_main=sile_main,
        output_pdf=output_pdf,
        verbose=bool(args.verbose),
    )


if __name__ == "__main__":
    raise SystemExit(main())
