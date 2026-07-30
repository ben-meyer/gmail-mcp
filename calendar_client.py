"""Google Calendar API client wrapper.

Thin layer over googleapiclient — no MCP, no auth flow, just the Calendar
operations the MCP tools need.  Mirrors the shape of gmail_client.py so both
are easy to read side-by-side.
"""

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def get_service(creds: Credentials):
    """Build the Calendar API service object."""
    return build("calendar", "v3", credentials=creds)


# ── Calendar list ─────────────────────────────────────────────────────────────

def list_calendars(creds: Credentials) -> list[dict]:
    """Return all calendars the account has access to."""
    service = get_service(creds)
    result = service.calendarList().list().execute()
    return [
        {
            "id": c["id"],
            "name": c.get("summary", ""),
            "description": c.get("description", ""),
            "primary": c.get("primary", False),
            "access_role": c.get("accessRole", ""),
            "color": c.get("backgroundColor", ""),
        }
        for c in result.get("items", [])
    ]


# ── Events ────────────────────────────────────────────────────────────────────

def list_events(
    creds: Credentials,
    calendar_id: str = "primary",
    time_min: str | None = None,
    time_max: str | None = None,
    max_results: int = 20,
    query: str | None = None,
) -> list[dict]:
    """Return events from a calendar, ordered by start time.

    Args:
        time_min: Lower bound (inclusive) in RFC3339 / ISO 8601 format.
        time_max: Upper bound (exclusive) in RFC3339 / ISO 8601 format.
        query: Free-text search term applied by the API server.
    """
    service = get_service(creds)
    kwargs: dict = {
        "calendarId": calendar_id,
        "maxResults": max_results,
        "singleEvents": True,   # expand recurring events
        "orderBy": "startTime",
    }
    if time_min:
        kwargs["timeMin"] = time_min
    if time_max:
        kwargs["timeMax"] = time_max
    if query:
        kwargs["q"] = query

    result = service.events().list(**kwargs).execute()
    return [_summarise_event(e) for e in result.get("items", [])]


def get_event(
    creds: Credentials, event_id: str, calendar_id: str = "primary"
) -> dict:
    """Return full details of a single event."""
    service = get_service(creds)
    e = service.events().get(calendarId=calendar_id, eventId=event_id).execute()
    return _full_event(e)


def create_event(
    creds: Credentials,
    summary: str,
    start_dt: str,
    end_dt: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
) -> dict:
    """Create a new event.

    Args:
        start_dt / end_dt: ISO 8601 UTC strings, e.g. "2024-06-15T14:00:00Z"
        attendees: List of email addresses to invite.
    """
    service = get_service(creds)
    body: dict = {
        "summary": summary,
        "start": {"dateTime": start_dt, "timeZone": "UTC"},
        "end": {"dateTime": end_dt, "timeZone": "UTC"},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    send_updates = "all" if attendees else "none"
    result = service.events().insert(
        calendarId=calendar_id, body=body, sendUpdates=send_updates
    ).execute()
    return {"id": result["id"], "link": result.get("htmlLink", ""), "status": "created"}


def update_event(
    creds: Credentials,
    event_id: str,
    calendar_id: str = "primary",
    **kwargs,
) -> dict:
    """Patch an existing event.  Only provided keyword args are changed.

    Accepted kwargs: summary, description, location, start_dt, end_dt
    """
    service = get_service(creds)
    event = service.events().get(calendarId=calendar_id, eventId=event_id).execute()

    if "summary" in kwargs:
        event["summary"] = kwargs["summary"]
    if "description" in kwargs:
        event["description"] = kwargs["description"]
    if "location" in kwargs:
        event["location"] = kwargs["location"]
    if "start_dt" in kwargs:
        event["start"] = {"dateTime": kwargs["start_dt"], "timeZone": "UTC"}
    if "end_dt" in kwargs:
        event["end"] = {"dateTime": kwargs["end_dt"], "timeZone": "UTC"}

    result = service.events().update(
        calendarId=calendar_id, eventId=event_id, body=event
    ).execute()
    return {"id": result["id"], "status": "updated"}


def delete_event(
    creds: Credentials, event_id: str, calendar_id: str = "primary"
) -> dict:
    """Delete an event. Sends cancellation emails to attendees."""
    service = get_service(creds)
    service.events().delete(
        calendarId=calendar_id, eventId=event_id, sendUpdates="all"
    ).execute()
    return {"id": event_id, "status": "deleted"}


# ── Private helpers ───────────────────────────────────────────────────────────

def _start_end(e: dict) -> tuple[str, str]:
    start = e.get("start", {})
    end = e.get("end", {})
    return (
        start.get("dateTime", start.get("date", "")),
        end.get("dateTime", end.get("date", "")),
    )


def _summarise_event(e: dict) -> dict:
    start, end = _start_end(e)
    return {
        "id": e["id"],
        "summary": e.get("summary", "(no title)"),
        "start": start,
        "end": end,
        "location": e.get("location", ""),
        "attendees": [a.get("email", "") for a in e.get("attendees", [])],
        "status": e.get("status", ""),
        "link": e.get("htmlLink", ""),
    }


def _full_event(e: dict) -> dict:
    start, end = _start_end(e)
    return {
        "id": e["id"],
        "summary": e.get("summary", "(no title)"),
        "start": start,
        "end": end,
        "location": e.get("location", ""),
        "description": e.get("description", ""),
        "attendees": [
            {"email": a.get("email", ""), "status": a.get("responseStatus", "")}
            for a in e.get("attendees", [])
        ],
        "organizer": e.get("organizer", {}).get("email", ""),
        "status": e.get("status", ""),
        "recurrence": e.get("recurrence", []),
        "link": e.get("htmlLink", ""),
    }
