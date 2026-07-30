# gmail-mcp — Personal Gmail + Calendar MCP Gateway

A self-hosted MCP server that gives any AI agent unified access to your Gmail
and Google Calendar over HTTP. Designed to run on a Raspberry Pi (or any
always-on machine) and be reachable from Claude desktop, mobile, and OpenClaw
via Tailscale.

```
any agent  ──Bearer token──▶  Pi (Tailscale)  ──Google OAuth──▶  Gmail / Calendar
                               port 8000/mcp
```

## Features

- **15 MCP tools** — Gmail search/read/send/label/archive + Calendar list/get/create/update/delete
- **Multi-account** — authenticate as many Google accounts as you like; each tool takes an `account` argument
- **Web OAuth** — add accounts by visiting `/auth/start?email=...` in a browser; no terminal needed after setup
- **API key auth** — all `/mcp` traffic requires a Bearer token; `/health` and `/auth/*` are intentionally public
- **Docker or systemd** — both deployment modes documented below

## Project layout

```
gmail-mcp/
├── server.py           MCP entrypoint — HTTP transport, API key middleware, auth routes
├── auth.py             OAuth2 — both local (InstalledApp) and web (redirect) flows
├── gmail_client.py     Gmail API wrapper
├── calendar_client.py  Calendar API wrapper
├── db.py               SQLite token store (service-agnostic)
├── scopes.py           Centralized scope constants
├── cli.py              CLI for local account management
├── Dockerfile
├── docker-compose.yml
├── deploy/
│   └── gmail-mcp.service  systemd unit for bare-Pi deployment
├── .env.example
└── pyproject.toml
```

---

## One-time Google Cloud setup

### 1. Create a project and enable APIs

1. Go to <https://console.cloud.google.com/> → create a new project.
2. **APIs & Services → Library** — enable both:
   - **Gmail API**
   - **Google Calendar API**

### 2. Configure the OAuth consent screen

**APIs & Services → OAuth consent screen**

- User type: **External**
- App name + your email
- Scopes to add: `gmail.readonly`, `gmail.send`, `gmail.modify`, `gmail.labels`, `calendar`, `calendar.events`
- Test users: add your Gmail address(es)

> **Important — publish the app to avoid 7-day token expiry:**
> After saving the consent screen, click **Publish App** → confirm.
> Your tokens will now be long-lived. You'll see an "unverified app" warning
> the first time you sign in — that's expected and fine for a personal gateway.
> Google's review process only applies to apps distributed to other users.

### 3. Create OAuth credentials

**APIs & Services → Credentials → Create credentials → OAuth client ID**

- Application type: **Web application** (needed for the `/auth/callback` redirect flow)
- Authorised redirect URIs — add your gateway's callback URL.
  With Tailscale this will look like:
  `https://your-machine.your-tailnet.ts.net:8000/auth/callback`
  Add `http://localhost:8000/auth/callback` too for local testing.

Download the JSON. You'll use it in the next step.

---

## Raspberry Pi deployment (recommended)

### Option A — Docker Compose

```bash
# On your Pi:
git clone <your-fork> gmail-mcp && cd gmail-mcp

# Credentials — pick one:
#   A) drop the downloaded JSON here:
cp ~/Downloads/client_secret_*.json .gmail-mcp-oauth.json
#   B) or set env vars in .env

cp .env.example .env
# Edit .env:
#   GATEWAY_API_KEY=<run: python3 -c "import secrets; print(secrets.token_urlsafe(32))">

mkdir data
docker compose up -d
```

### Option B — systemd (bare Pi, no Docker)

```bash
# On your Pi:
git clone <your-fork> /home/pi/gmail-mcp && cd /home/pi/gmail-mcp
cp .gmail-mcp-oauth.json /home/pi/gmail-mcp/   # your downloaded JSON

uv sync   # creates .venv automatically

# Create the env file for the service
sudo cp .env.example /etc/gmail-mcp.env
sudo nano /etc/gmail-mcp.env   # fill in GATEWAY_API_KEY

# Install and start the service
sudo cp deploy/gmail-mcp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now gmail-mcp

# Check it's running
sudo systemctl status gmail-mcp
curl http://localhost:8000/health
```

---

## Networking — Tailscale (strongly recommended)

Tailscale gives you a private, encrypted, zero-config VPN that works on your
phone, laptop, and Pi without port forwarding. It's free for personal use.

```bash
# On your Pi:
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up

# On your Mac / iPhone: install Tailscale from tailscale.com
# Once connected, your Pi is reachable as:
#   http://pi-hostname.your-tailnet.ts.net:8000
```

For HTTPS (needed for some MCP clients that require `https://` URLs):

```bash
# Enable Tailscale's built-in HTTPS on your Pi:
sudo tailscale serve --bg https / http://127.0.0.1:8000
# Your gateway is now at: https://your-pi.your-tailnet.ts.net/mcp
```

---

## Authenticate your Google accounts

After the server is running, open a browser and visit:

```
http://your-pi.local:8000/auth/start?email=you@gmail.com
```

You'll be redirected to Google's consent screen. After approving, the page
shows "✅ you@gmail.com connected". Repeat for each account.

To check which accounts are connected: `GET /health`

---

## Connect to Claude and other agents

### Claude.ai (desktop + mobile)

Settings → Integrations → Add MCP server

| Field | Value |
|---|---|
| URL | `https://your-pi.your-tailnet.ts.net/mcp` |
| API key | your `GATEWAY_API_KEY` |

The mobile Claude app uses the same integration — once added on desktop it
syncs automatically.

### Claude Code (CLI)

Add to `~/.claude/claude_code_config.json`:

```json
{
  "mcpServers": {
    "gmail-gateway": {
      "type": "http",
      "url": "https://your-pi.your-tailnet.ts.net/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_GATEWAY_API_KEY"
      }
    }
  }
}
```

### OpenClaw / other MCP clients

Any client that supports remote MCP servers over `streamable-http` (the
current MCP transport standard) can point at `https://your-pi.../mcp` with
`Authorization: Bearer <key>` in the headers.

---

## Available MCP tools

### Account management

| Tool | Description |
|---|---|
| `list_accounts` | List all authenticated Google accounts |
| `get_auth_link(email)` | Return the URL to authenticate a new account |
| `remove_account(email)` | Remove an account from the gateway |

### Gmail

| Tool | Description |
|---|---|
| `search_emails(account, query, max_results)` | Gmail search (`is:unread`, `from:`, `subject:`, etc.) |
| `read_email(account, message_id)` | Full email body + headers |
| `send_email(account, to, subject, body, cc, bcc)` | Send an email |
| `get_labels(account)` | List all labels / folders |
| `archive_email(account, message_id)` | Remove from Inbox |
| `mark_as_read(account, message_id)` | Remove UNREAD label |
| `mark_as_unread(account, message_id)` | Add UNREAD label |

### Calendar

| Tool | Description |
|---|---|
| `list_calendars(account)` | List all calendars |
| `list_events(account, days_ahead, calendar_id, max_results, query)` | Upcoming events |
| `get_event(account, event_id, calendar_id)` | Full event details |
| `create_event(account, summary, start_datetime, end_datetime, ...)` | Create event (ISO 8601 UTC) |
| `update_event(account, event_id, ...)` | Update fields on an existing event |
| `delete_event(account, event_id, calendar_id)` | Delete an event |

---

## Local development

```bash
uv sync
cp .env.example .env  # set GATEWAY_API_KEY= (empty = no auth in dev)
cp your-oauth.json .gmail-mcp-oauth.json
uv run python server.py
# Server: http://localhost:8000/mcp
# Auth:   http://localhost:8000/auth/start?email=you@gmail.com
```

Add accounts locally via CLI (opens a browser on your machine):

```bash
uv run python cli.py add you@gmail.com
uv run python cli.py list
```

---

## Troubleshooting

**Tokens expire after 7 days** — your OAuth app is still in "Testing" mode.
Publish it (OAuth consent screen → Publish App) to get long-lived tokens.

**"Access blocked" from Google** — add your email as a test user
(APIs & Services → OAuth consent screen → Test users).

**`refresh_token` missing** — revoke access at
<https://myaccount.google.com/permissions> then re-auth via `/auth/start`.

**401 Unauthorized on `/mcp`** — check the `Authorization: Bearer <key>`
header matches `GATEWAY_API_KEY` exactly.

**Calendar scope not available** — existing tokens were issued before Calendar
scopes were added. Remove the account and re-authenticate via `/auth/start`.
