from __future__ import annotations

from pathlib import Path
from typing import List

# Centralized configuration for data producers

# Sections configuration - single source of truth
SECTIONS: List[str] = [
    "rss",
    "wikipedia",
    "api_spend",
    "youtube", 
    "facebook",
    "caldav",
    "weather",
    "metadata",
]

RSS_FEEDS: List[str] = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://pluralistic.net/feed/",
    "https://astralcodexten.substack.com/feed",
    "https://thezvi.substack.com/feed",
    "https://blog.kagi.com/rss.xml",
    "https://we-make-money-not-art.com/feed",
]

YOUTUBE_CHANNELS: List[str] = []

FACEBOOK_PAGES: List[str] = []

# Default geographic coordinates (used by weather section)
LAT: float = 33.996805
LON: float = -84.295903

WEATHER_SVG_PATH: str | Path = "build/charts/weather.svg"

# OpenRouter API configuration
# NOTE: Fill OPENROUTER_API_TOKEN with your actual token. Code asserts non-empty.
OPENROUTER_API_TOKEN: str = "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"
OPENROUTER_CREDITS_URL: str = "https://openrouter.ai/api/v1/credits"
