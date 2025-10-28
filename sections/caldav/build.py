from __future__ import annotations

from typing import Any, Dict
from datetime import datetime, timedelta
import caldav

from tools.util import escape_sile
from tools.config import CALENDAR_SOURCES


def fetch_events(date: str) -> Dict[str, Any]:
    """
    CALDAV events for a given date.
    """
    start = date.replace(hour=0,minute=0,second=0,microsecond=0)
    end = start + timedelta(days=1)

    events = []
    for account in CALENDAR_SOURCES:
        url = account["url"]
        username = account["username"]
        password = account["password"]

        client = caldav.DAVClient(
            url=url,
            username=username,
            password=password
        )

        principal = client.principal()
        calendars = principal.calendars()

        for calendar in calendars:
            calendar_events = calendar.date_search(
                start=start,
                end=end,
                expand=True
            )
            for event in calendar_events:
                vev = event.vobject_instance.vevent
                events.append(
                    {
                        "summary": vev.summary.value,
                        "description": vev.description.value if hasattr(vev, 'description') else "",
                        "location": vev.location.value if hasattr(vev, 'location') else "",
                        "start": vev.dtstart.value,
                        "end": vev.dtend.value,
                        "calendar": str(calendar),
                    }
                )

    return events


def generate_sil(**kwargs) -> str:
    """
    Generate SILE code directly for the caldav section.
    """
    events = fetch_events(datetime.today())

    title = "Today's Events"

    content_lines = [f"    \\sectiontitle{{{title}}}"]

    if not events:
        content_lines.append("    No events scheduled")
        content_lines.append("    \\par")
    else:
        for event in events:
            event_title = escape_sile(event.get("summary", "(untitled)"))
            location = escape_sile(event.get("location", ""))
            calendar = escape_sile(event.get("calendar", ""))
            start = event.get("start")
            end = event.get("end")

            # Format time range
            if start and end:
                time = f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
            elif start:
                time = start.strftime('%H:%M')
            else:
                time = ""

            content_lines.append(f"    \\font[weight=600]{{{event_title}}}")
            if calendar:
                content_lines.append(f"({calendar})")
            content_lines.append("    \\par")

            if time:
                content_lines.append(f"    \\Subtle{{{time}}}")
                if location:
                    content_lines.append(f" · {location}")
                content_lines.append("    \\par")
            elif location:
                content_lines.append(f"    \\Subtle{{{location}}}")
                content_lines.append("    \\par")

    content = "\n".join(content_lines)

    return f"""\\define[command=caldavsection]{{
  \\sectionbox{{
{content}
  }}
}}"""
