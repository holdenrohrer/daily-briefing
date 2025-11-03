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
import os
import subprocess
import sys
import re
from PyPDF2 import PdfReader, PdfWriter
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Callable
# Ensure project root is on sys.path when running as a script (python tools/build.py)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)
import importlib
from types import ModuleType
from tools import config, util

# Global metadata variable - sections can add to this directly
metadata_info = {}
import notify2
import time

def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)




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


def _generate_main_sil() -> None:
    """Generate build/main.sil based on config.SECTIONS"""
    lines = [
        "\\begin[class=holden-report, papersize=letter]{document}",
        "\\include[src=../sile/holden-report.sil]",
        "\\include[src=../sile/utils.sil]",
        "",
        "% Per-section includes (generated sections or legacy format.sil)",
    ]

    for section in config.SECTIONS:
        # Check if section has generated .sil file, otherwise use legacy format.sil
        sil_path = Path(f"build/{section}.sil")
        lines.append(f"\\include[src={section}.sil]")

    lines.extend([
        "",
        "% Per-section commands",
    ])

    for section in config.SECTIONS:
        lines.append(f"\\{section}section")

    lines.extend([
        "",
        "\\end{document}",
    ])

    main_sil_path = Path("build/main.sil")
    main_sil_path.write_text("\n".join(lines), encoding="utf-8")


def _write_sil(file: str | Path, sil_content: str, verbose: bool = False) -> None:
    path = Path(file)
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        fh.write(sil_content)
    if verbose:
        print(f"[build] Wrote {file}")


def _write_per_section_sils(verbose: bool = False, cutoff_dt: datetime | None = None, official: bool = False) -> None:
    """
    Generate per-section .sil files and populate global metadata.
    Time-based filtering (e.g., RSS) is handled inside sections; pass cutoff_dt
    to limit items published at or after that moment. When 'official' is True,
    sections will be annotated accordingly.
    """
    global metadata_info

    # Initialize base metadata
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

    metadata_info = {
        "Created": _iso_now(),
        "Unix epoch": int(time.time()),
        "Cutoff": cutoff_dt.isoformat() if cutoff_dt else "None",
        "Official build": "Yes" if official else "No",
        "Git rev": _git_rev() or "Unknown",
    }

    # Build args that some sections might need (but most should get from config.py)
    build_args = {
        "since": cutoff_dt,  # Only for time-filtered sections like RSS
        "official": official,  # Only for sections that care about official builds
    }

    for section in config.SECTIONS:
        if section == "metadata":
            sil_generator = _generate_metadata_sil
        else:
            # Direct import of generate_sil from sections.{section}.build
            module = importlib.import_module(f"sections.{section}.build")
            sil_generator = getattr(module, "generate_sil")
        # Most sections should get what they need from config.py
        # Only pass build-specific args that can't be in config
        sil_content = sil_generator(**build_args)
        _write_sil(f"build/{section}.sil", sil_content, verbose)



def _generate_metadata_sil(**kwargs) -> str:
    """Generate SILE code directly for the metadata section - simple k:v displayer."""
    from tools.util import escape_sile

    global metadata_info
    data = metadata_info

    content_lines = [
        "\\vpenalty[penalty=-500]\\vfilll\\novbreak",
        "\\font[weight=200,size=6pt]{",
        "\\set[parameter=document.baselineskip, value=8pt]",
        "\\set[parameter=document.parskip, value=8pt]",
        "\\set[parameter=document.parindent, value=0pt]",
        "\\novbreak",
        "Metadata",
    ]

    # Simple k:v display for all metadata
    for key, value in data.items():
        if value is not None:
            content_lines.append("\\vpenalty[penalty=5]")
            content_lines.append(f"{key}: {escape_sile(str(value))}")

    content_lines.append("\\par}")
    content = "\n".join(content_lines)

    return f"""\\define[command=metadatasection]{{
{content}
}}"""


def _run_sile(sile_main: Path, output_pdf: Path, verbose: bool = False) -> int:
    env = os.environ.copy()
    _ensure_dir(output_pdf.parent)
    cmd = ["sile", "-o", str(output_pdf), '--', str(sile_main)]
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

    def _non_error_warn(s: str) -> bool:
        return re.match("^! (Overfull|Underfull)", s)
    # Heuristic: Treat known SILE error patterns as failure even if exit code is 0
    def _looks_like_sile_error(s: str) -> bool:
        if not s:
            return False
        return (
            "Error:" in s
            or "runtime error" in s
            or re.match("^! ", s)
            or "Unknown command" in s
        ) and not _non_error_warn(s)

    rc = proc.returncode
    if rc == 0 and (_looks_like_sile_error(stdout) or _looks_like_sile_error(stderr)):
        print(
            "[build] Detected SILE error patterns but exit code was 0; treating as failure",
            file=sys.stderr,
        )
        rc = 1

    non_error_warn = _non_error_warn(stdout) or _non_error_warn(stderr)

    if rc == 0 and not verbose and not non_error_warn:
        print(f"[build] OK: {output_pdf}")
    else:
        if stdout:
            print(stdout, end="")
        if stderr:
            print(stderr, end="", file=sys.stderr)
        print(f"[build] SILE exited with {rc}", file=sys.stderr)
    return rc


def _prompt_yes_no(question: str) -> bool:
    """
    Prompt the user with a yes/no question on stdin.

    Requirements:
    - 'question' must be a non-empty string.

    Returns True only for affirmative answers ('y'/'yes', case-insensitive).
    Returns False on empty input or EOF.
    """
    assert isinstance(question, str) and question.strip(), "question must be a non-empty string"
    if sys.stdin.isatty():
        try:
            ans = input(question + " [y/N] ")
        except EOFError:
            return False
        if not isinstance(ans, str):
            return False
        return ans.strip().lower() in ("y", "yes")
    else:
        return _notify2_prompt("Daily Briefing", question)


def _invoke_lpr(printer: str, pdf_path: Path, verbose: bool = False) -> int:
    """
    Print the given PDF using the 'lpr' command.

    Requirements:
    - 'printer' must be a non-empty string.
    - 'pdf_path' must point to an existing file.

    Raises:
    - AssertionError if preconditions are not met.
    - RuntimeError if lpr exits non-zero.

    Returns the lpr process return code on success.
    """
    assert isinstance(printer, str) and printer.strip(), "printer must be a non-empty string"
    assert isinstance(pdf_path, Path), "pdf_path must be a Path"
    assert pdf_path.is_file(), f"PDF does not exist: {pdf_path}"

    cmd = ["lpr", "-P", printer, *config.PRINTER_OPTIONS, str(pdf_path)]
    if verbose:
        print(f"[build] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"lpr failed (rc={proc.returncode}): {stderr}")
    if verbose:
        print(f"[build] Sent to printer '{printer}': {pdf_path}")
    return proc.returncode

def ensure_even_pages(pdf_path: str) -> str:
    """Ensure an even page count by adding a blank if necessary."""
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for p in reader.pages:
        writer.add_page(p)
    pagect = len(reader.pages)
    if len(reader.pages) % 2:
        from PyPDF2 import PageObject
        writer.add_page(PageObject.create_blank_page(
            width=reader.pages[0].mediabox.width,
            height=reader.pages[0].mediabox.height
        ))
        pagect += 1
    out = Path(pdf_path).with_stem(Path(pdf_path).stem + "_even")
    with open(out, "wb") as f:
        writer.write(f)
    return out, pagect

def _notify2_prompt(title: str, message: str) -> bool:
    """ Could easily be made asynch, but lazy. """
    notify2.init("Print Confirmation")
    n = notify2.Notification(title, message, "dialog-information")
    n.user_choice = None

    def yes_cb(noti, action): noti.user_choice = True
    def no_cb(noti, action): noti.user_choice = False

    n.add_action("yes", "Yes", yes_cb)
    n.add_action("no", "No", no_cb)
    n.show()

    # block forever until user clicks
    while n.user_choice is None:
        time.sleep(0.5)

    return n.user_choice

def extract_pages(pdf_path: str, suffix: str, pages: Generator[int, None, None], flip=False) -> str:
    """
    Create a new PDF containing only the specified (0-based) pages.
    Args:
        pdf_path: Path to the input PDF.
        suffix: Suffix to append to the output filename.
        pages: Generator of page indices to extract (0-based).
        flip: If True, rotate extracted pages 180 degrees.
    Returns:
        Path to the newly written PDF.
    """
    reader = PdfReader(pdf_path)
    writer = PdfWriter()
    for i in pages:
        if 0 <= i < len(reader.pages):
            page = reader.pages[i]
            if flip:
                page.rotate(180)
            writer.add_page(page)
    out_path = Path(pdf_path).with_stem(Path(pdf_path).stem + "_" + suffix)
    with open(out_path, "wb") as f:
        writer.write(f)
    return out_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build data JSON and (optionally) render PDF via SILE."
    )
    p.add_argument(
        "--sile",
        default="build/main.sil",
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
        Path("build"),
        Path("data/cache"),
        Path("build/charts"),
        Path("output"),
    ):
        _ensure_dir(d)

    # Determine cutoff for time-based sections using util function
    cutoff_dt = util.get_official_cutoff_time()

    _write_per_section_sils(verbose=bool(args.verbose), cutoff_dt=cutoff_dt, official=bool(args.official))

    # Generate build/main.sil based on available sections
    _generate_main_sil()
    if args.verbose:
        verbose = True
        print("[build] Generated build/main.sil")

    # If this is an official build, persist the timestamp
    if args.official:
        now_dt = datetime.now(timezone.utc)
        util.record_official_timestamp(now_dt)
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

    # Use build/main.sil instead of the provided sile_main
    build_main_sil = Path("build/main.sil")

    # First SILE run
    sile_result = _run_sile(build_main_sil, output_pdf, verbose=bool(args.verbose))
    if sile_result != 0:
        return sile_result

    # Calculate PDF printing cost and update metadata
    cost_info = util.calculate_pdf_printing_cost(output_pdf)
    if "error" in cost_info:
        print(f"[build] PDF printing cost calculation failed: {cost_info['error']}")
    else:
        print(f"[build] PDF printing cost: ${cost_info['total_cost']:.4f} "
              f"({cost_info['page_count']} pages, {cost_info['sheets_used']} sheets, "
              f"{cost_info['average_coverage_percent']:.1f}% avg coverage)")

        # Add cost data directly to global metadata with proper formatting
        metadata_info["Paper Cost"] = f"${cost_info['paper_cost']:.4f}"
        metadata_info["Ink Cost"] = f"${cost_info['ink_cost']:.4f}"

        # Format ink cost per page as requested
        ink_costs_per_page = cost_info['ink_costs_per_page']
        ink_costs_by_page = []
        for i, page_ink_cost in enumerate(ink_costs_per_page, 1):
            ink_costs_by_page.append(f"{i}: ${page_ink_cost:.4f}")
        metadata_info["Ink Cost by Page"] = "[" + ", ".join(ink_costs_by_page) + "]"

        # Calculate total cost
        total_cost = util.total_llm_cost + cost_info['paper_cost'] + cost_info['ink_cost']
        metadata_info["Total Cost"] = f"${total_cost:.4f}"

    # Add LLM cost to global metadata with formatting
    metadata_info["LLM Cost"] = f"${util.total_llm_cost:.4f}"

    _write_sil("build/metadata.sil", _generate_metadata_sil(), args.verbose)

    # Second SILE run with updated metadata
    _run_sile(build_main_sil, output_pdf, verbose=bool(args.verbose))

    even_count_pdf, pagect = ensure_even_pages(output_pdf)
    even_pdf = extract_pages(even_count_pdf, "even", range(0, pagect, 2))
    odd_pdf = extract_pages(even_count_pdf, "odd", range(pagect-1, 0, -2), flip=True)
    print(even_count_pdf, pagect, even_pdf, odd_pdf)

    # If this is an official build, decide whether to print
    if args.official:
        printer = config.PRINTER_NAME
        threshold = config.PRINT_THRESHOLD_USD
        if "error" in cost_info:
            print(
                f"[build] Skipping print: cannot estimate cost: {cost_info.get('error')}",
                file=sys.stderr,
            )
        else:
            total_cost = cost_info["total_cost"]
            question = f"Your daily briefing is ready!\nCost is ${total_cost:.2f}. Still print?"
            if total_cost < threshold or _prompt_yes_no(question):
                _invoke_lpr(printer, even_pdf, verbose=bool(args.verbose))
                if _prompt_yes_no("Pick up the print stack and reinsert into the printer without rotating.\nReady to print backsides?"):
                    _invoke_lpr(printer, odd_pdf, verbose=bool(args.verbose))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
