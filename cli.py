#!/usr/bin/env python3
"""CLI for managing Gmail MCP accounts.

Useful for the initial setup before Claude is connected:

    uv run python cli.py list
    uv run python cli.py add user@gmail.com
    uv run python cli.py remove user@gmail.com
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db
import auth


def main():
    if len(sys.argv) < 2:
        print("Gmail MCP CLI")
        print("")
        print("Usage:")
        print("  python cli.py list            - List authenticated accounts")
        print("  python cli.py add EMAIL       - Add and authenticate an account")
        print("  python cli.py remove EMAIL    - Remove an account")
        print("")
        print("Example:")
        print("  python cli.py add user@gmail.com")
        return

    command = sys.argv[1]

    if command == "list":
        accounts = db.list_accounts()
        if accounts:
            print("Authenticated accounts:")
            for acc in accounts:
                print(f"  - {acc}")
        else:
            print("No accounts authenticated.")

    elif command == "add":
        if len(sys.argv) < 3:
            print("Error: Please specify an email address")
            return
        email = sys.argv[2]
        print(f"Authenticating {email}...")
        print("A browser window will open. Please sign in with the correct Google account.")
        try:
            auth.authenticate_account(email)
            print(f"Successfully authenticated {email}")
        except Exception as e:
            print(f"Authentication failed: {e}")

    elif command == "remove":
        if len(sys.argv) < 3:
            print("Error: Please specify an email address")
            return
        email = sys.argv[2]
        if db.remove_account(email):
            print(f"Removed {email}")
        else:
            print(f"Account {email} not found")

    else:
        print(f"Unknown command: {command}")


if __name__ == "__main__":
    main()
