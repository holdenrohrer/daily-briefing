from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict


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
