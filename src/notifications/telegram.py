"""
Telegram notification module for Job Hunter v1.

Handles sending interactive approval cards to the configured Telegram chat.
"""

import json
import logging
import urllib.request
from urllib.error import URLError, HTTPError
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

def _escape_md(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    if not text:
        return ""
    # In MarkdownV2, these characters must be escaped:
    # _ * [ ] ( ) ~ ` > # + - = | { } . !
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text

def send_approval_card(
    chat_id: str,
    bot_token: str,
    queue_id: str,
    job: Dict[str, Any],
    eval_record: Dict[str, Any]
) -> None:
    """
    Sends an interactive, rich approval card to Telegram using MarkdownV2.

    Args:
        chat_id: The Telegram chat ID.
        bot_token: The Telegram bot token.
        queue_id: The UUID of the action_queue item.
        job: The job record dictionary.
        eval_record: The evaluation record dictionary.
    
    Raises:
        RuntimeError: If the API request fails, preventing the pipeline from advancing.
    """
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or MY_TELEGRAM_CHAT_ID")

    title = _escape_md(job.get('title', 'Unknown Title'))
    company = _escape_md(job.get('company', 'Unknown Company'))
    score = eval_record.get('score', 0)
    
    # Matches and Gaps
    tech_matches = eval_record.get('tech_matches', '[]')
    if isinstance(tech_matches, str):
        tech_matches = json.loads(tech_matches)
    matches_text = "\n".join([f"• {_escape_md(t)}" for t in tech_matches]) if tech_matches else "None"
    
    gaps = eval_record.get('gaps', '[]')
    if isinstance(gaps, str):
        gaps = json.loads(gaps)
    gaps_text = "\n".join([f"• {_escape_md(g)}" for g in gaps]) if gaps else "None"

    # Email
    email = eval_record.get('contact_email')
    email_display = _escape_md(email) if email else "⚠️ No application email found"
    email_type = _escape_md(eval_record.get('email_type', 'UNKNOWN'))
    
    if email:
        email_section = f"📧 *Application*\n{email_display}\nType: {email_type}\n\n"
        email_note = "📝 *Email*\nDynamic application email will be generated after approval\\.\n\n"
        buttons = [
            {"text": "✅ Approve", "callback_data": f"approve:{queue_id}"},
            {"text": "❌ Skip", "callback_data": f"skip:{queue_id}"}
        ]
    else:
        job_url = job.get('url', '')
        # Telegram MarkdownV2 requires special escaping for URLs? Actually just don't escape it inside the () of [text](url).
        email_section = f"📧 *Application*\n{email_display}\n🌐 *Application URL:* [Apply here]({job_url})\n\n"
        email_note = "⚠️ *Manual application required*\\.\n\n"
        buttons = [
            {"text": "✅ Applied Manually / Dismiss", "callback_data": f"skip:{queue_id}"}
        ]
    
    # Documents
    req_docs_json = eval_record.get('required_documents', '{}')
    if isinstance(req_docs_json, str):
        try:
            req_docs = json.loads(req_docs_json)
        except:
            req_docs = {}
    else:
        req_docs = req_docs_json or {}
        
    doc_lines = []
    has_missing_required = False
    for doc, req in req_docs.items():
        if doc in ["CV", "Cover Letter"]:
            doc_lines.append(f"✅ {_escape_md(doc)}")
        elif req == "REQUIRED_AT_APPLICATION":
            doc_lines.append(f"❌ {_escape_md(doc)}")
            has_missing_required = True
        else:
            doc_lines.append(f"❌ {_escape_md(doc)}")
            doc_lines.append(f"ℹ️ _Not required at application stage_")
            
    doc_text = "\n".join(doc_lines) if doc_lines else "✅ CV\n✅ Cover Letter"

    text = (
        f"🚀 *JOB MATCH FOUND*\n\n"
        f"💼 *Title:* {title}\n"
        f"🏢 *Company:* {company}\n"
        f"🎯 *Match Score:* {score}/100\n\n"
        f"✅ *Strong Matches*\n{matches_text}\n\n"
        f"⚠️ *Gaps*\n{gaps_text}\n\n"
        f"{email_section}"
        f"📄 *Documents*\n{doc_text}\n\n"
        f"{email_note}"
        f"📎 *CV*\n`{_escape_md(job.get('id', ''))[:16]}_cv\\.pdf`"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "reply_markup": {
            "inline_keyboard": [
                buttons
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
