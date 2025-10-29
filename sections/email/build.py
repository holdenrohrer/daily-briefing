from __future__ import annotations

import email
import email.header
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from imapclient import IMAPClient

from tools.util import escape_sile, get_official_cutoff_time, llm_json
from tools.config import EMAIL_ACCOUNTS

import email
from email import policy
from email.parser import BytesParser
from html.parser import HTMLParser
from html import unescape
import re

class HTMLStripper(HTMLParser):
    """Strips HTML tags and converts to plain text."""
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []

    def handle_data(self, d):
        self.text.append(d)

    def handle_starttag(self, tag, attrs):
        if tag in ['p', 'div', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.text.append('\n')

    def handle_endtag(self, tag):
        if tag in ['p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
            self.text.append('\n')

    def get_text(self):
        return unescape(''.join(self.text))


def strip_html(html):
    """Convert HTML to plain text by stripping tags."""
    stripper = HTMLStripper()
    stripper.feed(html)
    return stripper.get_text()


def extract_mime_content(raw_email_bytes):
    """
    Extract the actual MIME content from emails that may have wrapper boundaries.

    Some emails (especially from APIs) wrap the actual MIME message in an outer
    boundary. This function finds the actual Content-Type header and extracts
    the real message.
    """
    # Try to decode as string to search for headers
    try:
        email_str = raw_email_bytes.decode('utf-8', errors='replace')
    except AttributeError:
        email_str = raw_email_bytes

    # Look for the Content-Type header in the email
    content_type_match = re.search(r'^Content-Type:\s*multipart/\w+.*?boundary="([^"]+)"',
                                   email_str, re.MULTILINE | re.IGNORECASE)

    if content_type_match:
        # Find where the actual MIME headers start (after first boundary)
        # Look for the line with Content-Type: multipart
        lines = email_str.split('\n')
        start_idx = 0

        for i, line in enumerate(lines):
            if re.match(r'^Content-Type:\s*multipart/', line, re.IGNORECASE):
                start_idx = i
                break

        # Reconstruct from the actual MIME headers
        mime_content = '\n'.join(lines[start_idx:])
        return mime_content.encode('utf-8') if isinstance(mime_content, str) else mime_content

    return raw_email_bytes


def parse_email_to_text(raw_email_bytes):
    """
    Parse multipart or single-part email and return concatenated plain text.

    Args:
        raw_email_bytes: Raw email content as bytes

    Returns:
        str: Concatenated text content from all text parts, with HTML stripped
    """
    # Extract actual MIME content (handles wrapped emails)
    mime_content = extract_mime_content(raw_email_bytes)

    msg = BytesParser(policy=policy.default).parsebytes(mime_content)

    text_parts = []

    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = str(part.get("Content-Disposition", ""))

            if "attachment" in content_disposition:
                continue

            if content_type in ["text/plain", "text/html"]:
                payload = part.get_payload(decode=True)

                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    try:
                        text = payload.decode(charset, errors='replace')
                    except (UnicodeDecodeError, LookupError, AttributeError):
                        try:
                            text = payload.decode('utf-8', errors='replace')
                        except AttributeError:
                            text = str(payload)

                    if content_type == "text/html":
                        text = strip_html(text)

                    text_parts.append(text.strip())
    else:
        payload = msg.get_payload(decode=True)

        if payload:
            charset = msg.get_content_charset() or 'utf-8'
            try:
                text = payload.decode(charset, errors='replace')
            except (UnicodeDecodeError, LookupError, AttributeError):
                try:
                    text = payload.decode('utf-8', errors='replace')
                except AttributeError:
                    text = str(payload)

            if msg.get_content_type() == "text/html":
                text = strip_html(text)

            text_parts.append(text.strip())

    return '\n\n'.join(filter(None, text_parts))


def _email_summarize(context: str, body: str) -> List[str]:
    prompt = ''.join((
        "You are a filter. You take an email and pare it down.\n",
        "Marketing emails should become ONLY ONE SENTENCE.\n",
        "Appointments should become ONLY ONE SENTENCE.\n"
        "DO NOT INCLUDE EXTRANEOUS FACTS ABOUT THE EMAIL LIKE UNSUBSCRIBE LINKS.\n"
        "Quotes, personal messages, etc. should be conveyed verbatim. Use fancy quotation marks to indicate you are speaking verbatim\n"
        "Note: I already have access to context '{context}'. Do not duplicate the context.\n",
        "\n"
        "You MUST reply with JSON. Any other response is invalid.\n",
        "Fields:\n"
        "- extract: List of plain-text strings (no markdown, no links, no html). Each string will be displayed as a paragraph."
        ))
    return llm_json(system_prompt=prompt, user_prompt=body)['extract']

def fetch_emails() -> List[Dict[str, Any]]:
    """
    Fetch unread emails from IMAP servers using credentials from config.
    """
    all_emails = []

    # Get cutoff time but with oldest=infinitely old to never miss emails
    cutoff_time = get_official_cutoff_time(oldest=timedelta(days=365*100))  # 100 years ago

    for account in EMAIL_ACCOUNTS:
        imap_server = account["server"]
        imap_user = account["username"]
        imap_pass = account["password"]

        # Connect to IMAP server
        with IMAPClient(imap_server, ssl=True) as server:
            server.login(imap_user, imap_pass)

            # Select INBOX
            server.select_folder('INBOX')

            # Search for unread emails since cutoff time
            messages = server.search(['UNSEEN', 'SINCE', cutoff_time.date()])

            # Fetch all unread emails
            if messages:
                # Fetch email data
                response = server.fetch(messages, ['ENVELOPE', 'BODY.PEEK[TEXT]'])

                for msgid, data in response.items():
                    envelope = data[b'ENVELOPE']
                    body_data = data.get(b'BODY[TEXT]', b'')

                    # Extract email details from envelope
                    subject = envelope.subject.decode('utf-8') if envelope.subject else '(No Subject)'
                    from_addr = str(envelope.from_[0]) if envelope.from_ else '(Unknown Sender)'
                    email_date = envelope.date

                    # Convert date to UTC if needed
                    if email_date and email_date.tzinfo is None:
                        email_date = email_date.replace(tzinfo=timezone.utc)
                    if email_date.astimezone(timezone.utc) < cutoff_time.astimezone(timezone.utc):
                        continue

                    # Limit body length to avoid overwhelming output
                    context = f'{{"subject": {subject}, "from": {from_addr}, "received": {email_date}}}'
                    body = parse_email_to_text(body_data)
                    body = _email_summarize(context, body[:60000])

                    all_emails.append({
                        'subject': subject,
                        'from': from_addr,
                        'date': email_date,
                        'body': body,
                        'account': f"{imap_user}@{imap_server}"
                    })

    # Sort by date, most recent first
    all_emails.sort(key=lambda x: x['date'] if x['date'] else datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    return all_emails

def _intersperse(lst: List[str], sep: str) -> List[str]:
    return [sep if i % 2 else lst[i // 2] for i in range(2 * len(lst) - 1)]

def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the email section.
    """
    emails = fetch_emails()

    title = "Unread Emails"

    content_lines = [f"    \\sectiontitle{{{title}}}"]

    if not emails:
        content_lines.append("    No unread emails")
        content_lines.append("    \\par")
    else:
        for email_item in emails:
            subject = escape_sile(email_item.get('subject', '(No Subject)'))
            from_addr = escape_sile(email_item.get('from', '(Unknown Sender)'))
            body = email_item.get('body', '')
            email_date = email_item.get('date')
            account = escape_sile(email_item.get('account', ''))

            # Format date
            if email_date:
                date_str = email_date.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = "(No Date)"

            content_lines.append(f" \\font[weight=600]{{{escape_sile(subject)}}}")
            content_lines.append("    \\par")

            content_lines.append(f"    \\Subtle{{From: {from_addr}}}")
            content_lines.append("    \\par")

            content_lines.append(f"    \\Subtle{{Date: {escape_sile(date_str)}}}")
            if account:
                content_lines.append(f" · Account: {account}")
            content_lines.append("    \\par")


            if body:
                escaped_body = [escape_sile(line) for line in body]
                content_lines.append("\\font[size=10pt]{\\set[parameter=document.baselineskip, value=10pt]")
                content_lines.extend(_intersperse(escaped_body, '\\par'))
                content_lines.append("}    \\par")

            content_lines.append("    \\smallskip")

    content = "\n".join(content_lines)

    return f"""\\define[command=emailsection]{{
  \\sectionbox{{
{content}
  }}
}}"""
