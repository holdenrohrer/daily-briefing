from __future__ import annotations

from typing import Any, Dict


def summarize_spend(date_iso: str) -> Dict[str, Any]:
    """
    Placeholder API spend summary for a given date.
    """
    return {
        "title": "API Spend (Yesterday)",
        "date": date_iso,
        "total_usd": 0.0,
        "by_service": [],
        "top_endpoints": [],
    }
