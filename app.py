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

from flask import Flask, flash, redirect, render_template, request, url_for

import sheets

app = Flask(__name__)
# Secret key is only used for flash messages; override via env in production.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-me")

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


@app.route("/healthz", methods=["GET"])
def healthz():
    """Lightweight health check endpoint for Render."""
    return {"status": "ok"}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
