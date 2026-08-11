"""OAuth2 authentication for Google APIs (Gmail + Calendar).

Two flows are supported:

  InstalledAppFlow  — opens a browser on the local machine.
                      Use via:  python cli.py add you@gmail.com
                      Best for first-time setup when you have a terminal.

  Web flow          — browser-redirect OAuth suitable for a remote server.
                      Use via:  GET /auth/start?email=you@gmail.com
                      The server redirects to Google, Google redirects back
                      to /auth/callback, tokens are saved automatically.
"""

import os
import json
import secrets
from pathlib import Path
from datetime import datetime
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow, InstalledAppFlow

from db import save_tokens, get_tokens
from scopes import ALL_SCOPES

OAUTH_CREDENTIALS = Path(__file__).resolve().parent / ".gmail-mcp-oauth.json"

# In-memory map of  state -> {email, code_verifier}  for the web OAuth flow.
# Entries are consumed on callback. No expiry needed for a personal gateway.
# code_verifier is required because google-auth-oauthlib enables PKCE by default:
# the verifier lives on the Flow object that generated the authorization URL,
# so we must carry it to the callback where we build a second Flow.
_pending_auth: dict[str, dict] = {}


def get_oauth_config() -> dict:
    """Load the OAuth client config (client_id / client_secret).

    Tries .gmail-mcp-oauth.json first (the file downloaded from Google Cloud
    Console), then falls back to GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET env vars.
    """
    if OAUTH_CREDENTIALS.exists():
        return json.loads(OAUTH_CREDENTIALS.read_text())

    client_id = os.environ.get("GOOGLE_CLIENT_ID")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET")

    if client_id and client_secret:
        return {
            "web": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [],
            }
        }

    raise ValueError(
        "No OAuth credentials found. Set GOOGLE_CLIENT_ID and "
        "GOOGLE_CLIENT_SECRET, or save the JSON from Google Cloud Console as "
        f"{OAUTH_CREDENTIALS}."
    )


# ── Local (InstalledApp) flow ─────────────────────────────────────────────────

def authenticate_account(email: str) -> Credentials:
    """Run the OAuth consent flow locally, opening a browser window.

    Persists tokens and returns the Credentials object.
    Use this via cli.py when you have terminal access to the machine.
    """
    config = get_oauth_config()
    # InstalledAppFlow needs the "installed" key; patch if config has "web".
    if "web" in config and "installed" not in config:
        installed_config = {"installed": {**config["web"], "redirect_uris": ["http://localhost"]}}
    else:
        installed_config = config

    flow = InstalledAppFlow.from_client_config(installed_config, ALL_SCOPES)
    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        authorization_prompt_message=f"Please sign in with: {email}",
    )
    _persist(email, creds)
    return creds


# ── Web (redirect) flow ───────────────────────────────────────────────────────

def get_auth_url(email: str, redirect_uri: str) -> str:
    """Generate a Google OAuth consent URL for the web flow.

    Call this from the /auth/start route.  The returned URL sends the browser
    to Google; on approval Google redirects to redirect_uri with a code and
    state parameter that exchange_code() then handles.

    Args:
        email: Hint shown on Google's sign-in screen
        redirect_uri: Must match a URI registered in Google Cloud Console
    """
    config = get_oauth_config()
    flow = Flow.from_client_config(config, ALL_SCOPES, redirect_uri=redirect_uri)
    state = secrets.token_urlsafe(16)
    auth_url, _ = flow.authorization_url(
        prompt="consent",
        access_type="offline",
        login_hint=email,
        state=state,
    )
    _pending_auth[state] = {"email": email, "code_verifier": flow.code_verifier}
    return auth_url


def exchange_code(code: str, state: str, redirect_uri: str) -> str:
    """Complete the web OAuth flow: exchange the code for tokens.

    Call this from the /auth/callback route.

    Returns:
        The email address that was authenticated.
    Raises:
        ValueError: If the state is unknown or already consumed.
    """
    entry = _pending_auth.pop(state, None)
    if entry is None:
        raise ValueError("Unknown or already-used OAuth state. Try /auth/start again.")
    email = entry["email"]

    config = get_oauth_config()
    flow = Flow.from_client_config(config, ALL_SCOPES, redirect_uri=redirect_uri)
    flow.code_verifier = entry["code_verifier"]
    flow.fetch_token(code=code)
    _persist(email, flow.credentials)
    return email


# ── Shared helpers ────────────────────────────────────────────────────────────

def _persist(email: str, creds: Credentials) -> None:
    """Save tokens to the database."""
    save_tokens(
        email=email,
        access_token=creds.token,
        refresh_token=creds.refresh_token,
        expiry=creds.expiry,
        scopes=list(creds.scopes) if creds.scopes else ALL_SCOPES,
    )


def get_credentials(email: str) -> Optional[Credentials]:
    """Return Credentials for an account, refreshing the access token if needed.

    Returns None if the account has not been authenticated yet.
    """
    tokens = get_tokens(email)
    if not tokens:
        return None

    config = get_oauth_config()
    # Support both "installed" and "web" config shapes.
    client_cfg = config.get("installed") or config.get("web", {})

    creds = Credentials(
        token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_cfg["client_id"],
        client_secret=client_cfg["client_secret"],
        scopes=tokens["scopes"] or ALL_SCOPES,
    )

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _persist(email, creds)

    return creds
