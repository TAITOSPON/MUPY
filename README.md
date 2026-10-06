# MUPY – ฟอร์มเก็บข้อมูล User ลง Google Sheets

เว็บฟอร์มง่าย ๆ สำหรับเก็บข้อมูลผู้ใช้ (ประมาณ 200 คน) แล้วบันทึกลง Google Sheets

- **Backend:** Flask (Python)
- **Deploy:** Render (Free tier)
- **Storage:** Google Sheets ผ่าน Service Account

ฟิลด์ที่เก็บ: ชื่อ-นามสกุล, อีเมล, เบอร์โทร, หมายเหตุ (พร้อม timestamp อัตโนมัติ)

---

## โครงสร้างโปรเจกต์

```
MUPY/
├── app.py              # Flask app + routes + validation
├── sheets.py           # เชื่อม Google Sheets ผ่าน gspread
├── requirements.txt    # dependencies
├── Procfile            # คำสั่งรันบน Render (gunicorn)
├── render.yaml         # config สำหรับ Render (optional)
├── runtime.txt         # ล็อก Python version
├── templates/          # หน้าเว็บ (HTML)
│   ├── base.html
│   ├── index.html      # ฟอร์มกรอกข้อมูล
│   └── success.html    # หน้าบันทึกสำเร็จ
└── static/
    └── style.css
```

---

## ขั้นตอนที่ 1: สร้าง Google Service Account

ส่วนนี้ต้องทำเองในบัญชี Google ของคุณ (ผมสร้างแทนให้ไม่ได้)

1. เข้า [Google Cloud Console](https://console.cloud.google.com/)
2. สร้างโปรเจกต์ใหม่ (หรือใช้ที่มีอยู่) เช่นชื่อ `mupy-form`
3. เปิดใช้งาน API 2 ตัว (เมนู **APIs & Services → Library** แล้วค้นหาและกด Enable):
   - **Google Sheets API**
   - **Google Drive API**
4. ไปที่ **APIs & Services → Credentials → Create Credentials → Service account**
   - ตั้งชื่อ เช่น `mupy-writer` แล้วกด Create and Continue จนจบ
5. คลิกเข้าไปที่ service account ที่สร้าง → แท็บ **Keys → Add Key → Create new key → JSON**
   - จะได้ไฟล์ `.json` ดาวน์โหลดมา **เก็บไว้ให้ดี อย่าเผยแพร่**
6. เปิดไฟล์ JSON ดู แล้ว copy ค่า `client_email` ไว้ (เช่น `mupy-writer@xxxx.iam.gserviceaccount.com`)

---

## ขั้นตอนที่ 2: เตรียม Google Sheet

1. สร้าง Google Sheet ใหม่ที่ [sheets.google.com](https://sheets.google.com)
2. **แชร์** sheet ให้กับ `client_email` ของ service account (จากขั้นตอน 1.6)
   - กดปุ่ม **Share** → วางอีเมล service account → ให้สิทธิ์ **Editor** → Send
3. copy **Sheet ID** จาก URL:
   ```
   https://docs.google.com/spreadsheets/d/<<< SHEET_ID อยู่ตรงนี้ >>>/edit
   ```
4. ชื่อแท็บ (worksheet) ค่าเริ่มต้นคือ `Sheet1` ถ้าใช้ชื่ออื่นให้จำไว้ตั้งใน `SHEET_NAME`

> หัวตาราง (Timestamp, Full name, Email, Phone, Note) โปรแกรมจะเติมให้อัตโนมัติในแถวแรกตอนบันทึกครั้งแรก

---

## ขั้นตอนที่ 3: รันทดสอบบนเครื่อง (Local)

1. ติดตั้ง dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
2. วางไฟล์ service account JSON ไว้ในโฟลเดอร์โปรเจกต์ ตั้งชื่อ `service_account.json`
   (ไฟล์นี้อยู่ใน `.gitignore` แล้ว จะไม่ถูก commit)
3. ตั้งค่า environment variable (PowerShell):
   ```powershell
   $env:SHEET_ID="<Sheet ID ของคุณ>"
   $env:SHEET_NAME="Sheet1"
   ```
4. รัน:
   ```powershell
   python app.py
   ```
5. เปิดเบราว์เซอร์ที่ http://localhost:5000 แล้วลองกรอกฟอร์ม

---

## ขั้นตอนที่ 4: Deploy ขึ้น Render (Free)

1. push โค้ดขึ้น GitHub ให้เรียบร้อย (repo: `TAITOSPON/MUPY`)
2. เข้า [Render Dashboard](https://dashboard.render.com/) → **New → Web Service**
3. เชื่อม GitHub แล้วเลือก repo `MUPY`
4. ตั้งค่า:
   - **Runtime:** Python
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app`
   - **Instance Type:** Free
5. ไปที่แท็บ **Environment** เพิ่ม environment variables:

   | Key | Value |
   |-----|-------|
   | `SHEET_ID` | Sheet ID ของคุณ |
   | `SHEET_NAME` | `Sheet1` (หรือชื่อแท็บที่ใช้) |
   | `SECRET_KEY` | สุ่มข้อความยาว ๆ อะไรก็ได้ |
   | `GOOGLE_CREDENTIALS` | **เนื้อหาทั้งหมดของไฟล์ JSON** (เปิดไฟล์ copy ทั้งก้อนมาวาง) |

6. กด **Create Web Service** รอ build เสร็จ แล้วเปิด URL ที่ Render ให้มา

> **หมายเหตุ Render Free:** เครื่องจะ "หลับ" เมื่อไม่มีคนใช้งานสักพัก ครั้งแรกที่เปิดอาจโหลดช้าสัก 30–60 วินาที ถือเป็นเรื่องปกติของ free tier

---

## ความปลอดภัย

- ไฟล์ `service_account.json`, `.env`, `*.key` อยู่ใน `.gitignore` แล้ว **ห้าม commit ขึ้น GitHub เด็ดขาด**
- บน Render ใส่ credentials ผ่าน environment variable เท่านั้น
- ฟอร์มมีการตรวจสอบข้อมูล (validation) ฝั่ง server และกันอีเมลซ้ำ
