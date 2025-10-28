from __future__ import annotations

import json
import re
import sys
from typing import List, Optional, TypedDict

import requests
from litellm import completion  # type: ignore

from tools import config


class ComicExtraction(TypedDict):
    """
    Structured result for a webcomic extraction.

    Keys:
    - url: Source URL (non-empty).
    - title_text: The comic's title or header text (may be empty if unavailable).
    - images: Ordered list of image URLs (0 or more).
    - extra_text: Any extra descriptive text blocks (0 or more).
    - hidden_image: Optional "hidden" second comic image (SMBC often has one).
    """
    url: str
    title_text: str
    images: List[str]
    extra_text: List[str]
    hidden_image: Optional[str]


def _condense_html(html: str, max_chars: int = 50000) -> str:
    """
    Collapse whitespace to reduce token usage, then truncate.
    Raises AssertionError if html is empty after cleaning.
    """
    cleaned = re.sub(r"\s+", " ", html or "").strip()
    assert cleaned != "", "Empty HTML provided to _condense_html()"
    return cleaned[:max_chars]


def fetch_html(url: str, timeout: float = 15.0) -> str:
    """
    Fetch a URL and return its HTML as text.
    - Requires http/https URL.
    - Raises exceptions from requests on network or status errors.
    """
    assert isinstance(url, str) and url.startswith(("http://", "https://")), "URL must be http(s)"
    headers = {
        "User-Agent": "webcomic-extract-prototype/0.1 (+https://example.local)"
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    text = resp.text
    assert isinstance(text, str) and text != "", "Fetched empty response body"
    return text


def llm_extract_comic(url: str, html: str, model: Optional[str] = None) -> ComicExtraction:
    """
    Use a small, inexpensive model via OpenRouter (through LiteLLM) to extract
    webcomic structure from HTML.

    Requirements:
    - config.OPENROUTER_API_TOKEN must be a non-empty string.
    - html must be non-empty.

    Fails fast with AssertionError on invalid inputs or missing config.
    """
    assert isinstance(url, str) and url != "", "url must be a non-empty str"
    assert isinstance(html, str) and html != "", "html must be a non-empty str"
    token = getattr(config, "OPENROUTER_API_TOKEN", "")
    assert isinstance(token, str) and token.strip() != "", "OPENROUTER_API_TOKEN must be set in tools/config.py"

    cheap_model = model or "openrouter/meta-llama/llama-3.1-8b-instruct"

    system_prompt = (
        "You are a precise webcomic extraction assistant. Parse the provided HTML for a webcomic page "
        "and return a STRICT JSON object with the following keys:\n"
        '  - "title_text": string (comic title/header; empty if not found)\n'
        '  - "images": array of strings (absolute image URLs in reading order)\n'
        '  - "extra_text": array of strings (short descriptive text blocks, in order)\n'
        '  - "hidden_image": string or null (SMBC often includes a second hidden comic)\n'
        "Rules:\n"
        "- Prefer the main comic content over surrounding site chrome.\n"
        "- Include multiple images if the comic has panels split across <img> tags.\n"
        "- If unsure about a hidden second comic, set hidden_image to null.\n"
        "- Output ONLY valid JSON. No markdown fences, no prose."
    )

    condensed = _condense_html(html)
    user_prompt = f"URL: {url}\nHTML:\n{condensed}"

    resp = completion(
        model=cheap_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        api_base="https://openrouter.ai/api/v1",
        api_key=token,
        temperature=0,
        max_tokens=800,
        # Enable Zero Data Retention (ZDR) and add a descriptive title for dashboard logs.
        extra_headers={
            "X-Title": "Webcomic Extract Prototype",
            "X-OpenRouter-Zero-Data-Retention": "true",
        },
    )

    # LiteLLM returns an OpenAI-compatible object.
    try:
        content = resp["choices"][0]["message"]["content"]  # type: ignore[index]
    except Exception as e:  # Fail fast with detail
        raise RuntimeError(f"Unexpected LLM response structure: {type(resp)}; error: {e}")

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM did not return valid JSON: {e}\n---\n{content}")

    # Validate and coerce to our TypedDict shape.
    if not isinstance(parsed, dict):
        raise TypeError("Parsed LLM output is not a JSON object")

    title_text = str(parsed.get("title_text") or "")
    images = parsed.get("images") or []
    extra_text = parsed.get("extra_text") or []
    hidden_image = parsed.get("hidden_image", None)

    if not isinstance(images, list) or any(not isinstance(u, str) for u in images):
        raise TypeError('"images" must be a list of strings')
    if not isinstance(extra_text, list) or any(not isinstance(t, str) for t in extra_text):
        raise TypeError('"extra_text" must be a list of strings')
    if hidden_image is not None and not isinstance(hidden_image, str):
        raise TypeError('"hidden_image" must be a string or null')

    result: ComicExtraction = {
        "url": url,
        "title_text": title_text,
        "images": list(images),
        "extra_text": list(extra_text),
        "hidden_image": hidden_image if hidden_image is not None else None,
    }
    return result


def extract_webcomic(url: str, model: Optional[str] = None) -> ComicExtraction:
    """
    High-level helper: fetch HTML, then run LLM extraction.
    """
    html = fetch_html(url)
    return llm_extract_comic(url=url, html=html, model=model)


if __name__ == "__main__":
    """
    Prototype entrypoint. Provide a URL as argv[1], otherwise uses an SMBC homepage
    as a smoke test target (may not always be the latest strip page).
    """
    target_url = sys.argv[1] if len(sys.argv) > 1 else "https://www.smbc-comics.com"
    data = extract_webcomic(target_url)
    print(json.dumps(data, indent=2, ensure_ascii=False))
