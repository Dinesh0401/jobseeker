"""
Telegram notification module for Job Hunter v2.

Handles sending rich interactive approval cards to Telegram with
multi-dimensional scores, India eligibility classification, and manual confirmation buttons.
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
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    for char in escape_chars:
        text = text.replace(char, f"\\{char}")
    return text


def send_approval_card(
    chat_id: str,
    bot_token: str,
    queue_id: str,
    job: Dict[str, Any],
    eval_record: Dict[str, Any],
) -> None:
    """
    Sends an interactive approval card with multi-dimensional scores and India eligibility.
    """
    if not bot_token or not chat_id:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN or MY_TELEGRAM_CHAT_ID")

    title = _escape_md(job.get("title", "Unknown Title"))
    company = _escape_md(job.get("company", "Unknown Company"))
    job_url = job.get("url", "")

    # Multi-dimensional scores
    overall_score = eval_record.get("score", 0)
    tech_score = eval_record.get("technical_match_score", overall_score)
    exp_score = eval_record.get("experience_level_score", 100)
    loc_score = eval_record.get("location_eligibility_score", 100)

    # Classification fields
    eligibility_cat = eval_record.get("eligibility_category", "ELIGIBILITY_UNKNOWN")
    seniority_tier = eval_record.get("seniority_tier", "ENTRY_OR_JUNIOR")
    lang_cat = eval_record.get("language_category", "ENGLISH_ONLY")

    eligibility_icons = {
        "WORLDWIDE_REMOTE": "🌏 *Eligibility:* WORLDWIDE REMOTE \\(Open to India\\)",
        "INDIA_ELIGIBLE_REMOTE": "🇮🇳 *Eligibility:* INDIA ELIGIBLE REMOTE",
        "RELOCATION_SUPPORTED": "✈️ *Eligibility:* RELOCATION SUPPORTED \\(Visa Pathway\\)",
        "ELIGIBILITY_UNKNOWN": "❓ *Eligibility:* UNKNOWN \\(Check application portal\\)",
    }
    eligibility_display = eligibility_icons.get(
        eligibility_cat, f"⚠️ *Eligibility:* {_escape_md(eligibility_cat)}"
    )

    # Matches and Gaps
    tech_matches = eval_record.get("tech_matches", "[]")
    if isinstance(tech_matches, str):
        try:
            tech_matches = json.loads(tech_matches)
        except Exception:
            tech_matches = []
    matches_text = "\n".join([f"• {_escape_md(t)}" for t in tech_matches[:5]]) if tech_matches else "None"

    gaps = eval_record.get("gaps", "[]")
    if isinstance(gaps, str):
        try:
            gaps = json.loads(gaps)
        except Exception:
            gaps = []
    gaps_text = "\n".join([f"• {_escape_md(g)}" for g in gaps[:4]]) if gaps else "None"

    # Contact Email & Mode
    email = eval_record.get("contact_email")
    email_display = _escape_md(email) if email else "None \\(Portal Application\\)"
    email_type = _escape_md(eval_record.get("email_type", "UNKNOWN"))

    if email:
        mode_header = f"📧 *Mode:* Direct Email \\({email_display}\\)\nType: {email_type}\n\n"
        mode_note = "📝 *Action:* Dynamic application email will be dispatched upon approval\\.\n\n"
        buttons = [
            [
                {"text": "✅ Approve Email", "callback_data": f"approve:{queue_id}"},
                {"text": "❌ Skip", "callback_data": f"skip:{queue_id}"},
            ]
        ]
    else:
        mode_header = f"🌐 *Mode:* Manual Portal Application\n🔗 *URL:* [Open Job Posting]({job_url})\n\n"
        mode_note = "⚠️ *Action:* Apply via the portal link, then click Confirm below\\.\n\n"
        buttons = [
            [
                {"text": "🌐 Open Portal", "url": job_url},
                {"text": "✅ Confirm Applied", "callback_data": f"manual:{queue_id}"},
            ],
            [
                {"text": "❌ Dismiss", "callback_data": f"skip:{queue_id}"}
            ]
        ]

    # Documents Checklist
    cv_filename = f"{_escape_md(job.get('id', ''))[:16]}_cv\\.pdf"

    text = (
        f"🚀 *CAREER OPPORTUNITY MATCH*\n\n"
        f"💼 *Title:* {title}\n"
        f"🏢 *Company:* {company}\n"
        f"🎯 *Overall Fit:* {overall_score}/100\n"
        f"📊 *Breakdown:* Tech: {tech_score} \\| Exp: {exp_score} \\| Loc: {loc_score}\n\n"
        f"{eligibility_display}\n"
        f"👶 *Seniority:* {_escape_md(seniority_tier)}\n"
        f"🗣️ *Language:* {_escape_md(lang_cat)}\n\n"
        f"✅ *Key Matches*\n{matches_text}\n\n"
        f"⚠️ *Key Gaps*\n{gaps_text}\n\n"
        f"{mode_header}"
        f"{mode_note}"
        f"📎 *Tailored CV:* `{cv_filename}`"
    )

    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "MarkdownV2",
        "reply_markup": {"inline_keyboard": buttons},
    }

    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
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
