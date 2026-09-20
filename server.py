"""Gmail + Calendar MCP Gateway — multi-account access over HTTP.

Transport : streamable-http  (MCP endpoint at /mcp)
Auth      : Bearer token via GATEWAY_API_KEY env var
             — /health, /auth/start, /auth/callback are public (no key needed)
Accounts  : add via  GET /auth/start?email=you@gmail.com  from any browser,
             or via  python cli.py add you@gmail.com  when you have a terminal.
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import auth
import calendar_client
import db
import gmail_client

# ── Config ────────────────────────────────────────────────────────────────────
GATEWAY_API_KEY = os.environ.get("GATEWAY_API_KEY", "")
PORT = int(os.environ.get("PORT", "8000"))
HOST = os.environ.get("HOST", "0.0.0.0")

# ── MCP server ────────────────────────────────────────────────────────────────
mcp = FastMCP("gmail-gateway", host=HOST, port=PORT)


# ── API key ASGI middleware ───────────────────────────────────────────────────
class _APIKeyMiddleware:
    """Thin ASGI wrapper that enforces a Bearer token on all paths except the
    public ones (/health, /auth/*).  When GATEWAY_API_KEY is empty the server
    operates in dev-mode with no auth (a warning is printed at startup)."""

    _PUBLIC = frozenset({"/health", "/auth/start", "/auth/callback"})

    def __init__(self, app, api_key: str) -> None:
        self.app = app
        self.api_key = api_key

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and self.api_key:
            path = scope.get("path", "")
            if path not in self._PUBLIC:
                headers = dict(scope.get("headers", []))
                auth_header = headers.get(b"authorization", b"").decode()
                if auth_header != f"Bearer {self.api_key}":
                    res = Response(
                        "Unauthorized",
                        status_code=401,
                        headers={"WWW-Authenticate": "Bearer"},
                    )
                    await res(scope, receive, send)
                    return
        await self.app(scope, receive, send)


# ─────────────────────────────────────────────────────────────────────────────
# Account management
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_accounts() -> str:
    """List all authenticated Google accounts on this gateway."""
    accounts = db.list_accounts()
    if not accounts:
        return (
            "No accounts authenticated.\n"
            "Add one by visiting: GET /auth/start?email=you@gmail.com"
        )
    return "Authenticated accounts:\n" + "\n".join(f"- {a}" for a in accounts)


@mcp.tool()
def get_auth_link(email: str) -> str:
    """Get the URL to authenticate a new Google account via the browser.

    Open the returned URL to grant the gateway access to Gmail and Calendar.

    Args:
        email: The Google address to authenticate (e.g. you@gmail.com)
    """
    return (
        f"Open this path in a browser pointed at your gateway:\n\n"
        f"  /auth/start?email={email}\n\n"
        f"Example: http://<gateway-host>:{PORT}/auth/start?email={email}"
    )


@mcp.tool()
def remove_account(email: str) -> str:
    """Remove an authenticated account from the gateway.

    Args:
        email: The Google address to remove
    """
    if db.remove_account(email):
        return f"Removed {email}"
    return f"Account {email} not found"


# ─────────────────────────────────────────────────────────────────────────────
# Gmail tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def search_emails(account: str, query: str, max_results: int = 10) -> str:
    """Search emails in a Gmail account.

    Args:
        account: Gmail address to search in
        query: Gmail search query (e.g. "is:unread", "from:alice@example.com",
            "subject:hello after:2024/01/01")
        max_results: Maximum number of results (default 10)
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated. Use get_auth_link() first."
    try:
        messages = gmail_client.search_messages(creds, query, max_results)
        if not messages:
            return f"No emails found matching: {query}"
        result = f"Found {len(messages)} emails:\n\n"
        for msg in messages:
            result += f"ID: {msg['id']}\n"
            result += f"Subject: {msg['subject']}\n"
            result += f"From: {msg['from']}\n"
            result += f"Date: {msg['date']}\n"
            result += f"Preview: {msg['snippet']}...\n"
            result += "-" * 40 + "\n"
        return result
    except Exception as e:
        return f"Error searching emails: {e}"


@mcp.tool()
def read_email(account: str, message_id: str) -> str:
    """Read the full content of an email.

    Args:
        account: Gmail address
        message_id: The email ID (from search_emails results)
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        msg = gmail_client.get_message(creds, message_id)
        result = f"Subject: {msg['subject']}\n"
        result += f"From: {msg['from']}\n"
        result += f"To: {msg['to']}\n"
        if msg["cc"]:
            result += f"CC: {msg['cc']}\n"
        result += f"Date: {msg['date']}\n"
        result += f"Labels: {', '.join(msg['labels'])}\n"
        result += "\n--- Body ---\n\n"
        result += msg["body"]
        return result
    except Exception as e:
        return f"Error reading email: {e}"


@mcp.tool()
def send_email(
    account: str,
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
) -> str:
    """Send an email from a Gmail account.

    Args:
        account: Gmail address to send from
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
        cc: CC recipients (optional)
        bcc: BCC recipients (optional)
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        result = gmail_client.send_message(creds, to, subject, body, cc, bcc)
        return f"Email sent. Message ID: {result['id']}"
    except Exception as e:
        return f"Error sending email: {e}"


@mcp.tool()
def get_labels(account: str) -> str:
    """Get all labels/folders for a Gmail account.

    Args:
        account: Gmail address
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        labels = gmail_client.get_labels(creds)
        return "Labels:\n" + "\n".join(
            f"- {lb['name']} (ID: {lb['id']})" for lb in labels
        )
    except Exception as e:
        return f"Error getting labels: {e}"


@mcp.tool()
def archive_email(account: str, message_id: str) -> str:
    """Archive an email (remove from inbox).

    Args:
        account: Gmail address
        message_id: The email ID to archive
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        gmail_client.modify_labels(creds, message_id, remove_labels=["INBOX"])
        return f"Email {message_id} archived."
    except Exception as e:
        return f"Error archiving email: {e}"


@mcp.tool()
def mark_as_read(account: str, message_id: str) -> str:
    """Mark an email as read.

    Args:
        account: Gmail address
        message_id: The email ID
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        gmail_client.modify_labels(creds, message_id, remove_labels=["UNREAD"])
        return f"Email {message_id} marked as read."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def mark_as_unread(account: str, message_id: str) -> str:
    """Mark an email as unread.

    Args:
        account: Gmail address
        message_id: The email ID
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        gmail_client.modify_labels(creds, message_id, add_labels=["UNREAD"])
        return f"Email {message_id} marked as unread."
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def label_email(account: str, message_id: str, label_name: str) -> str:
    """Apply a label to an email by label name (case-insensitive match).

    Args:
        account: Gmail address
        message_id: The email ID
        label_name: The label name to apply
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        labels = gmail_client.get_labels(creds)
        label = next(
            (l for l in labels if l["name"].lower() == label_name.lower()), None
        )
        if not label:
            available = ", ".join(l["name"] for l in labels if l["type"] == "user")
            return (
                f"Label '{label_name}' not found.\n"
                f"Available user labels: {available}\n"
                f"Use get_or_create_label() to create it first."
            )
        gmail_client.modify_labels(creds, message_id, add_labels=[label["id"]])
        return f"Applied label '{label['name']}' to message {message_id}."
    except Exception as e:
        return f"Error applying label: {e}"


@mcp.tool()
def get_or_create_label(account: str, label_name: str) -> str:
    """Get a label ID by name, creating the label if it doesn't exist.

    Useful for ensuring a label exists before applying it in bulk.

    Args:
        account: Gmail address
        label_name: Label name to find or create
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        labels = gmail_client.get_labels(creds)
        label = next(
            (l for l in labels if l["name"].lower() == label_name.lower()), None
        )
        if label:
            return f"Label '{label['name']}' exists (ID: {label['id']})"
        new_label = gmail_client.create_label(creds, label_name)
        return f"Label '{new_label['name']}' created (ID: {new_label['id']})"
    except Exception as e:
        return f"Error: {e}"


# ─────────────────────────────────────────────────────────────────────────────
# Calendar tools
# ─────────────────────────────────────────────────────────────────────────────

@mcp.tool()
def list_calendars(account: str) -> str:
    """List all calendars for a Google account.

    Args:
        account: Google address
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        cals = calendar_client.list_calendars(creds)
        if not cals:
            return "No calendars found."
        result = f"Calendars for {account}:\n\n"
        for c in cals:
            primary = " (primary)" if c["primary"] else ""
            result += f"- {c['name']}{primary}\n  ID: {c['id']}\n"
        return result
    except Exception as e:
        return f"Error listing calendars: {e}"


@mcp.tool()
def list_events(
    account: str,
    days_ahead: int = 7,
    calendar_id: str = "primary",
    max_results: int = 20,
    query: str = "",
) -> str:
    """List upcoming calendar events.

    Args:
        account: Google address
        days_ahead: How many days ahead to look (default 7)
        calendar_id: Calendar ID (default "primary"); use list_calendars to find IDs
        max_results: Maximum events to return (default 20)
        query: Optional free-text search within events
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        now = datetime.now(timezone.utc)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=days_ahead)).isoformat()
        events = calendar_client.list_events(
            creds, calendar_id, time_min, time_max, max_results, query or None
        )
        if not events:
            return f"No events in the next {days_ahead} days."
        result = f"Events in the next {days_ahead} days ({len(events)} found):\n\n"
        for e in events:
            result += f"Title: {e['summary']}\n"
            result += f"ID:    {e['id']}\n"
            result += f"Start: {e['start']}\n"
            result += f"End:   {e['end']}\n"
            if e["location"]:
                result += f"Where: {e['location']}\n"
            if e["attendees"]:
                result += f"With:  {', '.join(e['attendees'])}\n"
            result += "-" * 40 + "\n"
        return result
    except Exception as e:
        return f"Error listing events: {e}"


@mcp.tool()
def find_free_slots(
    account: str,
    duration_minutes: int = 30,
    earliest: str = "",
    latest: str = "",
    calendar_ids: str = "",
) -> str:
    """Find free meeting slots across ALL of an account's calendars in one
    free/busy call — including calendars shared at free/busy-only (e.g. a work
    calendar), which list_events cannot see. Busy blocks from every calendar
    are merged, working hours (09:00-18:00 Europe/London) and 15-minute
    buffers are honoured, and slot arithmetic is done in code, not by the model.

    Args:
        account: Google address
        duration_minutes: Required slot length (default 30)
        earliest: Optional ISO 8601 lower bound (default: now)
        latest: Optional ISO 8601 upper bound (default: earliest + 7 days)
        calendar_ids: Optional comma-separated calendar IDs to check. Default:
            every calendar on the account (recommended — that is the point).
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        ids = (
            [c.strip() for c in calendar_ids.split(",") if c.strip()]
            if calendar_ids
            else [c["id"] for c in calendar_client.list_calendars(creds)]
        )
        if not ids:
            return "No calendars found for this account."
        slots = calendar_client.find_free_slots(
            creds, ids, duration_minutes=duration_minutes,
            earliest=earliest or None, latest=latest or None,
        )
        if not slots:
            return "No free slots found in the requested window."
        result = f"Free slots ({duration_minutes} min, next {len(slots)}):\n\n"
        for s in slots:
            result += f"- {s['start']} → {s['end']}\n"
        return result
    except Exception as e:
        return f"Error finding free slots: {e}"


@mcp.tool()
def get_event(account: str, event_id: str, calendar_id: str = "primary") -> str:
    """Get full details of a calendar event.

    Args:
        account: Google address
        event_id: Event ID (from list_events results)
        calendar_id: Calendar ID (default "primary")
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        e = calendar_client.get_event(creds, event_id, calendar_id)
        result = f"Title:     {e['summary']}\n"
        result += f"Start:     {e['start']}\n"
        result += f"End:       {e['end']}\n"
        result += f"Status:    {e['status']}\n"
        result += f"Organizer: {e['organizer']}\n"
        if e["location"]:
            result += f"Location:  {e['location']}\n"
        if e["description"]:
            result += f"\nDescription:\n{e['description']}\n"
        if e["attendees"]:
            result += "\nAttendees:\n"
            for a in e["attendees"]:
                result += f"  - {a['email']} ({a['status']})\n"
        if e["link"]:
            result += f"\nCalendar link: {e['link']}\n"
        return result
    except Exception as e:
        return f"Error getting event: {e}"


@mcp.tool()
def create_event(
    account: str,
    summary: str,
    start_datetime: str,
    end_datetime: str,
    calendar_id: str = "primary",
    description: str = "",
    location: str = "",
    attendee_emails: str = "",
    timezone_name: str = "Europe/London",
    send_invites: bool = False,
) -> str:
    """Create a new calendar event. NOT sent to attendees unless send_invites
    is explicitly true — created events stay local until then.

    Args:
        account: Google address
        summary: Event title
        start_datetime: ISO 8601, e.g. "2024-06-15T14:00:00" (local, resolved
            against timezone_name) or "2024-06-15T14:00:00Z" (explicit UTC)
        end_datetime: Same format as start_datetime
        calendar_id: Calendar to create in (default "primary")
        description: Event description (optional)
        location: Location or video link (optional)
        attendee_emails: Comma-separated email addresses to invite (optional)
        timezone_name: IANA timezone for the event (default Europe/London)
        send_invites: Set true ONLY when Ben has confirmed the event should
            email its attendees. Default false.
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        attendees = (
            [a.strip() for a in attendee_emails.split(",") if a.strip()]
            if attendee_emails
            else []
        )
        result = calendar_client.create_event(
            creds, summary, start_datetime, end_datetime,
            calendar_id, description, location, attendees,
            timezone_name=timezone_name, send_invites=send_invites,
        )
        gate = "with invites sent" if (attendees and send_invites) else "WITHOUT invites (local only)"
        return f"Event created ({gate}).\nID:   {result['id']}\nLink: {result['link']}"
    except Exception as e:
        return f"Error creating event: {e}"


@mcp.tool()
def update_event(
    account: str,
    event_id: str,
    calendar_id: str = "primary",
    summary: str = "",
    description: str = "",
    location: str = "",
    start_datetime: str = "",
    end_datetime: str = "",
    timezone_name: str = "Europe/London",
    send_invites: bool = False,
) -> str:
    """Update a calendar event. Only fields you supply are changed. Attendees
    are NOT emailed about the change unless send_invites is explicitly true.

    Args:
        account: Google address
        event_id: Event ID to update
        calendar_id: Calendar ID (default "primary")
        summary: New title (optional)
        description: New description (optional)
        location: New location (optional)
        start_datetime: New start, ISO 8601 (optional; resolved against timezone_name)
        end_datetime: New end, ISO 8601 (optional)
        timezone_name: IANA timezone for supplied datetimes (default Europe/London)
        send_invites: Set true ONLY when Ben has confirmed the change should
            email its attendees. Default false.
    """
    creds = auth.get_credentials(account)
    if not creds:
        return f"Account {account} not authenticated."
    try:
        kwargs: dict = {}
        if summary:        kwargs["summary"] = summary
        if description:    kwargs["description"] = description
        if location:       kwargs["location"] = location
        if start_datetime: kwargs["start_dt"] = start_datetime
        if end_datetime:   kwargs["end_dt"] = end_datetime
        if not kwargs:
            return "No fields to update were provided."
        calendar_client.update_event(
            creds, event_id, calendar_id,
            timezone_name=timezone_name, send_invites=send_invites, **kwargs,
        )
        return f"Event {event_id} updated."
    except Exception as e:
        return f"Error updating event: {e}"


# delete_event is deliberately NOT exposed as an MCP tool during the trial:
# a model mistake here emails cancellation notices to other people's inboxes
# (it sent unconditionally before the send-gate fix). The underlying
# calendar_client.delete_event() now defaults to sendUpdates="none" and
# remains available for scripted/CLI use once trust is earned — re-add the
# tool wrapper then, alongside send_email, per the staged rollout in the
# setup guide (Part 6d/6e).


# ─────────────────────────────────────────────────────────────────────────────
# Custom HTTP routes  (no API key required — public by design)
# ─────────────────────────────────────────────────────────────────────────────

@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    """Health check — useful for monitoring and confirming the gateway is up."""
    return JSONResponse({"status": "ok", "accounts": db.list_accounts(), "port": PORT})


@mcp.custom_route("/auth/start", methods=["GET"])
async def auth_start(request: Request) -> Response:
    """Kick off the Google OAuth flow.

    Usage: GET /auth/start?email=you@gmail.com
    Redirects to Google's consent screen; on approval lands on /auth/callback.
    """
    email = request.query_params.get("email", "").strip()
    if not email:
        return HTMLResponse(
            "<h2>Missing parameter</h2><p>Usage: /auth/start?email=you@gmail.com</p>",
            status_code=400,
        )
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/callback"
    try:
        url = auth.get_auth_url(email, redirect_uri)
        return RedirectResponse(url)
    except Exception as e:
        return HTMLResponse(f"<h2>Error</h2><p>{e}</p>", status_code=500)


@mcp.custom_route("/auth/callback", methods=["GET"])
async def auth_callback(request: Request) -> Response:
    """Google redirects here after the user grants consent."""
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    if not code or not state:
        return HTMLResponse(
            "<h2>Error</h2><p>Missing code or state — did the OAuth flow complete?</p>",
            status_code=400,
        )
    redirect_uri = str(request.base_url).rstrip("/") + "/auth/callback"
    try:
        email = auth.exchange_code(code, state, redirect_uri)
        return HTMLResponse(
            f"<h2>✅ {email} connected</h2>"
            f"<p>The gateway now has access to Gmail and Calendar for this account.</p>"
            f"<p>You can close this tab.</p>"
        )
    except Exception as e:
        return HTMLResponse(f"<h2>Auth error</h2><p>{e}</p>", status_code=400)


# ─────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    if not GATEWAY_API_KEY:
        print("⚠️  GATEWAY_API_KEY not set — running without auth (dev mode only)")
    else:
        print("🔐 API key auth enabled")

    print(f"🚀 MCP endpoint  → http://{HOST}:{PORT}/mcp")
    print(f"🩺 Health check  → http://{HOST}:{PORT}/health")
    print(f"🔑 Add account   → http://{HOST}:{PORT}/auth/start?email=you@gmail.com")

    app = _APIKeyMiddleware(mcp.streamable_http_app(), GATEWAY_API_KEY)
    uvicorn.run(app, host=HOST, port=PORT, log_level="info")
