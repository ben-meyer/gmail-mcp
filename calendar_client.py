"""Google Calendar API client wrapper.

Thin layer over googleapiclient — no MCP, no auth flow, just the Calendar
operations the MCP tools need.  Mirrors the shape of gmail_client.py so both
are easy to read side-by-side.
"""

from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Ben is in London; the guide (Part 6c) flags hardcoded UTC as the bug that
# books everything an hour out between late March and late October.
DEFAULT_TIMEZONE = "Europe/London"


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
    timezone_name: str = DEFAULT_TIMEZONE,
    send_invites: bool = False,
) -> dict:
    """Create a new event.

    Args:
        start_dt / end_dt: ISO 8601 strings — naive local times (resolved
            against timezone_name) or explicit offsets ("...Z"/"+01:00").
        timezone_name: IANA zone the datetimes live in. Defaults to
            Europe/London — NOT UTC, which silently booked an hour out in BST.
        attendees: List of email addresses to invite.
        send_invites: False (default) creates the event WITHOUT emailing
            attendees — a model mistake stays local until a human sends it.
            Only pass True deliberately.
    """
    service = get_service(creds)
    body: dict = {
        "summary": summary,
        "start": {"dateTime": start_dt, "timeZone": timezone_name},
        "end": {"dateTime": end_dt, "timeZone": timezone_name},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    # Gate: no emails leave this server unless explicitly asked for.
    send_updates = "all" if (attendees and send_invites) else "none"
    result = service.events().insert(
        calendarId=calendar_id, body=body, sendUpdates=send_updates
    ).execute()
    return {"id": result["id"], "link": result.get("htmlLink", ""), "status": "created"}


def update_event(
    creds: Credentials,
    event_id: str,
    calendar_id: str = "primary",
    timezone_name: str = DEFAULT_TIMEZONE,
    send_invites: bool = False,
    **kwargs,
) -> dict:
    """Patch an existing event.  Only provided keyword args are changed.

    Accepted kwargs: summary, description, location, start_dt, end_dt
    (start_dt/end_dt resolved against timezone_name; send_invites=False keeps
    attendee notification emails off unless explicitly requested).
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
        event["start"] = {"dateTime": kwargs["start_dt"], "timeZone": timezone_name}
    if "end_dt" in kwargs:
        event["end"] = {"dateTime": kwargs["end_dt"], "timeZone": timezone_name}

    send_updates = "all" if send_invites else "none"
    result = service.events().update(
        calendarId=calendar_id, eventId=event_id, body=event, sendUpdates=send_updates
    ).execute()
    return {"id": result["id"], "status": "updated"}


def delete_event(
    creds: Credentials, event_id: str, calendar_id: str = "primary",
    notify_attendees: bool = False,
) -> dict:
    """Delete an event. By default NO cancellation emails are sent — a wrong
    deletion must not email other people's inboxes. Pass notify_attendees=True
    deliberately to cancel on attendees' calendars."""
    service = get_service(creds)
    service.events().delete(
        calendarId=calendar_id, eventId=event_id,
        sendUpdates="all" if notify_attendees else "none",
    ).execute()
    return {"id": event_id, "status": "deleted"}


# ── Free/busy ────────────────────────────────────────────────────────────────

def free_busy(
    creds: Credentials,
    calendar_ids: list[str],
    time_min: str,
    time_max: str,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> dict:
    """Busy blocks across up to 50 calendars in ONE call.

    Works on calendars shared at free/busy-only permission, so a work calendar
    you don't own still blocks out availability. Returns {calendar_id: [(start, end), ...]}.
    A calendar that has been unshared fails SILENTLY per-item — check the
    "errors" key of the result rather than expecting an exception.
    """
    service = get_service(creds)
    result = service.freebusy().query(body={
        "timeMin": time_min,
        "timeMax": time_max,
        "timeZone": timezone_name,
        "items": [{"id": cid} for cid in calendar_ids],
    }).execute()
    out: dict = {}
    for cid, cal in result.get("calendars", {}).items():
        entry: dict = {"busy": [(b["start"], b["end"]) for b in cal.get("busy", [])]}
        if cal.get("errors"):
            entry["errors"] = cal["errors"]
        out[cid] = entry
    return out


def find_free_slots(
    creds: Credentials,
    calendar_ids: list[str],
    duration_minutes: int = 30,
    earliest: str | None = None,
    latest: str | None = None,
    working_hours: tuple[int, int] = (9, 18),
    buffer_minutes: int = 15,
    timezone_name: str = DEFAULT_TIMEZONE,
) -> list[dict]:
    """Candidate meeting slots across all given calendars, computed in Python.

    Queries free/busy for every calendar in one call, then subtracts busy
    blocks (plus a buffer each side) from the working-day window. Slot
    arithmetic is done here — not by the model — because that is where
    mid-sized models get subtly wrong.

    Args:
        calendar_ids: All calendars to respect (every calendar you live in).
        duration_minutes: Required slot length.
        earliest / latest: ISO 8601 bounds for the search window; default
            today → +7 days in the target timezone.
        working_hours: (start_hour, end_hour) in the target timezone.
        buffer_minutes: Breathing room kept clear either side of busy blocks.

    Returns a list of {"start", "end"} ISO 8601 dicts, soonest first, capped
    at 20. Never raises for individual calendar failures; query free_busy()
    directly if you need per-calendar error details.
    """
    from datetime import datetime, timedelta

    tz = ZoneInfo(timezone_name)
    now = datetime.now(tz)
    window_start = datetime.fromisoformat(earliest).astimezone(tz) if earliest else now
    window_end = (
        datetime.fromisoformat(latest).astimezone(tz) if latest
        else (window_start + timedelta(days=7))
    )
    if window_end <= window_start:
        raise ValueError("latest must be after earliest")

    busy_map = free_busy(
        creds, calendar_ids,
        window_start.isoformat(), window_end.isoformat(), timezone_name,
    )

    # Merge busy intervals from ALL calendars into one timeline (buffered).
    intervals: list[tuple[datetime, datetime]] = []
    for cal in busy_map.values():
        for b_start, b_end in cal["busy"]:
            s = datetime.fromisoformat(b_start).astimezone(tz) - timedelta(minutes=buffer_minutes)
            e = datetime.fromisoformat(b_end).astimezone(tz) + timedelta(minutes=buffer_minutes)
            intervals.append((s, e))
    intervals.sort()

    merged: list[list[datetime]] = []
    for s, e in intervals:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    # Walk day by day, subtract merged busy from each working window.
    duration = timedelta(minutes=duration_minutes)
    slots: list[dict] = []
    day = window_start.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < window_end and len(slots) < 20:
        wh_start = day + timedelta(hours=working_hours[0])
        wh_end = day + timedelta(hours=working_hours[1])
        cursor = max(wh_start, window_start)
        day_end = min(wh_end, window_end)
        for s, e in merged:
            if e <= cursor or s >= day_end:
                continue
            if s > cursor:
                gap = (min(s, day_end) - cursor).total_seconds()
                if gap >= duration.total_seconds():
                    slots.append({"start": cursor.isoformat(), "end": (cursor + duration).isoformat()})
                    if len(slots) >= 20:
                        break
            cursor = max(cursor, e)
            if cursor >= day_end:
                break
        if cursor < day_end and len(slots) < 20:
            gap = (day_end - cursor).total_seconds()
            if gap >= duration.total_seconds():
                slots.append({"start": cursor.isoformat(), "end": (cursor + duration).isoformat()})
        day += timedelta(days=1)

    return slots


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
