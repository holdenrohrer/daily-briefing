#!/usr/bin/env python3
"""
Build orchestrator: prepares data/data.json and optionally invokes SILE to
render output/brief.pdf from sile/main.sil.

No external dependencies; standard library only.
Environment:
- REPORT_DATA_JSON is set for SILE so templates can read the JSON path.

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict
# Ensure project root is on sys.path when running as a script (python tools/build.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from tools import caldav, facebook, rss, spend, weather as weather_mod, wiki, youtube


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)


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

def _write_per_section_jsons() -> None:
    """
    Write per-section placeholder JSON files under data/.
    """
    # RSS
    rss_feeds = [
        "https://feeds.arstechnica.com/arstechnica/index",
        "https://pluralistic.net/feed/",
    ]
    rss_json = {
        "title": "RSS Highlights",
        "items": rss.fetch_rss(rss_feeds),
    }
    _write_json(Path("data/rss.json"), rss_json)
    print("[build] Wrote data/rss.json")

    # Wikipedia
    wiki_json = wiki.fetch_front_page()
    _write_json(Path("data/wikipedia.json"), wiki_json)
    print("[build] Wrote data/wikipedia.json")

    # API Spend
    yesterday = datetime.now(timezone.utc).date().isoformat()
    spend_json = spend.summarize_spend(yesterday)
    _write_json(Path("data/api_spend.json"), spend_json)
    print("[build] Wrote data/api_spend.json")

    # YouTube
    yt_channels: list[str] = []
    yt_json = {
        "title": "YouTube",
        "items": youtube.fetch_videos(yt_channels),
    }
    _write_json(Path("data/youtube.json"), yt_json)
    print("[build] Wrote data/youtube.json")

    # Facebook
    fb_pages: list[str] = []
    fb_json = {
        "title": "Facebook",
        "items": facebook.fetch_posts(fb_pages),
    }
    _write_json(Path("data/facebook.json"), fb_json)
    print("[build] Wrote data/facebook.json")

    # CALDAV
    cal_json = {
        "title": "Today’s Events",
        "items": caldav.fetch_events(yesterday),
    }
    _write_json(Path("data/caldav.json"), cal_json)
    print("[build] Wrote data/caldav.json")

    # Weather (ensure placeholder SVG exists)
    svg_meta = weather_mod.build_daily_svg(Path("assets/charts/weather.svg"))
    weather_json = {
        "title": "Weather",
        "svg_path": svg_meta["svg_path"],
        "items": [],
    }
    _write_json(Path("data/weather.json"), weather_json)
    print("[build] Wrote data/weather.json")


def _run_sile(sile_main: Path, output_pdf: Path, data_json: Path) -> int:
    env = os.environ.copy()
    env["REPORT_DATA_JSON"] = str(data_json.resolve())
    _ensure_dir(output_pdf.parent)
    cmd = ["sile", "-o", str(output_pdf), str(sile_main)]
    print(f"[build] Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, env=env, check=False)
    except FileNotFoundError:
        print(
            "[build] ERROR: 'sile' not found on PATH. "
            "Ensure you are in the Nix dev shell (nix develop).",
            file=sys.stderr,
        )
        return 127
    if proc.returncode != 0:
        print(
            f"[build] SILE exited with {proc.returncode}", file=sys.stderr
        )
    return proc.returncode


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
        "--data-json",
        default="data/data.json",
        type=str,
        help="Combined data JSON output path.",
    )
    p.add_argument(
        "--skip-sile",
        action="store_true",
        help="Only build data JSON; do not run SILE.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    sile_main = Path(args.sile)
    output_pdf = Path(args.output)
    data_json = Path(args.data_json)

    # Ensure basic project directories exist
    for d in (
        Path("data"),
        Path("data/.cache"),
        Path("assets/charts"),
        Path("output"),
    ):
        _ensure_dir(d)

    # Write placeholder combined JSON
    data = _build_placeholder_data()
    _write_json(data_json, data)
    print(f"[build] Wrote {data_json}")
    _write_per_section_jsons()

    if args.skip_sile:
        return 0

    if not sile_main.exists():
        print(
            f"[build] ERROR: SILE entrypoint not found: {sile_main}",
            file=sys.stderr,
        )
        return 2

    return _run_sile(sile_main=sile_main, output_pdf=output_pdf, data_json=data_json)


if __name__ == "__main__":
    raise SystemExit(main())
