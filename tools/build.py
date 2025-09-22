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
    Placeholder normalized structure. As data integrations are implemented,
    replace the empty lists / None values with real content.
    """
    return {
        "generated_at": _iso_now(),
        "version": 1,
        "sections": {
            "rss": [],
            "wikipedia": None,
            "api_spend": [],
            "youtube": [],
            "facebook": [],
            "caldav": [],
            "weather": {
                "svg_path": "assets/charts/weather.svg",
                "items": [],
            },
        },
        "sources": [],
        "notes": [
            "This is placeholder data. Populate via tools/* modules as they land."
        ],
    }


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
