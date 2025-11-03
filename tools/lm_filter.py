from __future__ import annotations

import email
from email import policy
from email.parser import BytesParser
from typing import Any, Dict

from tools.util import llm, escape_sile, sile_img_from_url
from urllib.request import Request, urlopen
from html import unescape
import re

safe_tools = ['title', 'header', 'bold', 'italics', 'bolditalics', 'enumerate', 'itemize', 'item',]
tools_prompt = (
    "You may use the following tags as needed: \\title{} for titles, \\header{} for headers, "
    "\\bold{} for bold text, \\italics{} for italics, \\bolditalics{} for bold italics.\n"
    "No other tags are valid and they will display incorrectly to the user.\n"
    "Please do not include any other tags than the above listed.\n"
    "Do not include any HTML, markdown, links, URLs, or images of any kind in your output.\n"
)

async def oneline(email_data: Dict[str, Any]) -> str:
    """
    Filter email to a single line summary for marketing/appointment emails.
    """
    context = f"Subject: {email_data.get('subject', '')}, From: {email_data.get('from', '')}"
    body = email_data.get('raw_body', '')

    prompt = (
        "You are a filter. You take an email and pare it down to ONLY ONE SENTENCE. "
        f"Note: I already have access to context '{context}'. Do not duplicate the context."
    )

    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:10000],  # Limit body length
        return_json=False
    )

    return escape_sile(result)


async def dmarc_summary(email_data: Dict[str, Any]) -> str:
    """
    Filter DMARC reports to a single line summary of domain authentication status.
    """
    body = email_data.get('raw_body', '')

    prompt = (
        "You are a DMARC report summarizer. Extract key authentication information and "
        "summarize in ONE SENTENCE. Focus on: domain name, pass/fail status, "
        "and any significant authentication issues. "
        "Example: 'example.com: All messages passed DMARC, SPF, and DKIM authentication.' "
        "or 'example.com: 5 messages failed DMARC due to SPF alignment issues.'"
    )

    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:15000],  # DMARC reports can be longer
        return_json=False
    )

    return escape_sile(result)


async def verbatim(email_data: Dict[str, Any]) -> str:
    """
    Return email content verbatim with minimal formatting, allowing safe SILE commands.
    """
    body = email_data.get('raw_body', '')

    prompt = (
        "You are a filter that preserves important content verbatim.\n"
        "Return the content "
        "with minimal changes but clean formatting.\n"
        "DO NOT delete or summarize any body text.\n"
        "Remove signatures, disclaimers, and unsubscribe links."
    ) + tools_prompt

    result = await llm(
        system_prompt=prompt,
        user_prompt=body[:50000],
        return_json=False
    )

    # Allow basic formatting commands but escape everything else
    return escape_sile(result, safe_tools)

async def categorize_email(email_data: Dict[str, Any], valid_categories: list[str]) -> str:
    """
    Use LLM to categorize an email based on its content.
    """
    subject = email_data.get('subject', '')
    from_addr = email_data.get('from', '')
    body = email_data.get('raw_body', '')[:5000]  # Limit for categorization

    categories_list = ', '.join(valid_categories)

    prompt = (
        f"You are an email categorizer. Based on the email content, "
        f"determine which category this email belongs to from these options: {categories_list}. "
        f"You MUST respond with exactly one of these category names, nothing else: {categories_list}"
    )

    user_prompt = f"Subject: {subject}\nFrom: {from_addr}\n\n{body}"

    result = await llm(
        system_prompt=prompt,
        user_prompt=user_prompt,
        return_json=False
    )

    return result.strip()


def extract_text_from_url(url: str, timeout: float = 10.0) -> str:
    """
    Extract text content from a URL. Attempts to get clean text from HTML.
    """
    try:
        req = Request(url, headers={"User-Agent": "daily-briefing/0.1 (+https://example.local)"})
        with urlopen(req, timeout=timeout) as resp:
            content = resp.read().decode('utf-8', errors='replace')

        # Simple HTML to text conversion
        # Remove script and style elements
        content = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
        content = re.sub(r'<style[^>]*>.*?</style>', '', content, flags=re.DOTALL | re.IGNORECASE)

        # Remove HTML tags
        content = re.sub(r'<[^>]+>', ' ', content)

        # Unescape HTML entities
        content = unescape(content)

        # Normalize whitespace
        content = re.sub(r'\s+', ' ', content).strip()

        return content[:50000]  # Limit content size

    except Exception:
        return ""


async def verbatim_rss(rss_data: Dict[str, Any], extra_prompt='') -> str:
    """
    Return RSS content verbatim for feeds that should be included in their entirety.
    """
    title = rss_data.get('title', '')
    link = rss_data.get('link', '')
    content = rss_data.get('content', '')

    if not content and link:
        content = extract_text_from_url(link)

    if not content:
        content = rss_data.get('summary', '')

    prompt = (
        "You are a filter that preserves RSS content verbatim with formatting control.\n"
        "Keep article titles verbatim (do not change to title case).\n"
        "Clean up any formatting issues but preserve the complete content.\n"
        "Remove navigation elements, ads, and unrelated content.\n"
        "Note: sometimes, content will include many more posts than just the title post. "
        "Only include the title post and its subheadings in your resposne.\n"
    ) + tools_prompt + extra_prompt

    result = await llm(
        system_prompt=prompt,
        user_prompt=f"Title: {title}\n\n{content}",
        return_json=False
    )

    result = result.replace('\n', '\n\n')

    # Allow the new formatting tags
    return escape_sile(result, safe_tools)


async def pluralistic_filter(*args) -> str:
    """
    Special filter for Pluralistic that extracts sections up to 'Hey look at this: Delights to delectate'.
    Inherits most functionality from verbatim_rss.
    """
    return await verbatim_rss(*args, extra_prompt=(
        "For pluralistic, include all sections up to and including 'Hey look at this'\n"
        "Don't include any sections after this."
    ))

async def de_html(text: str) -> str:
    return await llm(
        system_prompt=(
            "Filter the following text from HTML to plain UTF-8.\n"
            "Include no further commentary.\n"
        ),
        user_prompt=text,
        return_json=False
    )

async def default_rss(rss_data: Dict[str, Any]) -> str:
    """
    Default RSS filter that extracts and cleans up the summary from RSS XML.
    """
    title = escape_sile(rss_data['title'])
    published = rss_data['published'].strftime("%Y %B %-d %H:%M")
    description = escape_sile(await de_html(rss_data['description']))

    return f'\\title{{{title}}}\\cr\\Subtle{{Published {published}}}\\cr\n{description}\\bigskip'
