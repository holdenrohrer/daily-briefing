from __future__ import annotations

from pathlib import Path
from typing import List, Dict

from tools.util import get_password_from_store

# Centralized configuration for data producers

# Sections configuration - single source of truth
SECTIONS: List[str] = [
    "email",
    "caldav",
    "rss",
    "api_spend",
    "youtube",
    "facebook",
    "weather",
    "metadata",
]
# RSS rendering configuration
# When True, the RSS section will render each source (blog/site) in its own section box.
RSS_PER_SOURCE_SECTIONBOX: bool = True

# Hosts to treat as "webcomics" for full-content rendering.
# These will be allowed to include multiple images, title text, extra descriptive text,
# and, for SMBC, an optional hidden alt comic image.
RSS_COMIC_HOSTS: List[str] = [
    "xkcd.com",
    "www.smbc-comics.com",
    "existentialcomics.com",
    "qwantz.com",
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
OPENROUTER_API_TOKEN: str = "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"
OPENROUTER_CREDITS_URL: str = "https://openrouter.ai/api/v1/credits"

# Printing configuration
PRINTER_NAME: str = "holdens_printer"
PRINT_THRESHOLD_USD: float = 1.00
PRINTER_OPTIONS: List[str] = ["-o", "sides=two-sided-long-edge"]
