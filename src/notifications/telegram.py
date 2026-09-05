"""
Telegram notification module for Job Hunter v1.

Handles sending interactive approval cards to the configured Telegram chat.
"""

import json
import logging
import urllib.request
from urllib.error import URLError, HTTPError
from typing import Optional

logger = logging.getLogger(__name__)

def send_approval_card(
    chat_id: str,
    bot_token: str,
    queue_id: str,
    job_title: str,
    company: str,
    score: int,
    email: Optional[str]
) -> None:
    """
    Sends an interactive approval card to Telegram.

    Args:
        chat_id: The Telegram chat ID.
        bot_token: The Telegram bot token.
        queue_id: The UUID of the action_queue item.
        job_title: The job title.
        company: The company name.
        score: The match score (0-100).
        email: The extracted contact email (or 'Unknown').
    
    Raises:
        RuntimeError: If the API request fails, preventing the pipeline from advancing.
    """
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or MY_TELEGRAM_CHAT_ID")

    email_display = email if email else "Unknown"
    
    payload = {
        "chat_id": chat_id,
        "text": (
            f"🤖 *Job Hunter — New Match Found*\n\n"
            f"💼 *Title:* {job_title}\n"
            f"🏢 *Company:* {company}\n"
            f"📊 *Match Score:* {score}/100\n"
            f"📧 *Delivery:* Email ({email_display})\n\n"
            f"Ready to review application draft and dispatch."
        ),
        "parse_mode": "Markdown",
        "reply_markup": {
            "inline_keyboard": [
                [
                    {"text": "✅ Approve", "callback_data": f"approve:{queue_id}"},
                    {"text": "❌ Skip", "callback_data": f"skip:{queue_id}"}
                ]
            ]
        }
    }

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            res = json.loads(resp.read().decode())
            if not res.get("ok"):
                logger.error("Telegram API returned an error: %s", res)
                raise RuntimeError(f"Telegram API error: {res}")
            logger.info("Successfully sent Telegram approval card for queue_id %s", queue_id)
    except HTTPError as e:
        logger.error("HTTPError sending Telegram card: %d - %s", e.code, e.reason)
        raise RuntimeError(f"HTTPError sending Telegram card: {e.reason}") from e
    except URLError as e:
        logger.error("URLError sending Telegram card: %s", e.reason)
        raise RuntimeError(f"URLError sending Telegram card: {e.reason}") from e
    except Exception as e:
        logger.error("Failed to send Telegram card: %s", e)
        raise RuntimeError(f"Failed to send Telegram card: {e}") from e
