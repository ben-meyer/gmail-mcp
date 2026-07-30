"""Gmail API client wrapper.

Thin layer over googleapiclient. No MCP, no auth flow — just the Gmail
operations the MCP tools need. A future calendar_client.py will sit
alongside this file and follow the same shape.
"""

import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


def get_service(creds: Credentials):
    """Build the Gmail API service object."""
    return build("gmail", "v1", credentials=creds)


def search_messages(creds: Credentials, query: str,
                    max_results: int = 10) -> list[dict]:
    """Search for emails matching a Gmail query string.

    Two-step: list returns IDs only, then we fetch metadata for each.
    """
    service = get_service(creds)
    results = service.users().messages().list(
        userId="me", q=query, maxResults=max_results
    ).execute()

    messages = results.get("messages", [])
    summaries = []
    for msg in messages:
        detail = service.users().messages().get(
            userId="me",
            id=msg["id"],
            format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute()

        headers = {
            h["name"]: h["value"]
            for h in detail.get("payload", {}).get("headers", [])
        }
        summaries.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId"),
            "subject": headers.get("Subject", "(no subject)"),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "snippet": detail.get("snippet", "")[:100],
        })
    return summaries


def _extract_body(payload: dict) -> str:
    """Recursively pull the best text body out of a MIME payload."""
    if "body" in payload and payload["body"].get("data"):
        return base64.urlsafe_b64decode(
            payload["body"]["data"]
        ).decode("utf-8", errors="replace")

    if "parts" in payload:
        plain_text = ""
        html_text = ""
        for part in payload["parts"]:
            mime = part.get("mimeType", "")
            if mime.startswith("multipart/"):
                result = _extract_body(part)
                if result:
                    return result
            elif mime == "text/plain" and part.get("body", {}).get("data"):
                plain_text = base64.urlsafe_b64decode(
                    part["body"]["data"]
                ).decode("utf-8", errors="replace")
            elif (mime == "text/html"
                  and part.get("body", {}).get("data")
                  and not html_text):
                html_text = base64.urlsafe_b64decode(
                    part["body"]["data"]
                ).decode("utf-8", errors="replace")
        return plain_text or html_text
    return ""


def get_message(creds: Credentials, message_id: str) -> dict:
    """Get the full content of an email by ID."""
    service = get_service(creds)
    msg = service.users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()

    headers = {
        h["name"]: h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }
    payload = msg.get("payload", {})
    body = _extract_body(payload)

    return {
        "id": msg["id"],
        "thread_id": msg.get("threadId"),
        "subject": headers.get("Subject", "(no subject)"),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "cc": headers.get("Cc", ""),
        "date": headers.get("Date", ""),
        "body": body,
        "labels": msg.get("labelIds", []),
    }


def send_message(creds: Credentials, to: str, subject: str, body: str,
                 cc: str = "", bcc: str = "", reply_to: str = "") -> dict:
    """Send an email. reply_to should be the In-Reply-To message ID."""
    service = get_service(creds)
    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc
    if reply_to:
        message["In-Reply-To"] = reply_to
        message["References"] = reply_to
    message.attach(MIMEText(body, "plain"))

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    result = service.users().messages().send(
        userId="me", body={"raw": raw}
    ).execute()
    return {
        "id": result["id"],
        "thread_id": result.get("threadId"),
        "status": "sent",
    }


def get_labels(creds: Credentials) -> list[dict]:
    """List all labels on the account."""
    service = get_service(creds)
    results = service.users().labels().list(userId="me").execute()
    labels = results.get("labels", [])
    return [
        {"id": l["id"], "name": l["name"], "type": l.get("type", "")}
        for l in labels
    ]


def create_label(creds: Credentials, name: str) -> dict:
    """Create a new label in the account."""
    service = get_service(creds)
    result = service.users().labels().create(
        userId="me",
        body={"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"},
    ).execute()
    return {"id": result["id"], "name": result["name"]}


def modify_labels(creds: Credentials, message_id: str,
                  add_labels: list[str] | None = None,
                  remove_labels: list[str] | None = None) -> dict:
    """Add or remove labels on a message.

    Common patterns:
        archive  -> remove_labels=["INBOX"]
        mark read   -> remove_labels=["UNREAD"]
        mark unread -> add_labels=["UNREAD"]
    """
    service = get_service(creds)
    body: dict = {}
    if add_labels:
        body["addLabelIds"] = add_labels
    if remove_labels:
        body["removeLabelIds"] = remove_labels

    result = service.users().messages().modify(
        userId="me", id=message_id, body=body
    ).execute()
    return {
        "id": result["id"],
        "labels": result.get("labelIds", []),
    }
