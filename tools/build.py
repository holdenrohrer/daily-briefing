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
import re
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


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    _ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, sort_keys=True, ensure_ascii=False)




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


def _write_per_section_jsons(verbose: bool = False, cutoff_dt: datetime | None = None, official: bool = False) -> None:
    """
    Write per-section JSON files under build/.
    Time-based filtering (e.g., RSS) is handled inside sections; pass cutoff_dt
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

    # Get section data using dynamic approach based on config
    section_data = {}

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

    # Extract individual section data for metadata
    rss_data = section_data.get("rss", {})
    wiki_data = section_data.get("wikipedia", {})
    spend_data = section_data.get("api_spend", {})
    yt_data = section_data.get("youtube", {})
    fb_data = section_data.get("facebook", {})
    cal_data = section_data.get("caldav", {})
    weather_data = section_data.get("weather", {})

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

    # Generate metadata section dynamically based on config.SECTIONS
    metadata_sections = {}
    for section in config.SECTIONS[:-1]:  # Exclude metadata itself
        if section == "rss":
            metadata_sections[section] = {
                "items": len(rss_data.get("items", [])) if isinstance(rss_data, dict) else 0,
                "sources": (rss_data.get("meta", {}) or {}).get("sources") if isinstance(rss_data, dict) else None,
            }
        elif section == "wikipedia":
            metadata_sections[section] = {
                "updated": (wiki_data or {}).get("updated") if isinstance(wiki_data, dict) else None,
            }
        elif section == "api_spend":
            metadata_sections[section] = {
                "date": (spend_data or {}).get("date") if isinstance(spend_data, dict) else None,
                "total_usd": (spend_data or {}).get("total_usd") if isinstance(spend_data, dict) else None,
            }
        elif section == "youtube":
            metadata_sections[section] = {
                "items": len(yt_data.get("items", [])) if isinstance(yt_data, dict) else 0,
            }
        elif section == "facebook":
            metadata_sections[section] = {
                "items": len(fb_data.get("items", [])) if isinstance(fb_data, dict) else 0,
            }
        elif section == "caldav":
            metadata_sections[section] = {
                "items": len(cal_data.get("items", [])) if isinstance(cal_data, dict) else 0,
            }
        elif section == "weather":
            metadata_sections[section] = {
                "svg_path": (weather_data or {}).get("svg_path") if isinstance(weather_data, dict) else None,
            }

    metadata: Dict[str, Any] = {
        "title": "Metadata",
        "created_iso": _iso_now(),
        "cutoff_iso": cutoff_dt.isoformat() if cutoff_dt else None,
        "official": bool(official),
        "python_version": sys.version,
        "git_rev": _git_rev(),
        "sections": metadata_sections,
    }
    _fetch_json("build/metadata.json", lambda: metadata)



def _generate_metadata_sil(**kwargs) -> str:
    """Generate SILE code directly for the metadata section."""
    from tools.util import escape_sile

    # Read the metadata JSON that was already generated
    with open("build/metadata.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    content_lines = [
        "  \\vpenalty[penalty=-500]\\vfilll",
        "  \\font[weight=200,size=6pt]{",
        "    \\set[parameter=document.baselineskip, value=8pt]",
        "    \\novbreak",
        "    Metadata",
        "    \\par",
    ]

    if data.get("created_iso"):
        content_lines.append(f"    Created: {escape_sile(str(data['created_iso']))}")
        content_lines.append("    \\par")
    if data.get("cutoff_iso"):
        content_lines.append(f"    Cutoff: {escape_sile(str(data['cutoff_iso']))}")
        content_lines.append("    \\par")

    content_lines.append(f"    Official build: {'Yes' if data.get('official') else 'No'}")
    content_lines.append("    \\par")

    if data.get("git_rev"):
        content_lines.append(f"    Git rev: {escape_sile(str(data['git_rev']))}")
        content_lines.append("    \\par")

    if data.get("python_version"):
        pyver = str(data["python_version"])
        firstline = pyver.split('\n')[0] if '\n' in pyver else pyver
        content_lines.append(f"    Python: {escape_sile(firstline)}")
        content_lines.append("    \\par")

    sections = data.get("sections", {})
    if sections.get("rss", {}).get("items"):
        content_lines.append(f"    RSS items: {sections['rss']['items']}")
        content_lines.append("    \\par")
    if sections.get("youtube", {}).get("items"):
        content_lines.append(f"    YouTube items: {sections['youtube']['items']}")
        content_lines.append("    \\par")
    if sections.get("facebook", {}).get("items"):
        content_lines.append(f"    Facebook items: {sections['facebook']['items']}")
        content_lines.append("    \\par")
    if sections.get("caldav", {}).get("items"):
        content_lines.append(f"    CALDAV items: {sections['caldav']['items']}")
        content_lines.append("    \\par")

    if data.get("printing_cost"):
        cost = data["printing_cost"]
        if not cost.get("error"):
            content_lines.append(f"    Printing Cost: ${cost.get('total_cost', 0):.2f}")
            content_lines.append("    \\par")

    content_lines.append("  }")
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
    try:
        ans = input(question)
    except EOFError:
        return False
    if not isinstance(ans, str):
        return False
    return ans.strip().lower() in ("y", "yes")


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

    cmd = ["lpr", *config.PRINTER_OPTIONS, "-P", printer, str(pdf_path)]
    if verbose:
        print(f"[build] Running: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        raise RuntimeError(f"lpr failed (rc={proc.returncode}): {stderr}")
    if verbose:
        print(f"[build] Sent to printer '{printer}': {pdf_path}")
    return proc.returncode


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

    _write_per_section_jsons(verbose=bool(args.verbose), cutoff_dt=cutoff_dt, official=bool(args.official))

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

    # Update metadata with cost info and regenerate
    metadata_path = Path("build/metadata.json")
    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)
    metadata["printing_cost"] = cost_info
    with metadata_path.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, sort_keys=True, ensure_ascii=False)

    _write_sil("build/metadata.sil", _generate_metadata_sil(), args.verbose)

    # Second SILE run with updated metadata
    _run_sile(build_main_sil, output_pdf, verbose=bool(args.verbose))

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
            total_cost = float(cost_info.get("total_cost", 0.0))
            try:
                if total_cost < threshold:
                    _invoke_lpr(printer, output_pdf, verbose=bool(args.verbose))
                else:
                    question = f"Cost is ${total_cost:.2f}. Still print? [y/N] "
                    if _prompt_yes_no(question):
                        _invoke_lpr(printer, output_pdf, verbose=bool(args.verbose))
            except Exception as e:
                print(f"[build] Printing failed: {e}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
