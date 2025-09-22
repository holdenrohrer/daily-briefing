#!/usr/bin/env python3
"""
Simple generator: compile the SILE document to a PDF.

Usage:
  python generate.py
  python generate.py --output output/brief.pdf
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the daily report PDF using SILE"
    )
    parser.add_argument(
        "--output",
        "-o",
        default="output/brief.pdf",
        help="Path to write the generated PDF (default: output/brief.pdf)",
    )
    args = parser.parse_args()

    sile_bin = shutil.which("sile")
    if not sile_bin:
        sys.stderr.write(
            "Error: 'sile' not found in PATH. Activate the dev shell or install SILE.\n"
        )
        return 127

    repo_root = Path(__file__).resolve().parent
    input_sil = repo_root / "sile" / "main.sil"

    if not input_sil.is_file():
        sys.stderr.write(f"Error: Input SILE file not found: {input_sil}\n")
        return 2

    output_path = (repo_root / args.output).resolve()
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write(f"Error: Could not create output directory: {exc}\n")
        return 3

    cmd = [sile_bin, "-o", str(output_path), str(input_sil)]
    try:
        result = subprocess.run(cmd, check=False)
    except OSError as exc:
        sys.stderr.write(f"Error: Failed to execute SILE: {exc}\n")
        return 126

    if result.returncode != 0:
        sys.stderr.write(
            f"Error: SILE exited with status {result.returncode}\n"
        )
        return result.returncode

    print(f"OK: Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
