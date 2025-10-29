from __future__ import annotations

from pathlib import Path
from typing import List, Dict

from tools.util import get_password_from_store, get_key_from_store

# Centralized configuration for data producers

# Sections configuration - single source of truth
SECTIONS: List[str] = [
    "email",
    "caldav",
    "weather",
    "rss",
    "comics",
    "api_spend",
    "youtube",
    "facebook",
    "metadata",
]

# The canonical parts a comic may include.
RSS_COMIC_ALLOWED_PARTS: List[str] = ["title_text", "images", "extra_text", "hidden_image"]

RSS_FEEDS: List[str] = [
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://pluralistic.net/feed/",
    "https://astralcodexten.substack.com/feed",
    "https://thezvi.substack.com/feed",
    "https://blog.kagi.com/rss.xml",
    "https://we-make-money-not-art.com/feed",
    "https://karpathy.bearblog.dev/feed/",
    "https://fivebooks.com/feed",
    "https://solar.lowtechmagazine.com/index.xml",
    "https://www.mots-surannes.fr/feed/",
]

COMIC_FEEDS: List[str] = [
    "https://xkcd.com/rss.xml",
    "https://www.smbc-comics.com/rss.php",
    "https://existentialcomics.com/rss.xml",
    "https://qwantz.com/rssfeed.php",
]

CALENDAR_SOURCES: List[str] = [
    {"url": "https://dav.hrhr.dev/", "username": "hr", "password": get_password_from_store("hrhr.dev/hr")},
    {"url": "https://dav.hrhr.dev/", "username": "family", "password": get_password_from_store("hrhr.dev/family")},
]

YOUTUBE_CHANNELS: List[str] = []

FACEBOOK_PAGES: List[str] = []

# Default geographic coordinates (used by weather section)
LAT: float = 33.996805
LON: float = -84.295903

WEATHER_SVG_PATH: str | Path = "build/charts/weather.svg"

# Email configuration
EMAIL_ACCOUNTS: List[Dict[str, str]] = [
    {
        "server": "hrhr.dev",
        "username": "hr",
        "password": get_password_from_store("hrhr.dev/hr")
    }
]

# OpenRouter API configuration
# NOTE: Fill OPENROUTER_API_TOKEN with your actual token. Code asserts non-empty.
OPENROUTER_API_TOKEN: str = get_key_from_store("openrouter", "apikey")
OPENROUTER_CREDITS_URL: str = "https://openrouter.ai/api/v1/credits"
LLM: str = "openrouter/qwen/qwen3-8b"

# Comics section caching configuration
# TTL (in seconds) for caching RSS feed fetches for comics sources.
COMICS_FEED_TTL_S: int = 1800
# TTL (in seconds) for caching LLM extraction results per comic page.
COMICS_EXTRACTION_TTL_S: int = 86400
COMICS_IMAGE_TTL_S: int = 86400
# Maximum rendered image size (inches) for comics images in SILE
COMICS_IMAGE_MAX_HEIGHT_IN: float = 6.0
COMICS_IMAGE_MAX_WIDTH_IN: float = 5.0

# Printing configuration
PRINTER_NAME: str = "holdens_printer"
PRINT_THRESHOLD_USD: float = 1.00
PRINTER_OPTIONS: List[str] = ["-o", "sides=two-sided-long-edge"]
