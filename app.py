"""
Flask web app that collects user information through a simple form and
stores each submission in a Google Sheet.

Run locally:
    pip install -r requirements.txt
    set FLASK_APP=app.py        (Windows PowerShell: $env:FLASK_APP="app.py")
    flask run

Production (Render) uses gunicorn via the Procfile.
"""

import os
import re
from datetime import datetime
from functools import wraps

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import sheets

app = Flask(__name__)
# Secret key is only used for flash messages; override via env in production.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

# รหัสผ่านสำหรับเข้าหน้า admin (ตั้งผ่าน env var ใน production).
# ค่า default ใช้สำหรับทดสอบ local เท่านั้น ควรเปลี่ยนก่อน deploy จริง.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")


def login_required(view):
    """Decorator กันหน้า admin ให้เข้าได้เฉพาะเมื่อ login แล้ว."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)

    return wrapped

# Basic email format check. Not RFC-perfect, but good enough for a form.
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Allow digits, spaces, +, -, and parentheses; require at least 9 digits.
PHONE_ALLOWED_RE = re.compile(r"^[\d\s+\-()]+$")


def validate(full_name, email, phone):
    """Return a list of human-readable error messages (empty if valid)."""
    errors = []

    if not full_name or len(full_name.strip()) < 2:
        errors.append("กรุณากรอกชื่อ-นามสกุลให้ถูกต้อง")

    if not email or not EMAIL_RE.match(email.strip()):
        errors.append("กรุณากรอกอีเมลให้ถูกต้อง")

    phone_clean = (phone or "").strip()
    if not phone_clean:
        errors.append("กรุณากรอกเบอร์โทร")
    elif not PHONE_ALLOWED_RE.match(phone_clean):
        errors.append("เบอร์โทรมีอักขระที่ไม่ถูกต้อง")
    elif len(re.sub(r"\D", "", phone_clean)) < 9:
        errors.append("เบอร์โทรต้องมีตัวเลขอย่างน้อย 9 หลัก")

    return errors


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip()
    phone = request.form.get("phone", "").strip()
    note = request.form.get("note", "").strip()

    errors = validate(full_name, email, phone)
    if errors:
        for message in errors:
            flash(message, "error")
        # Re-render the form keeping what the user already typed.
        return (
            render_template(
                "index.html",
                full_name=full_name,
                email=email,
                phone=phone,
                note=note,
            ),
            400,
        )

    try:
        if sheets.email_exists(email):
            flash("อีเมลนี้ถูกบันทึกไว้แล้ว", "error")
            return (
                render_template(
                    "index.html",
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    note=note,
                ),
                409,
            )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets.append_user(timestamp, full_name, email, phone, note)
    except Exception as exc:  # noqa: BLE001 - surface a friendly message
        app.logger.exception("Failed to save submission")
        flash(
            "เกิดข้อผิดพลาดในการบันทึกข้อมูล กรุณาลองใหม่อีกครั้ง", "error"
        )
        return (
            render_template(
                "index.html",
                full_name=full_name,
                email=email,
                phone=phone,
                note=note,
            ),
            500,
        )

    return redirect(url_for("success"))


@app.route("/success", methods=["GET"])
def success():
    return render_template("success.html")


@app.route("/preorder", methods=["GET"])
def preorder():
    return render_template("preorder.html", medicines=sheets.MEDICINES)


@app.route("/preorder/submit", methods=["POST"])
def preorder_submit():
    customer_name = request.form.get("customer_name", "").strip()
    contact = request.form.get("contact", "").strip()

    errors = []

    if not customer_name or len(customer_name) < 2:
        errors.append("กรุณากรอกชื่อลูกค้าให้ถูกต้อง")

    if not contact:
        errors.append("กรุณากรอกข้อมูลติดต่อกลับ")

    # เก็บจำนวนที่สั่งของยาแต่ละรายการ (index ตรงกับ sheets.MEDICINES).
    quantities = {}
    cart_items = []  # รายการในตะกร้า: [{"name", "qty"}, ...]
    for i, medicine in enumerate(sheets.MEDICINES):
        name = medicine["name"]
        raw = request.form.get(f"qty_{i}", "").strip()
        qty = 0
        if raw:
            try:
                qty = int(raw)
            except ValueError:
                errors.append(f"จำนวนของ \"{name}\" ต้องเป็นตัวเลข")
                qty = 0
        if qty < 0:
            errors.append(f"จำนวนของ \"{name}\" ต้องไม่น้อยกว่า 0")
            qty = 0
        quantities[i] = raw
        if qty > 0:
            cart_items.append({"name": name, "qty": qty})

    order_items = [f"{item['name']} x{item['qty']}" for item in cart_items]

    if not errors and not order_items:
        errors.append("กรุณาเลือกจำนวนยาอย่างน้อย 1 รายการ")

    if errors:
        for message in errors:
            flash(message, "error")
        return (
            render_template(
                "preorder.html",
                medicines=sheets.MEDICINES,
                customer_name=customer_name,
                contact=contact,
                quantities=quantities,
            ),
            400,
        )

    order_text = "; ".join(order_items)

    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheets.append_preorder(timestamp, customer_name, contact, order_text)
    except Exception:  # noqa: BLE001 - surface a friendly message
        app.logger.exception("Failed to save pre-order")
        flash(
            "เกิดข้อผิดพลาดในการบันทึกคำสั่งจอง กรุณาลองใหม่อีกครั้ง", "error"
        )
        return (
            render_template(
                "preorder.html",
                medicines=sheets.MEDICINES,
                customer_name=customer_name,
                contact=contact,
                quantities=quantities,
            ),
            500,
        )

    # เก็บสรุปคำสั่งจองล่าสุดไว้ใน session เพื่อนำไปแสดงในหน้ายืนยัน (ตะกร้า).
    total_qty = sum(item["qty"] for item in cart_items)
    session["last_order"] = {
        "customer_name": customer_name,
        "contact": contact,
        "products": cart_items,
        "total_qty": total_qty,
        "timestamp": timestamp,
    }

    return redirect(url_for("preorder_success"))


@app.route("/preorder/success", methods=["GET"])
def preorder_success():
    # ดึงสรุปคำสั่งจองล่าสุดจาก session (ถ้ามี) มาแสดงเป็นรายการในตะกร้า.
    order = session.pop("last_order", None)
    return render_template("preorder_success.html", order=order)


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("is_admin"):
        return redirect(url_for("admin"))

    if request.method == "POST":
        password = request.form.get("password", "")
        if password == ADMIN_PASSWORD:
            session["is_admin"] = True
            # ป้องกัน open-redirect: รับเฉพาะ path ภายใน (ขึ้นต้นด้วย /).
            target = request.form.get("next") or request.args.get("next")
            if target and target.startswith("/") and not target.startswith("//"):
                return redirect(target)
            return redirect(url_for("admin"))
        flash("รหัสผ่านไม่ถูกต้อง", "error")

    next_target = request.args.get("next", "")
    return render_template("admin_login.html", next=next_target)


@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    session.pop("is_admin", None)
    flash("ออกจากระบบแล้ว", "success")
    return redirect(url_for("admin_login"))


@app.route("/admin", methods=["GET"])
@login_required
def admin():
    load_error = None
    orders = []
    try:
        orders = sheets.get_preorders()
    except Exception:  # noqa: BLE001 - surface a friendly message
        app.logger.exception("Failed to load pre-orders for admin")
        load_error = (
            "โหลดข้อมูลคำสั่งจองไม่สำเร็จ "
            "ตรวจสอบการตั้งค่า SHEET_ID และสิทธิ์การเข้าถึงชีต"
        )

    return render_template(
        "admin.html",
        medicines=sheets.MEDICINES,
        orders=orders,
        order_count=len(orders),
        load_error=load_error,
    )


@app.route("/healthz", methods=["GET"])
def healthz():
    """Lightweight health check endpoint for Render."""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
