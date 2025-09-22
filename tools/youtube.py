from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def fetch_videos(channels: List[str]) -> List[Dict[str, Any]]:
    """
    Placeholder YouTube fetcher: returns one item referencing the first channel.
    """
    now = datetime.now(timezone.utc).isoformat()
    channel = channels[0] if channels else "Example Channel"
    return [
        {
            "title": "Placeholder Video",
            "channel": channel,
            "published": now,
            "link": "https://youtube.com/",
        }
    ]
