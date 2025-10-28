from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
from tools.util import escape_sile


def fetch_videos(channels: List[str]) -> Dict[str, Any]:
    """
    Placeholder YouTube fetcher: returns a section dict with one item referencing the first channel.
    """
    now = datetime.now(timezone.utc).isoformat()
    channel = channels[0] if channels else "Example Channel"
    return {
        "title": "YouTube",
        "items": [
            {
                "title": "Placeholder Video",
                "channel": channel,
                "published": now,
                "link": "https://youtube.com/",
            }
        ],
    }


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the youtube section.
    """
    from tools import config
    data = fetch_videos(config.YOUTUBE_CHANNELS)
    
    title = escape_sile(data["title"])
    items = data.get("items", [])
    
    content_lines = [f"    \\sectiontitle{{{title}}}"]
    
    if not items:
        content_lines.append("    No videos available")
        content_lines.append("    \\par")
    else:
        for item in items:
            video_title = escape_sile(item.get("title", "(untitled)"))
            channel = escape_sile(item.get("channel", ""))
            link = escape_sile(item.get("link", ""))
            
            content_lines.append(f"    \\font[weight=600]{{{video_title}}}")
            content_lines.append("    \\par")
            if channel:
                content_lines.append(f"    \\Subtle{{{channel}}}")
                content_lines.append("    \\par")
            if link:
                content_lines.append(f"    \\font[size=8pt]{{{link}}}")
                content_lines.append("    \\par")
    
    content = "\n".join(content_lines)
    
    return f"""\\define[command=youtubesection]{{
  \\sectionbox{{
{content}
  }}
}}"""
