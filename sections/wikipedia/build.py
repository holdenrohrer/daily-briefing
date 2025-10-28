from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from tools.util import escape_sile


def fetch_front_page() -> Dict[str, Any]:
    """
    Placeholder Wikipedia front page summary.
    """
    now = datetime.now(timezone.utc).isoformat()
    return {
        "title": "Wikipedia Front Page",
        "summary": "Placeholder summary of Wikipedia's main page.",
        "link": "https://en.wikipedia.org/wiki/Main_Page",
        "updated": now,
    }


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the wikipedia section.
    """
    data = fetch_front_page()
    
    title = escape_sile(data["title"])
    summary = escape_sile(data["summary"])
    link = escape_sile(data["link"])
    
    return f"""\\define[command=wikipediasection]{{
  \\sectionbox{{
    \\sectiontitle{{{title}}}
    {summary}
    \\par
    \\skip[height=0.25em]
    \\Subtle{{{link}}}
    \\par
  }}
}}"""
