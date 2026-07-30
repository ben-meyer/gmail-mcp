"""Centralized OAuth scope definitions.

Add new scope lists here and include them in ALL_SCOPES — auth.py and every
client module import from this single source of truth.
"""

# Gmail scopes — read, send, modify, label
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.labels",
]

# Calendar scopes — full read/write access to events and calendar list
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# All scopes requested at OAuth time. Existing accounts will be re-prompted
# the next time their token is refreshed if new scopes are added here.
ALL_SCOPES = list(GMAIL_SCOPES) + list(CALENDAR_SCOPES)
