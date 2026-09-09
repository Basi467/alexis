"""Google Calendar access via the calendar.events scope -- can view, create, and
delete events, but deliberately can't touch calendar settings or create new
calendars (least privilege for what this assistant actually needs to do).
"""
import logging
from datetime import datetime, timedelta

from googleapiclient.errors import HttpError

from systems.google_auth import get_service, is_configured  # noqa: F401 (re-exported)

logger = logging.getLogger(__name__)


def _get_service():
    return get_service("calendar", "v3")


def _to_rfc3339(naive_datetime_str: str) -> str:
    """Parses 'YYYY-MM-DD HH:MM' as local time and attaches the system's current
    UTC offset, producing what the Calendar API expects. Assumes the assistant's
    machine is in the user's own timezone, which holds for a personal local
    assistant like this one."""
    dt = datetime.fromisoformat(naive_datetime_str.replace("T", " "))
    return dt.astimezone().isoformat()


def list_events(start_date: str, days: int = 1, max_results: int = 20) -> list[dict]:
    """start_date: 'YYYY-MM-DD'. Returns events from the start of start_date
    through the end of the day `days` later, most recent first. Empty list (not
    an error) if Calendar isn't set up or the call fails -- same "nothing to
    report" treatment as the Gmail client."""
    service = _get_service()
    if service is None:
        return []

    try:
        day_start = datetime.fromisoformat(start_date).astimezone()
        time_min = day_start.isoformat()
        time_max = day_start.replace(hour=23, minute=59, second=59)
        if days > 1:
            time_max = time_max + timedelta(days=days - 1)
        time_max = time_max.isoformat()

        result = service.events().list(
            calendarId="primary", timeMin=time_min, timeMax=time_max,
            maxResults=max_results, singleEvents=True, orderBy="startTime",
        ).execute()

        events = []
        for item in result.get("items", []):
            start = item.get("start", {}).get("dateTime") or item.get("start", {}).get("date")
            end = item.get("end", {}).get("dateTime") or item.get("end", {}).get("date")
            events.append({
                "id": item["id"],
                "summary": item.get("summary", "(no title)"),
                "start": start,
                "end": end,
                "location": item.get("location", ""),
            })
        return events

    except HttpError as e:
        logger.error("Calendar API error: %s", e)
        return []
    except Exception as e:
        logger.error("Failed to fetch calendar events: %s", e)
        return []


def create_event(summary: str, start_time: str, end_time: str, description: str = "") -> tuple[bool, str]:
    service = _get_service()
    if service is None:
        return False, "Calendar isn't set up yet."

    try:
        event_body = {
            "summary": summary,
            "start": {"dateTime": _to_rfc3339(start_time)},
            "end": {"dateTime": _to_rfc3339(end_time)},
        }
        if description:
            event_body["description"] = description

        service.events().insert(calendarId="primary", body=event_body).execute()
        return True, f"Added '{summary}' to your calendar."

    except HttpError as e:
        logger.error("Failed to create calendar event: %s", e)
        return False, f"I couldn't add that to your calendar: {e}"
    except Exception as e:
        logger.error("Failed to create calendar event: %s", e)
        return False, f"I couldn't add that to your calendar: {e}"


def find_event_by_summary(query: str, search_days: int = 60) -> dict | None:
    """Substring match against upcoming event titles, same fuzzy pattern used for
    cancelling reminders -- lets the user say 'cancel the dentist appointment'
    without knowing the calendar's internal event id."""
    today = datetime.now().strftime("%Y-%m-%d")
    events = list_events(today, days=search_days, max_results=100)
    query_lower = query.lower()
    for e in events:
        if query_lower in e["summary"].lower() or e["summary"].lower() in query_lower:
            return e
    return None


def describe_events(events: list[dict]) -> str:
    if not events:
        return ""
    parts = []
    for e in events:
        try:
            start = datetime.fromisoformat(e["start"]).strftime("%I:%M %p").lstrip("0")
        except (ValueError, TypeError):
            start = ""  # all-day event, no specific time to read out
        parts.append(f"{e['summary']}{f' at {start}' if start else ''}")
    return ", ".join(parts)


def delete_event(event_id: str) -> tuple[bool, str]:
    service = _get_service()
    if service is None:
        return False, "Calendar isn't set up yet."

    try:
        service.events().delete(calendarId="primary", eventId=event_id).execute()
        return True, "Removed that event from your calendar."
    except HttpError as e:
        logger.error("Failed to delete calendar event: %s", e)
        return False, f"I couldn't remove that event: {e}"
    except Exception as e:
        logger.error("Failed to delete calendar event: %s", e)
        return False, f"I couldn't remove that event: {e}"
