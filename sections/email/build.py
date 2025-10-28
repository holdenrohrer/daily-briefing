from __future__ import annotations

import email
import email.header
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List
from imapclient import IMAPClient

from tools.util import escape_sile, get_official_cutoff_time
from tools.config import EMAIL_ACCOUNTS


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

                    # Extract and decode body
                    body = ""
                    if body_data:
                        try:
                            body = body_data.decode('utf-8').strip()
                        except UnicodeDecodeError:
                            try:
                                body = body_data.decode('latin-1').strip()
                            except UnicodeDecodeError:
                                body = body_data.decode('utf-8', errors='ignore').strip()

                    # Limit body length to avoid overwhelming output
                    if len(body) > 1000:
                        body = body[:1000] + "..."

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
            body = escape_sile(email_item.get('body', ''))
            email_date = email_item.get('date')
            account = escape_sile(email_item.get('account', ''))

            # Format date
            if email_date:
                date_str = email_date.strftime('%Y-%m-%d %H:%M')
            else:
                date_str = "(No Date)"

            content_lines.append(f"    \\font[weight=600]{{{subject}}}")
            content_lines.append("    \\par")

            content_lines.append(f"    \\Subtle{{From: {from_addr}}}")
            content_lines.append("    \\par")

            content_lines.append(f"    \\Subtle{{Date: {escape_sile(date_str)}}}")
            if account:
                content_lines.append(f" · Account: {account}")
            content_lines.append("    \\par")

            if body:
                content_lines.append(f"    {body}")
                content_lines.append("    \\par")

            content_lines.append("    \\smallskip")

    content = "\n".join(content_lines)

    return f"""\\define[command=emailsection]{{
  \\sectionbox{{
{content}
  }}
}}"""
