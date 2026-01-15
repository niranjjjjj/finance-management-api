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
sheet = client.open("Clean_Data").sheet2


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
        # HELP COMMAND
        # =================================================
        if text_lower in ["help", "/help", "/start"]:
            help_text = (
                "💰 *Finance Bot Commands*\n\n"
                "📥 *Save Data:*\n"
                "`<CustomerID> <Amount>` - Save with today's date\n"
                "`<CustomerID> <Amount> <DD-MM-YYYY>` - Save with specific date\n\n"
                "📤 *Show Records:*\n"
                "`show <CustomerID>` - View customer summary\n\n"
                "🗑️ *Delete Records:*\n"
                "`delete <CustomerID> <Amount> <DD-MM-YYYY>` - Delete specific entry\n"
                "`delete all <CustomerID>` - Delete all records for customer\n\n"
                "*Examples:*\n"
                "`132 500`\n"
                "`132 300 15-01-2026`\n"
                "`show 132`\n"
                "`delete 132 300 15-01-2026`\n"
                "`delete all 132`"
            )
            send_message(chat_id, help_text)
            return {"status": "ok"}

        # =================================================
        # SHOW COMMAND
        # =================================================
        if text_lower.startswith("show"):
            customer_id = text_lower.replace("show", "", 1).strip()
            
            if not customer_id:
                send_message(chat_id, "❌ Please provide a Customer ID\nExample: `show 132`")
                return {"status": "ok"}
            
            try:
                records = sheet.get_all_records()
                customer_rows = []

                for r in records:
                    sheet_id = str(r.get("Customer_id", "")).strip()
                    if sheet_id == customer_id:
                        customer_rows.append(r)

                if not customer_rows:
                    send_message(chat_id, f"❌ No records found for customer {customer_id}")
                    return {"status": "ok"}

                # First entry is the initial loan
                total_given = int(customer_rows[0].get("Amount", 0))
                
                # Subsequent entries are payments
                payments = customer_rows[1:] if len(customer_rows) > 1 else []
                total_paid = sum(int(p.get("Amount", 0)) for p in payments)
                balance = total_given - total_paid

                reply = (
                    f"📄 *Customer ID:* {customer_id}\n\n"
                    f"💰 *Total Given:* ₹{total_given:,}\n"
                    f"💵 *Total Paid:* ₹{total_paid:,}\n"
                    f"📉 *Balance:* ₹{balance:,}\n\n"
                )

                if payments:
                    reply += "🧾 *Payment History:*\n"
                    for i, p in enumerate(payments, 1):
                        date_str = p.get("Date", "Unknown")
                        amount = p.get("Amount", 0)
                        reply += f"{i}) {date_str} – ₹{amount}\n"
                else:
                    reply += "No payments yet."

                send_message(chat_id, reply)
                
            except Exception as e:
                send_message(chat_id, f"❌ Error retrieving records: {str(e)}")
                
            return {"status": "ok"}

        # =================================================
        # DELETE ALL RECORDS OF A CUSTOMER
        # =================================================
        if text_lower.startswith("delete all "):
            customer_id = text_lower.replace("delete all", "", 1).strip()
            
            if not customer_id:
                send_message(chat_id, "❌ Please provide a Customer ID\nExample: `delete all 132`")
                return {"status": "ok"}

            try:
                rows = sheet.get_all_values()
                if len(rows) == 0:
                    send_message(chat_id, "❌ No records found in sheet")
                    return {"status": "ok"}
                    
                header = rows[0]
                new_rows = [header]

                deleted = 0
                for r in rows[1:]:
                    if r and len(r) > 0:
                        if r[0] != customer_id:
                            new_rows.append(r)
                        else:
                            deleted += 1

                sheet.clear()
                sheet.update(new_rows)

                send_message(chat_id, f"🗑️ Deleted {deleted} records for customer {customer_id}")
                
            except Exception as e:
                send_message(chat_id, f"❌ Error deleting records: {str(e)}")
                
            return {"status": "ok"}

        # =================================================
        # DELETE SINGLE ENTRY
        # =================================================
        if text_lower.startswith("delete "):
            parts = text.split()

            if len(parts) != 4:
                send_message(
                    chat_id,
                    "❌ Invalid format\n\n"
                    "*Usage:*\n"
                    "`delete <CustomerID> <Amount> <DD-MM-YYYY>`\n\n"
                    "*Example:*\n"
                    "`delete 132 200 15-01-2026`"
                )
                return {"status": "ok"}

            _, customer_id, amount, date = parts

            try:
                rows = sheet.get_all_values()
                if len(rows) == 0:
                    send_message(chat_id, "❌ No records found in sheet")
                    return {"status": "ok"}
                    
                header = rows[0]
                new_rows = [header]
                deleted = False

                for r in rows[1:]:
                    if r and len(r) >= 3:
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
                    send_message(chat_id, "✅ Entry deleted successfully")
                else:
                    send_message(chat_id, "❌ No matching entry found")
                    
            except Exception as e:
                send_message(chat_id, f"❌ Error deleting entry: {str(e)}")
                
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
                "*Usage:*\n"
                "`<CustomerID> <Amount>`\n"
                "or\n"
                "`<CustomerID> <Amount> <DD-MM-YYYY>`\n\n"
                "*Examples:*\n"
                "`132 200`\n"
                "`132 200 15-01-2026`"
            )
            return {"status": "ok"}

        try:
            amount = int(amount)
            if amount <= 0:
                send_message(chat_id, "❌ Amount must be greater than 0")
                return {"status": "ok"}
                
            datetime.strptime(date, "%d-%m-%Y")
        except ValueError:
            send_message(chat_id, "❌ Invalid amount or date format (use DD-MM-YYYY)")
            return {"status": "ok"}
        except Exception:
            send_message(chat_id, "❌ Invalid input format")
            return {"status": "ok"}

        try:
            sheet.append_row([
                str(customer_id),
                str(amount),
                str(date),
                datetime.now().strftime("%d-%m-%Y %H:%M:%S")
            ])
            send_message(chat_id, f"✅ Saved successfully\nCustomer: {customer_id}\nAmount: ₹{amount}\nDate: {date}")
            
        except Exception as e:
            send_message(chat_id, f"❌ Error saving to Google Sheets: {str(e)}")
            
        return {"status": "ok"}

    except Exception:
        with open("server_error.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] ERROR:\n")
            f.write(traceback.format_exc() + "\n" + "="*50 + "\n")
        try:
            send_message(chat_id, "❌ Server error occurred. Please try again.")
        except:
            pass
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
                "text": text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            },
            timeout=10
        )
    except Exception as e:
        with open("telegram_error.log", "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now()}] Failed to send message: {str(e)}\n")


# =====================================================
# HEALTH CHECK ENDPOINT
# =====================================================
@app.get("/")
async def health_check():
    return {
        "status": "online",
        "service": "Telegram Finance Bot",
        "timestamp": datetime.now().isoformat()
    }


# =====================================================
# SHEET STATUS ENDPOINT (FOR DEBUGGING)
# =====================================================
@app.get("/sheet-status")
async def sheet_status():
    try:
        records = sheet.get_all_records()
        return {
            "status": "connected",
            "total_records": len(records),
            "columns": list(records[0].keys()) if records else [],
            "sample_data": records[:3] if records else []
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
