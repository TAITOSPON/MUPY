"""
Google Sheets integration using a Service Account.

Credentials are loaded from the GOOGLE_CREDENTIALS environment variable
(the full JSON content of the service account key) so that nothing secret
is ever committed to the repository. This works well on Render where you
set the value in the dashboard.

For local development you can instead place the key file at
./service_account.json and it will be used as a fallback.
"""

import json
import os
import threading

import gspread
from google.oauth2.service_account import Credentials

# Scopes required to read/write Google Sheets.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Header row written to the sheet the first time it is used.
HEADER = ["Timestamp", "Full name", "Email", "Phone", "Note"]

LOCAL_KEY_FILE = os.path.join(os.path.dirname(__file__), "service_account.json")

# gspread clients are not guaranteed thread-safe; guard sheet access.
_lock = threading.Lock()
_worksheet = None


def _load_credentials():
    """Build Credentials from env var JSON or a local key file."""
    raw = os.environ.get("GOOGLE_CREDENTIALS")
    if raw:
        info = json.loads(raw)
        return Credentials.from_service_account_info(info, scopes=SCOPES)

    if os.path.exists(LOCAL_KEY_FILE):
        return Credentials.from_service_account_file(LOCAL_KEY_FILE, scopes=SCOPES)

    raise RuntimeError(
        "No Google credentials found. Set the GOOGLE_CREDENTIALS environment "
        "variable to the service account JSON, or place service_account.json "
        "next to this file for local development."
    )


def _open_worksheet():
    """Open (and cache) the target worksheet, creating the header if needed."""
    creds = _load_credentials()
    client = gspread.authorize(creds)

    sheet_id = os.environ.get("SHEET_ID")
    sheet_name = os.environ.get("SHEET_NAME", "Sheet1")

    if not sheet_id:
        raise RuntimeError("The SHEET_ID environment variable is not set.")

    spreadsheet = client.open_by_key(sheet_id)
    worksheet = spreadsheet.worksheet(sheet_name)

    # Write the header row once if the sheet is empty.
    if not worksheet.get_all_values():
        worksheet.append_row(HEADER, value_input_option="USER_ENTERED")

    return worksheet


def get_worksheet():
    """Return the cached worksheet, opening it on first use."""
    global _worksheet
    if _worksheet is None:
        _worksheet = _open_worksheet()
    return _worksheet


def reset_worksheet():
    """Drop the cached worksheet so the next call reconnects.

    Useful after a transient API/auth error (e.g. Render waking from sleep
    or an expired token) so a retry can establish a fresh connection.
    """
    global _worksheet
    _worksheet = None


def append_user(timestamp, full_name, email, phone, note):
    """Append a single user record as a new row (reconnects once on failure)."""
    with _lock:
        try:
            worksheet = get_worksheet()
            worksheet.append_row(
                [timestamp, full_name, email, phone, note],
                value_input_option="USER_ENTERED",
            )
        except Exception:
            # Reconnect once in case the cached client went stale.
            reset_worksheet()
            worksheet = get_worksheet()
            worksheet.append_row(
                [timestamp, full_name, email, phone, note],
                value_input_option="USER_ENTERED",
            )


def email_exists(email):
    """Return True if the given email already exists in the sheet."""
    if not email:
        return False
    with _lock:
        try:
            worksheet = get_worksheet()
            existing = worksheet.col_values(3)
        except Exception:
            reset_worksheet()
            worksheet = get_worksheet()
            # Column 3 is the email column (1-indexed): Timestamp, Name, Email...
            existing = worksheet.col_values(3)
    existing_lower = {value.strip().lower() for value in existing[1:]}
    return email.strip().lower() in existing_lower
