from __future__ import annotations

from typing import Any, Dict
from tools.util import escape_sile


def fetch_events(date_iso: str) -> Dict[str, Any]:
    """
    Placeholder CALDAV events for a given date.
    """
    return {"title": "Today's Events", "items": []}


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the caldav section.
    """
    from datetime import date
    data = fetch_events(date.today().isoformat())
    
    title = escape_sile(data["title"])
    items = data.get("items", [])
    
    content_lines = [f"    \\sectiontitle{{{title}}}"]
    
    if not items:
        content_lines.append("    No events scheduled")
        content_lines.append("    \\par")
    else:
        for item in items:
            event_title = escape_sile(item.get("title", "(untitled)"))
            time = escape_sile(item.get("time", ""))
            
            content_lines.append(f"    \\font[weight=600]{{{event_title}}}")
            content_lines.append("    \\par")
            if time:
                content_lines.append(f"    \\Subtle{{{time}}}")
                content_lines.append("    \\par")
    
    content = "\n".join(content_lines)
    
    return f"""\\define[command=caldavsection]{{
  \\sectionbox{{
{content}
  }}
}}"""
