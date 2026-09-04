"""
Helper script to send an interactive test card to Telegram for queue item approval.
Reads credentials from local .env.
"""

import json
import os
import urllib.request
from pathlib import Path

# Load .env manually if python-dotenv isn't installed
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("MY_TELEGRAM_CHAT_ID")
QUEUE_ID = "30ef0ddf-b78c-4b8b-910e-afb7346d42e1"

if not BOT_TOKEN or not CHAT_ID:
    print("ERROR: TELEGRAM_BOT_TOKEN or MY_TELEGRAM_CHAT_ID missing from .env")
    exit(1)

payload = {
    "chat_id": CHAT_ID,
    "text": (
        "🤖 *Job Hunter — New Match Found*\n\n"
        "💼 *Title:* Python Developer\n"
        "🏢 *Company:* TestCorp\n"
        "📊 *Match Score:* 85/100\n"
        "📧 *Delivery:* Email (sjdineshofficial@gmail.com)\n\n"
        "Ready to review application draft and dispatch."
    ),
    "parse_mode": "Markdown",
    "reply_markup": {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"approve:{QUEUE_ID}"},
                {"text": "❌ Skip", "callback_data": f"skip:{QUEUE_ID}"}
            ]
        ]
    }
}

req = urllib.request.Request(
    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        if res.get("ok"):
            print("✅ Test card successfully sent to Telegram!")
            print("Check your Telegram bot, then click '✅ Approve'.")
        else:
            print("❌ Telegram API returned an error:", res)
except Exception as e:
    print("❌ Failed to send Telegram card:", e)
