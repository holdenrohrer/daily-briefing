from __future__ import annotations

import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


def escape_sile(text: str) -> str:
    """
    Escape text for SILE by escaping backslashes, braces, and other problematic characters.
    """
    return (text.replace("\\", "\\\\")
               .replace("{", "\\{")
               .replace("}", "\\}")
               .replace("%", "\\%"))


def get_official_cutoff_time(oldest=timedelta(hours=48)) -> datetime:
    """
    Helper function for --official filtering.

    Returns the cutoff time for filtering items: the earlier of
    (last official release timestamp, 48 hours ago).

    Used to filter RSS and other time-based content to only show
    items that occurred after the last official release or in the
    last 48 hours, whichever is more recent.

    Returns:
        datetime: The cutoff time in UTC
    """
    import json
    from pathlib import Path

    now = datetime.now(timezone.utc)
    default_cutoff = now - oldest

    # Try to read last official timestamp
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

                # Return the later of the two times (more restrictive)
                return max(last_official, default_cutoff)
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        pass

    return default_cutoff


def record_official_timestamp(timestamp: datetime | None = None) -> None:
    """
    Record the timestamp for an official release.

    Args:
        timestamp: The timestamp to record. If None, uses current time.
    """
    import json
    from pathlib import Path

    if timestamp is None:
        timestamp = datetime.now(timezone.utc)

    # Ensure timestamp is UTC
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    official_file = Path("data/cache/official.json")
    official_file.parent.mkdir(parents=True, exist_ok=True)

    data = {"last_official": timestamp.isoformat()}
    with official_file.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True, ensure_ascii=False)


def calculate_pdf_printing_cost(pdf_path: Path) -> dict[str, Any]:
    """
    Calculate the printing cost of a PDF using ghostscript inkcov utility.

    Assumes printed back-front so (pagect+1)//2 paper used at $0.013/page
    and $0.045/(5% coverage page). C,M,Y,K all cost the same amount.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Dict with cost breakdown including paper cost, ink cost, and total cost
    """
    if not pdf_path.exists():
        return {
            "error": f"PDF file not found: {pdf_path}",
            "paper_cost": 0.0,
            "ink_cost": 0.0,
            "total_cost": 0.0,
        }

    try:
        # Run ghostscript inkcov to get ink coverage per page
        cmd = [
            "gs", "-q",
            "-o", "-",
            "-sDEVICE=inkcov",
            str(pdf_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if result.returncode != 0:
            return {
                "error": f"Ghostscript failed: {result.stderr}",
                "paper_cost": 0.0,
                "ink_cost": 0.0,
                "total_cost": 0.0,
            }

        # Parse inkcov output
        # Format is typically: Page N: C M Y K (percentages)
        lines = result.stdout.strip().split('\n')
        page_coverages = []

        for line in lines:
            # Extract coverage values after the colon
            values = [x for x in line.split()]
            if len(values) >= 4:
                c, m, y, k = values[:4]
                # Total coverage (sum of all channels)
                total_coverage = float(c) + float(m) + float(y) + float(k)
                page_coverages.append(total_coverage)

        page_count = len(page_coverages)
        if page_count == 0:
            return {
                "error": "Could not parse ink coverage data",
                "paper_cost": 0.0,
                "ink_cost": 0.0,
                "total_cost": 0.0,
            }

        # Calculate costs
        # Paper cost: (pages+1)//2 sheets at $0.013/sheet (duplex printing)
        sheets_used = (page_count + 1) // 2
        paper_cost = sheets_used * 0.013

        # Ink cost: total coverage percentage * $0.045 / (5% coverage)
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

def get_password_from_store(pass_path):
    """Retrieve password from password-store using pass command."""
    result = subprocess.run(
        ['pass', 'show', pass_path],
        capture_output=True,
        text=True,
        check=True
    )
    return result.stdout.strip().split('\n')[0]  # First line is the password
