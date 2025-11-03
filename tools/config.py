from __future__ import annotations

from pathlib import Path
from typing import List, Dict, Union, Any

from tools.util import get_password_from_store, get_key_from_store, outlook_account
import tools.lm_filter as lm_filter

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

RSS_FEEDS: List[Union[str, Dict[str, Any]]] = [
    "https://feeds.arstechnica.com/arstechnica/index",
    {"url": "https://pluralistic.net/feed/", "parser": lm_filter.pluralistic_filter},
    "https://astralcodexten.substack.com/feed",
    {"url": "https://thezvi.substack.com/feed", "parser": lm_filter.verbatim_rss},
    "https://samkriss.substack.com/feed"
    "https://blog.kagi.com/rss.xml",
    "https://we-make-money-not-art.com/feed",
    "https://karpathy.bearblog.dev/feed/",
    "https://fivebooks.com/feed",
    "https://solar.lowtechmagazine.com/posts/index.xml",
    {"url": "https://100r.ca/links/rss.xml", "parser": lm_filter.verbatim_rss},
    "https://www.mots-surannes.fr/feed",
    "https://hackaday.com/feed",
    "https://theeggandtherock.com/feed",
    {"url": "https://www.christophertitmussdharma.org/feed", "parser": lm_filter.verbatim_rss},
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
        "account_type": "normal",
        "username": "hr",
        "password": get_password_from_store("hrhr.dev/hr")
    },
    outlook_account()
]

EMAIL_RULES = [
    {
        "condition": lambda m: m['from'] == 'jaynithya123@gmail.com',
        "display": lm_filter.verbatim, # move to verbatim_with_images soon
    },
]
EMAIL_CATEGORIES = [
    {
        "looks_like": "DMARC Report",
        "display": lm_filter.dmarc_summary
    },
    {
        "looks_like": "Transaction or Confirmation",
        "display": lm_filter.oneline
    },
    {
        "looks_like": "Marketing",
        "display": lm_filter.oneline
    },
    {
        "looks_like": "Personal Communication",
        "display": lm_filter.verbatim
    },
]

# OpenRouter API configuration

OPENROUTER_API_TOKEN: str = get_key_from_store("openrouter", "apikey")
OPENROUTER_CREDITS_URL: str = "https://openrouter.ai/api/v1/credits"
LLM: str = "openrouter/meta-llama/llama-3.1-70b-instruct"
LLM_TTL_S: int = 86400

# Comics section caching configuration
# TTL (in seconds) for caching RSS feed fetches for comics sources.
COMICS_FEED_TTL_S: int = 1800
# TTL (in seconds) for caching LLM extraction results per comic page.
COMICS_EXTRACTION_TTL_S: int = 86400
COMICS_IMAGE_TTL_S: int = 86400
# Maximum rendered image size (inches) for comics images in SILE
COMICS_IMAGE_MAX_HEIGHT_IN: float = 6.0
COMICS_IMAGE_MAX_WIDTH_IN: float = 5.0

RSS_FEED_TTL_S: int = 3600

# Printing configuration
PRINTER_NAME: str = "holdens_printer"
PRINT_THRESHOLD_USD: float = 1.00
PRINTER_OPTIONS: List[str] = []
