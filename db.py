"""SQLite storage for Google OAuth tokens.

Service-agnostic: stores tokens keyed by email. The same table backs Gmail
today and will back Calendar (and any other Google API) later — the Calendar
extension simply adds its scopes to the same row.
"""

import os
import sqlite3
import json
from pathlib import Path
from datetime import datetime

# Override via DB_PATH env var — useful when running in Docker or on a server
# where the home directory isn't a reliable place for persistent data.
DB_PATH = Path(os.environ.get("DB_PATH", Path.home() / ".gmail-mcp-tokens.db"))


def get_connection():
    """Get database connection and ensure table exists."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            email TEXT PRIMARY KEY,
            access_token TEXT NOT NULL,
            refresh_token TEXT NOT NULL,
            token_expiry TEXT,
            scopes TEXT
        )
    """)
    conn.commit()
    return conn


def save_tokens(email: str,
                access_token: str,
                refresh_token: str,
                expiry: datetime | None = None,
                scopes: list[str] | None = None):
    """Save or update tokens for an account."""
    conn = get_connection()
    expiry_str = expiry.isoformat() if expiry else None
    scopes_str = json.dumps(scopes) if scopes else None
    conn.execute("""
        INSERT OR REPLACE INTO accounts
            (email, access_token, refresh_token, token_expiry, scopes)
        VALUES (?, ?, ?, ?, ?)
    """, (email, access_token, refresh_token, expiry_str, scopes_str))
    conn.commit()
    conn.close()


def get_tokens(email: str) -> dict | None:
    """Get tokens for an account."""
    conn = get_connection()
    cursor = conn.execute(
        "SELECT access_token, refresh_token, token_expiry, scopes "
        "FROM accounts WHERE email = ?",
        (email,),
    )
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "access_token": row[0],
        "refresh_token": row[1],
        "expiry": datetime.fromisoformat(row[2]) if row[2] else None,
        "scopes": json.loads(row[3]) if row[3] else None,
    }


def list_accounts() -> list[str]:
    """List all authenticated accounts."""
    conn = get_connection()
    cursor = conn.execute("SELECT email FROM accounts")
    accounts = [row[0] for row in cursor.fetchall()]
    conn.close()
    return accounts


def remove_account(email: str) -> bool:
    """Remove an account. Returns True if a row was deleted."""
    conn = get_connection()
    cursor = conn.execute("DELETE FROM accounts WHERE email = ?", (email,))
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted
