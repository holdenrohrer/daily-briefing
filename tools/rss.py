from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


def fetch_rss(feeds: List[str]) -> List[Dict[str, Any]]:
    """
    Placeholder RSS fetcher: returns one item referencing the first feed URL.
    """
    now = datetime.now(timezone.utc).isoformat()
    first = feeds[0] if feeds else "https://example.com/feed"
    source = "Ars Technica" if "arstechnica" in first else "RSS"
    return [
        {
            "title": f"Placeholder from {source}",
            "link": first,
            "source": source,
            "published": now,
            "summary": "This is a placeholder RSS item.",
        }
    ]
