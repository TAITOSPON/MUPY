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

# รายการยาสำหรับหน้าสั่งจองล่วงหน้า (pre-order).
# แก้ไข/เพิ่มรายการได้ที่นี่ที่เดียว หน้าเว็บจะอัปเดตตาม.
# แต่ละรายการมี "name" (ชื่อที่แสดง + บันทึกลงชีต) และ "image"
# (ชื่อไฟล์รูปใน static/images/). ถ้าไฟล์รูปไม่มี หน้าเว็บจะใช้ placeholder แทน.
MEDICINES = [
    {"name": "พาราเซตามอล (Paracetamol) 500mg", "image": "paracetamol.svg"},
    {"name": "ไอบูโพรเฟน (Ibuprofen) 400mg", "image": "ibuprofen.svg"},
    {"name": "อะม็อกซีซิลลิน (Amoxicillin) 500mg", "image": "amoxicillin.svg"},
    {"name": "ยาแก้แพ้ (Cetirizine) 10mg", "image": "cetirizine.svg"},
    {"name": "ยาลดกรด (Antacid)", "image": "antacid.svg"},
    {"name": "วิตามินซี (Vitamin C) 1000mg", "image": "vitamin-c.svg"},
    {"name": "ยาแก้ไอ (Cough syrup)", "image": "cough-syrup.svg"},
    {"name": "เกลือแร่ (ORS)", "image": "ors.svg"},
]

# ชื่อชีต (worksheet) สำหรับเก็บคำสั่งจองยา แยกจากชีตลงทะเบียน.
PREORDER_SHEET_NAME = os.environ.get("PREORDER_SHEET_NAME", "Preorders")

# หัวตารางของชีต pre-order: เวลา, ชื่อลูกค้า, ข้อมูลติดต่อกลับ, รายการสั่ง.
PREORDER_HEADER = ["Timestamp", "Customer name", "Contact", "Order"]

LOCAL_KEY_FILE = os.path.join(os.path.dirname(__file__), "service_account.json")

# gspread clients are not guaranteed thread-safe; guard sheet access.
_lock = threading.Lock()
_worksheet = None
_preorder_worksheet = None


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

    # Write the header row once if the sheet has no real content yet.
    # Note: a freshly cleared sheet can return [[]] rather than [], so we
    # check whether any cell actually holds a value.
    values = worksheet.get_all_values()
    is_empty = not any(any(cell for cell in row) for row in values)
    if is_empty:
        worksheet.append_row(HEADER, value_input_option="RAW")

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
    """Append a single user record as a new row (reconnects once on failure).

    Uses value_input_option="RAW" so values are stored exactly as given.
    This keeps leading zeros on Thai phone numbers (e.g. 0812345678) instead
    of letting Sheets interpret them as a number and strip the leading 0.
    """
    row = [str(timestamp), str(full_name), str(email), str(phone), str(note)]
    with _lock:
        try:
            worksheet = get_worksheet()
            worksheet.append_row(row, value_input_option="RAW")
        except Exception:
            # Reconnect once in case the cached client went stale.
            reset_worksheet()
            worksheet = get_worksheet()
            worksheet.append_row(row, value_input_option="RAW")


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


def _open_preorder_worksheet():
    """Open (and cache) the pre-order worksheet, creating it + header if needed."""
    creds = _load_credentials()
    client = gspread.authorize(creds)

    sheet_id = os.environ.get("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("The SHEET_ID environment variable is not set.")

    spreadsheet = client.open_by_key(sheet_id)

    # ใช้ชีตแยกสำหรับ pre-order ถ้ายังไม่มีให้สร้างใหม่.
    try:
        worksheet = spreadsheet.worksheet(PREORDER_SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=PREORDER_SHEET_NAME, rows=1000, cols=len(PREORDER_HEADER)
        )

    values = worksheet.get_all_values()
    is_empty = not any(any(cell for cell in row) for row in values)
    if is_empty:
        worksheet.append_row(PREORDER_HEADER, value_input_option="RAW")

    return worksheet


def get_preorder_worksheet():
    """Return the cached pre-order worksheet, opening it on first use."""
    global _preorder_worksheet
    if _preorder_worksheet is None:
        _preorder_worksheet = _open_preorder_worksheet()
    return _preorder_worksheet


def reset_preorder_worksheet():
    """Drop the cached pre-order worksheet so the next call reconnects."""
    global _preorder_worksheet
    _preorder_worksheet = None


def append_preorder(timestamp, customer_name, contact, order_text):
    """Append a single pre-order record as a new row (reconnects once on failure).

    order_text ควรเป็นสรุปรายการยาที่สั่ง เช่น
    "พาราเซตามอล x2; วิตามินซี x1".
    ใช้ value_input_option="RAW" เพื่อเก็บค่าตามที่กรอกจริง.
    """
    row = [str(timestamp), str(customer_name), str(contact), str(order_text)]
    with _lock:
        try:
            worksheet = get_preorder_worksheet()
            worksheet.append_row(row, value_input_option="RAW")
        except Exception:
            # Reconnect once in case the cached client went stale.
            reset_preorder_worksheet()
            worksheet = get_preorder_worksheet()
            worksheet.append_row(row, value_input_option="RAW")


def get_preorders():
    """อ่านคำสั่งจองทั้งหมดจากชีต Preorders (ใหม่สุดอยู่บน).

    คืนค่าเป็น list ของ dict:
        {"timestamp", "customer_name", "contact", "order"}
    ข้ามแถวหัวตาราง (header) ให้อัตโนมัติ.
    """
    with _lock:
        try:
            worksheet = get_preorder_worksheet()
            values = worksheet.get_all_values()
        except Exception:
            reset_preorder_worksheet()
            worksheet = get_preorder_worksheet()
            values = worksheet.get_all_values()

    orders = []
    # แถวแรกเป็น header (PREORDER_HEADER) จึงเริ่มที่ index 1.
    for row in values[1:]:
        # เผื่อบางแถวมีคอลัมน์ไม่ครบ ให้เติมค่าว่าง.
        cells = (list(row) + ["", "", "", ""])[:4]
        timestamp, customer_name, contact, order = cells
        # ข้ามแถวว่างสนิท.
        if not any(cell.strip() for cell in cells):
            continue
        orders.append(
            {
                "timestamp": timestamp,
                "customer_name": customer_name,
                "contact": contact,
                "order": order,
            }
        )

    # ใหม่สุดอยู่บน (ชีตเก็บเรียงเก่า->ใหม่ จึงกลับลำดับ).
    orders.reverse()
    return orders
