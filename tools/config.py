from __future__ import annotations

from pathlib import Path
from typing import List

# Centralized configuration for data producers


RSS_FEEDS: List[str] = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://pluralistic.net/feed/",
    "https://astralcodexten.substack.com/feed",
    "https://thezvi.substack.com/feed",
]

YOUTUBE_CHANNELS: List[str] = []

FACEBOOK_PAGES: List[str] = []

# Default geographic coordinates (used by weather section)
LAT: float = 33.996805
LON: float = -84.295903

WEATHER_SVG_PATH: str | Path = "assets/charts/weather.svg"
