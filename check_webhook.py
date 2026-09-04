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
req = urllib.request.Request(f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo")
try:
    with urllib.request.urlopen(req) as resp:
        print("Webhook Info:", json.dumps(json.loads(resp.read().decode()), indent=2))
except Exception as e:
    print("Error:", e)
