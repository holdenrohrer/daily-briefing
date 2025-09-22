from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


def build_daily_svg(path: str | Path) -> Dict[str, Any]:
    """
    Write a minimal placeholder SVG to the given path and return metadata.
    """
    now = datetime.now(timezone.utc).isoformat()
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="200" viewBox="0 0 640 200">
  <rect width="640" height="200" fill="white" stroke="black" stroke-width="1"/>
  <text x="20" y="100" font-family="JetBrains Mono, monospace" font-size="16">Placeholder weather chart — {now}</text>
</svg>
"""
    p.write_text(svg, encoding="utf-8")
    return {"svg_path": str(p), "generated_at": now}
