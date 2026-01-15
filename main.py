from fastapi import FastAPI, Request
import requests
from datetime import datetime
import traceback
import os
import json

import gspread
from oauth2client.service_account import ServiceAccountCredentials


# =====================================================
# APP INIT
# =====================================================
app = FastAPI()


# =====================================================
# CONFIG (FROM ENV VARIABLES – RENDER SAFE)
# =====================================================
BOT_TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID"))
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"


# =====================================================
# GOOGLE SHEETS SETUP
# =====================================================
SCOPE = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

GOOGLE_CREDS = json.loads(os.getenv("GOOGLE_CREDS"))

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    GOOGLE_CREDS,
    SCOPE
)

client = gspread.authorize(creds)
sheet = client.open("Finance_Records").sheet1


# =====================================================
# TELEGRAM WEBHOOK
# =====================================================
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()

        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")

        # -------------------------------
        # SECURITY CHECK
        # -------------------------------
        if user_id != AUTHORIZED_USER_ID:
            return {"status": "ignored"}

        text_lower = text.lower()

        # =================================================
        # SHOW COMMAND
        # =================================================
        if text_lower.startswith("show"):
            customer_id = text_lower.replace("show", "", 1).strip()

            records = sheet.get_all_records()
            customer_rows = []

            for r in records:
                sheet_id = str(r.get("Customer_id", "")).strip()
                if sheet_id == str(customer_id):
                    customer_rows.append(r)

            if not customer_rows:
                send_message(chat_id, f"❌ No records found for {customer_id}")
                return {"status": "ok"}

            total_given = int(customer_rows[0]["Amount"])
            payments = customer_rows[1:]
            total_paid = sum(int(p["Amount"]) for p in payments)
            balance = total_given - total_paid

            reply = (
                f"📄 Customer ID: {customer_id}\n\n"
                f"💰 Total Given : ₹{total_given}\n"
                f"💵 Total Paid  : ₹{total_paid}\n"
                f"📉 Balance     : ₹{balance}\n\n"
                f"🧾 Payment History:\n"
            )

            if payments:
                for i, p in enumerate(payments, 1):
                    reply += f"{i}) {p['Date']} – ₹{p['Amount']}\n"
            else:
                reply += "No payments yet."

            send_message(chat_id, reply)
            return {"status": "ok"}

        # =================================================
        # DELETE ALL RECORDS OF A CUSTOMER
        # =================================================
        if text_lower.startswith("delete all "):
            customer_id = text_lower.replace("delete all", "", 1).strip()

            rows = sheet.get_all_values()
            header = rows[0]
            new_rows = [header]

            deleted = 0
            for r in rows[1:]:
                if r[0] != customer_id:
                    new_rows.append(r)
                else:
                    deleted += 1

            sheet.clear()
            sheet.update(new_rows)

            send_message(chat_id, f"🗑️ Deleted {deleted} records for {customer_id}")
            return {"status": "ok"}

        # =================================================
        # DELETE SINGLE ENTRY
        # =================================================
        if text_lower.startswith("delete "):
            parts = text.split()

            if len(parts) != 4:
                send_message(
                    chat_id,
                    "❌ Use:\n"
                    "delete <CustomerID> <Amount> <Date>\n"
                    "Example:\n"
                    "delete 132 200 15-01-2026"
                )
                return {"status": "ok"}

            _, customer_id, amount, date = parts

            rows = sheet.get_all_values()
            header = rows[0]
            new_rows = [header]
            deleted = False

            for r in rows[1:]:
                if (
                    r[0] == customer_id and
                    r[1] == amount and
                    r[2] == date and
                    not deleted
                ):
                    deleted = True
                    continue
                new_rows.append(r)

            sheet.clear()
            sheet.update(new_rows)

            if deleted:
                send_message(chat_id, "🗑️ Entry deleted successfully")
            else:
                send_message(chat_id, "❌ No matching entry found")

            return {"status": "ok"}

        # =================================================
        # SAVE DATA
        # =================================================
        parts = text.split()

        if len(parts) == 3:
            customer_id, amount, date = parts
        elif len(parts) == 2:
            customer_id, amount = parts
            date = datetime.now().strftime("%d-%m-%Y")
        else:
            send_message(
                chat_id,
                "❌ Invalid format\n\n"
                "Use:\n"
                "CustomerID Amount\n"
                "or\n"
                "CustomerID Amount Date\n\n"
                "Example:\n132 200"
            )
            return {"status": "ok"}

        try:
            amount = int(amount)
            datetime.strptime(date, "%d-%m-%Y")
        except Exception:
            send_message(chat_id, "❌ Invalid amount or date")
            return {"status": "ok"}

        sheet.append_row([
            str(customer_id).strip(),
            amount,
            date,
            datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        ])

        send_message(chat_id, "✅ Saved successfully")
        return {"status": "ok"}

    except Exception:
        with open("server_error.log", "a", encoding="utf-8") as f:
            f.write(traceback.format_exc() + "\n")
        return {"status": "error"}


# =====================================================
# TELEGRAM SEND MESSAGE
# =====================================================
def send_message(chat_id, text):
    try:
        requests.post(
            TELEGRAM_API,
            json={
                "chat_id": chat_id,
                "text": text
            },
            timeout=5
        )
    except Exception:
        pass







