"""Centralized OAuth scope definitions.

Add new scope lists here and include them in ALL_SCOPES — auth.py and every
client module import from this single source of truth.
"""

# Gmail scopes — gmail.modify is a superset of readonly+labels, so requesting
# those separately only widens the consent screen, not the access.
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# Calendar scopes — full access to events and calendar list ("calendar" is a
# superset of "calendar.events").
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
]

# All scopes requested at OAuth time. NOTE: trimming this list forces
# re-consent on every account (tokens keep their original scope set until
# re-authed — get_credentials reads scopes back from the DB row).
ALL_SCOPES = list(GMAIL_SCOPES) + list(CALENDAR_SCOPES)
