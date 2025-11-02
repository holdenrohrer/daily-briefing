from __future__ import annotations

import mailparser
import gzip
import zipfile
import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from imapclient import IMAPClient

from tools.util import escape_sile, get_official_cutoff_time, llm
from tools.config import EMAIL_ACCOUNTS, EMAIL_RULES, EMAIL_CATEGORIES
import tools.lm_filter as lm_filter

from html.parser import HTMLParser
from html import unescape

import asyncio

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


def extract_compressed_content(payload, max_size=100000):
    """
    Extract content from compressed attachments (.gz, .zip) with size limit.
    
    Args:
        payload: Raw attachment bytes
        max_size: Maximum content size to prevent zip bombs (default 100KB)
    
    Returns:
        str: Extracted text content or empty string if failed
    """
    try:
        # Try gzip first
        with gzip.open(io.BytesIO(payload), 'rt', encoding='utf-8', errors='replace') as f:
            content = f.read(max_size)
            return content
    except (gzip.BadGzipFile, OSError):
        pass
    
    try:
        # Try zip
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            content_parts = []
            total_size = 0
            
            for info in zf.infolist():
                if total_size >= max_size:
                    break
                
                # Skip directories and very large files
                if info.is_dir() or info.file_size > max_size:
                    continue
                
                with zf.open(info) as f:
                    chunk_size = min(info.file_size, max_size - total_size)
                    data = f.read(chunk_size)
                    text = data.decode('utf-8', errors='replace')
                    content_parts.append(f"--- {info.filename} ---\n{text}")
                    total_size += len(text)
                    
                    if total_size >= max_size:
                        break
            
            return '\n\n'.join(content_parts)
    except (zipfile.BadZipFile, UnicodeDecodeError):
        pass
        
    return ""


def parse_email_to_text(raw_email_bytes):
    """
    Parse email and return concatenated plain text including compressed attachments.
    Uses mail-parser for clean, automatic handling of complex nested structures.

    Args:
        raw_email_bytes: Raw email content as bytes

    Returns:
        str: Concatenated text content with compressed attachments expanded
    """
    mail = mailparser.parse_from_bytes(raw_email_bytes)
    text_parts = []

    # Get plain text (preferred) or HTML text
    if mail.text_plain:
        text_parts.extend(mail.text_plain)
    elif mail.text_html:
        # Strip HTML if no plain text available
        for html_part in mail.text_html:
            text_parts.append(strip_html(html_part))

    # Handle compressed attachments (for DMARC reports, etc.)
    for attachment in mail.attachments:
        filename = attachment.get('filename', '')
        if filename.endswith(('.gz', '.zip')):
            payload = attachment.get('payload')
            if payload:
                compressed_content = extract_compressed_content(payload)
                if compressed_content:
                    text_parts.append(f"--- Attachment: {filename} ---\n{compressed_content}")

    return '\n\n'.join(filter(None, text_parts))


async def _apply_email_filter(email_data: Dict[str, Any]) -> str:
    """
    Apply filtering rules to email based on EMAIL_RULES and EMAIL_CATEGORIES configuration.
    """
    # First check EMAIL_RULES for specific conditions
    for rule in EMAIL_RULES:
        if rule['condition'](email_data):
            return await rule['display'](email_data)
    
    # Use EMAIL_CATEGORIES with category detection
    category_names = [cat['looks_like'] for cat in EMAIL_CATEGORIES]
    category = await lm_filter.categorize_email(email_data, category_names)
    
    # Find matching category and apply its filter
    for cat_config in EMAIL_CATEGORIES:
        if category.lower().strip() == cat_config['looks_like'].lower().strip():
            return await cat_config['display'](email_data)
    
    # Fallback to oneline if no match found
    return await lm_filter.oneline(email_data)

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
                # Fetch email data including full message for processing
                response = server.fetch(messages, ['ENVELOPE', 'BODY.PEEK[TEXT]', 'BODY.PEEK[]'])

                async def extract_email_metadata(msgid, data):
                    """Extract basic email metadata without LLM processing."""
                    envelope = data[b'ENVELOPE']
                    raw_email_bytes = data.get(b'BODY[]', b'')

                    # Parse email using mail-parser for clean header decoding
                    mail = mailparser.parse_from_bytes(raw_email_bytes)
                    
                    # Extract email details (mail-parser handles all the encoding automatically)
                    subject = mail.subject or '(No Subject)'
                    from_addr = mail.from_[0][1] if mail.from_ and mail.from_[0] else '(Unknown Sender)'
                    email_date = envelope.date

                    # Convert date to UTC if needed
                    if email_date and email_date.tzinfo is None:
                        email_date = email_date.replace(tzinfo=timezone.utc)
                    if email_date.astimezone(timezone.utc) < cutoff_time.astimezone(timezone.utc):
                        return None

                    # Parse email content (includes compressed attachments)
                    raw_body = parse_email_to_text(raw_email_bytes)
                    
                    # Create email data structure for filtering
                    return {
                        'subject': subject,
                        'from': from_addr,
                        'date': email_date,
                        'raw_body': raw_body,
                        'raw_email_bytes': raw_email_bytes,
                        'account': f"{imap_user}@{imap_server}"
                    }

                async def process_emails():
                    # First extract all metadata concurrently
                    email_metadata = await asyncio.gather(*[
                        extract_email_metadata(msgid, data) 
                        for msgid, data in response.items()
                    ])
                    
                    # Filter out None results
                    valid_emails = [email for email in email_metadata if email is not None]
                    
                    # Then apply filters concurrently to all valid emails
                    if valid_emails:
                        processed_bodies = await asyncio.gather(*[
                            _apply_email_filter(email_data) 
                            for email_data in valid_emails
                        ])
                        
                        # Combine metadata with processed bodies
                        for email_data, processed_body in zip(valid_emails, processed_bodies):
                            email_data['body'] = processed_body
                    
                    return valid_emails

                all_emails = asyncio.run(process_emails())

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
                # Body is already processed and escaped by the filter functions
                content_lines.append("\\font[size=10pt]{\\set[parameter=document.baselineskip, value=10pt]")
                content_lines.append(body)
                content_lines.append("}    \\par")

            content_lines.append("    \\smallskip")

    content = "\n".join(content_lines)

    return f"""\\define[command=emailsection]{{
  \\sectionbox{{
{content}
  }}
}}"""
