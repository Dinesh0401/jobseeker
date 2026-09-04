import json
import os
import urllib.request
from pathlib import Path

env_file = Path(__file__).parent / ".env"
if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET")
WEBHOOK_URL = "https://rgyaqajrzxvyidbbwoai.supabase.co/functions/v1/telegram-webhook"

payload = {
    "url": WEBHOOK_URL,
    "secret_token": SECRET,
    "allowed_updates": ["message", "callback_query"]
}

req = urllib.request.Request(
    f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"}
)

try:
    with urllib.request.urlopen(req) as resp:
        res = json.loads(resp.read().decode())
        print("setWebhook response:", res)
except Exception as e:
    print("Failed to register webhook:", e)
