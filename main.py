from fastapi import FastAPI, Request
import requests
from datetime import datetime
import traceback
import os
import json

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = FastAPI()

# ======================
# CONFIG
# ======================
BOT_TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_USER_ID = int(os.getenv("AUTHORIZED_USER_ID"))
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

# ======================
# GOOGLE SHEETS SETUP
# ======================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

GOOGLE_CREDS = json.loads(os.getenv("GOOGLE_CREDS"))

creds = ServiceAccountCredentials.from_json_keyfile_dict(
    GOOGLE_CREDS, scope
)

client = gspread.authorize(creds)
sheet = client.open("Finance_Records").sheet1


# ======================
# TELEGRAM WEBHOOK
# ======================
@app.post("/telegram/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        message = data.get("message", {})
        text = message.get("text", "").strip()
        chat_id = message.get("chat", {}).get("id")
        user_id = message.get("from", {}).get("id")

        # Security
        if user_id != AUTHORIZED_USER_ID:
            return {"status": "ignored"}

        text_lower = text.lower()

        # ======================
        # SHOW COMMAND
        # ======================
        if text_lower.startswith("show "):
            customer_id = text.split(maxsplit=1)[1].strip()

            records = sheet.get_all_records()

            rows = [
                r for r in records
                if str(r.get("Customer_id")).strip() == customer_id
            ]

            if not rows:
                send_message(chat_id, f"❌ No records found for {customer_id}")
                return {"status": "ok"}

            total_given = int(rows[0]["Amount"])
            payments = rows[1:]
            total_paid = sum(int(r["Amount"]) for r in payments)
            balance = total_given - total_paid

            reply = (
                f"📄 Customer ID: {customer_id}\n\n"
                f"💰 Total Given : ₹{total_given}\n"
                f"💵 Total Paid  : ₹{total_paid}\n"
                f"📉 Balance     : ₹{balance}\n\n"
                f"🧾 Payments:\n"
            )

            if payments:
                for i, r in enumerate(payments, 1):
                    reply += f"{i}) {r['Date']} – ₹{r['Amount']}\n"
            else:
                reply += "No payments yet."

            send_message(chat_id, reply)
            return {"status": "ok"}

        # ======================
        # DELETE COMMAND
        # ======================
        if text_lower.startswith("delete all "):
            customer_id = text.split(maxsplit=2)[2].strip()

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

        if text_lower.startswith("delete "):
            parts = text.split()
            if len(parts) != 4:
                send_message(
                    chat_id,
                    "❌ Use:\ndelete <CustomerID> <Amount> <Date>\nExample:\ndelete 132 200 15-01-2026"
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

        # ======================
        # SAVE DATA
        # ======================
        parts = text.split()

        if len(parts) == 3:
            customer_id, amount, date = parts
        elif len(parts) == 2:
            customer_id, amount = parts
            date = datetime.now().strftime("%d-%m-%Y")
        else:
            send_message(
                chat_id,
                "❌ Invalid format\n\nUse:\nCustomerID Amount\nor\nCustomerID Amount Date\n\nExample:\n132 200"
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
        with open("server_error.log", "a") as f:
            f.write(traceback.format_exc() + "\n")
        return {"status": "error"}


# ======================
# SEND TELEGRAM MESSAGE
# ======================
def send_message(chat_id, text):
    try:
        requests.post(
            TELEGRAM_API,
            json={"chat_id": chat_id, "text": text},
            timeout=5
        )
    except Exception:
        pass
