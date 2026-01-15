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

        # =================================================
        # HELP COMMAND
        # =================================================
        if text.lower() in ["help", "/help", "/start", "commands"]:
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

        text_lower = text.lower()

        # =================================================
        # SHOW COMMAND
        # =================================================
        if text_lower.startswith("show"):
            customer_id = text_lower.replace("show", "", 1).strip()
            
            if not customer_id:
                send_message(chat_id, "❌ Please provide a Customer ID\nExample: `show 132`")
                return {"status": "ok"}
            
            try:
                # Get all records from sheet
                records = sheet.get_all_records()
                
                # Debug: Check what columns we have
                print("DEBUG KEYS:", records[0].keys())
                send_message(chat_id, f"🔎 Debug keys: {list(records[0].keys())}")

                    
                customer_rows = []

                for r in records:
                    # Try different possible column names
                    sheet_id = str(r.get("Customer_id", r.get("Customer ID", r.get("customer_id", "")))).strip()
                    if sheet_id == customer_id:
                        customer_rows.append(r)

                if not customer_rows:
                    send_message(chat_id, f"❌ No records found for customer {customer_id}")
                    return {"status": "ok"}

                # First entry is the initial loan (oldest entry)
                customer_rows.sort(key=lambda x: x.get("Entry_time", x.get("Timestamp", "")))
                
                total_given = int(customer_rows[0].get("Amount", 0))
                
                # Subsequent entries are payments
                payments = customer_rows[1:] if len(customer_rows) > 1 else []
                total_paid = sum(int(p.get("Amount", 0)) for p in payments)
                balance = total_given - total_paid

                reply = (
                    f"📄 *Customer ID:* {customer_id}\n"
                    f"📊 *Records Found:* {len(customer_rows)}\n\n"
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
                error_msg = f"❌ Error retrieving records: {str(e)}\n\n"
                error_msg += f"🔍 Try checking: https://your-app.onrender.com/sheet-status"
                send_message(chat_id, error_msg)
                
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
        # SAVE DATA - MAIN LOGIC
        # =================================================
        parts = text.split()
        
        # If it's just numbers without spaces (like "130", "2100"), it's invalid
        if len(parts) == 1 and text.replace(" ", "").isdigit():
            send_message(
                chat_id,
                "❌ Invalid format\n\n"
                "To save data, use:\n"
                "`<CustomerID> <Amount>`\n\n"
                "*Examples:*\n"
                "`1 30`\n"
                "`2 100`\n"
                "`5 100`"
            )
            return {"status": "ok"}
        
        # If it has spaces, try to parse as save command
        if len(parts) == 2 or len(parts) == 3:
            # Try to parse customer_id and amount
            try:
                if len(parts) == 2:
                    customer_id, amount_str = parts
                    date = datetime.now().strftime("%d-%m-%Y")
                else:
                    customer_id, amount_str, date = parts
                
                # Validate customer_id is not empty
                if not customer_id or not customer_id.strip():
                    send_message(chat_id, "❌ Customer ID cannot be empty")
                    return {"status": "ok"}
                
                # Validate amount
                if not amount_str.isdigit():
                    send_message(chat_id, "❌ Amount must be a number")
                    return {"status": "ok"}
                
                amount = int(amount_str)
                if amount <= 0:
                    send_message(chat_id, "❌ Amount must be greater than 0")
                    return {"status": "ok"}
                
                # Validate date format
                try:
                    datetime.strptime(date, "%d-%m-%Y")
                except ValueError:
                    send_message(chat_id, "❌ Invalid date format. Use DD-MM-YYYY")
                    return {"status": "ok"}
                
                # All validations passed, save to sheet
                try:
                    sheet.append_row([
                        str(customer_id).strip(),
                        amount,
                        date,
                        datetime.now().strftime("%d-%m-%Y %H:%M:%S")
                    ])
                    send_message(chat_id, f"✅ *Saved successfully*\n\n"
                                        f"• Customer: `{customer_id}`\n"
                                        f"• Amount: ₹{amount:,}\n"
                                        f"• Date: {date}")
                    
                except Exception as e:
                    send_message(chat_id, f"❌ Error saving to Google Sheets: {str(e)}")
                
                return {"status": "ok"}
                
            except Exception as e:
                send_message(chat_id, f"❌ Error processing your request: {str(e)}")
                return {"status": "ok"}
        
        # =================================================
        # UNKNOWN COMMAND
        # =================================================
        send_message(
            chat_id,
            "❌ *Unknown command*\n\n"
            "Type `help` to see available commands.\n\n"
            "*Common formats:*\n"
            "• `1 30` - Save ₹30 for customer 1\n"
            "• `show 1` - Show records for customer 1\n"
            "• `delete 1 30 15-01-2026` - Delete specific entry"
        )
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
    """Debug endpoint to check sheet structure"""
    try:
        # Get all data as list of lists
        all_data = sheet.get_all_values()
        
        # Get records as dictionaries
        records = sheet.get_all_records()
        
        response = {
            "status": "connected",
            "total_rows": len(all_data),
            "headers": all_data[0] if all_data else [],
            "column_count": len(all_data[0]) if all_data else 0,
            "total_records": len(records),
        }
        
        if records:
            response["sample_record"] = records[0]
            response["all_columns"] = list(records[0].keys())
            
        return response
        
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }


# =====================================================
# FIX HEADERS (RUN ONCE TO UPDATE SHEET STRUCTURE)
# =====================================================
@app.get("/fix-headers")
async def fix_headers():
    """Fix the column headers in the sheet to match expected names"""
    try:
        # Get current headers
        headers = sheet.row_values(1)
        
        # Create mapping for expected headers
        expected_headers = ["Customer_id", "Amount", "Date", "Timestamp"]
        
        if headers != expected_headers:
            # Update the headers
            sheet.update('A1:D1', [expected_headers])
            return {
                "status": "updated",
                "old_headers": headers,
                "new_headers": expected_headers,
                "message": "Headers updated successfully"
            }
        else:
            return {
                "status": "already_correct",
                "headers": headers,
                "message": "Headers are already correct"
            }
            
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }
