from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from tools.util import escape_sile


def summarize_spend(date_iso: str) -> Dict[str, Any]:
    """
    Dummy API spend section - returns placeholder data.
    """
    return {
        "title": "API Spend",
        "date": date_iso,
        "total_usd": 0.0,
        "totals": {
            "total_credits": 0.0,
            "total_usage": 0.0,
            "remaining": 0.0,
            "fetched_iso": datetime.now(timezone.utc).isoformat(),
        },
    }


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the API spend section.
    """
    yesterday = datetime.now(timezone.utc).date().isoformat()
    data = summarize_spend(yesterday)
    
    title = escape_sile(data["title"])
    date = escape_sile(data["date"])
    total_usd = data["total_usd"]
    
    totals = data["totals"]
    total_credits = totals["total_credits"]
    total_usage = totals["total_usage"]
    remaining = totals["remaining"]
    fetched_iso = escape_sile(totals["fetched_iso"])
    
    return f"""\\define[command=api_spendsection]{{
  \\sectionbox{{
    \\sectiontitle{{{title}}}
    OpenRouter usage since {date}: ${total_usd:.4f}
    \\par
    \\skip[height=0.25em]
    \\Subtle{{Total usage: ${total_usage:.4f}    Total credits: ${total_credits:.4f}    Remaining: ${remaining:.4f}}}
    \\par
    \\Subtle{{Updated: {fetched_iso}}}
    \\par
  }}
}}"""
