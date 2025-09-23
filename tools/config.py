from __future__ import annotations

from pathlib import Path
from typing import List

# Centralized configuration for data producers

RSS_FEEDS: List[str] = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://pluralistic.net/feed/",
]

YOUTUBE_CHANNELS: List[str] = []

FACEBOOK_PAGES: List[str] = []

WEATHER_SVG_PATH: str | Path = "assets/charts/weather.svg"
