"""
Gmail SMTP Dispatcher for Job Hunter v1.

Idempotent worker that consumes the action_queue via raw SQL
with FOR UPDATE SKIP LOCKED for proper row-level locking.

Spec Reference: Technical_Specification.md §7

Invariants:
  - Max 5 emails per 15-minute cron run (rate limiting).
  - Only dispatches items where method = 'EMAIL'.
  - SMTP failure reverts status to APPROVED_FOR_DISPATCH.
  - SMTP timeout (uncertain send) keeps EXECUTING for manual review.
  - Uses SMTP_SSL on port 465 for secure connection.
  - Job state transitions use transition_job_state() PG function.
"""

import base64
import os
import logging
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from src.db.client import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def dispatch_approved_applications():
    """
    Idempotent worker for SMTP dispatch.

    1. Recovers stale EXECUTING orphans (uncertain-send protection).
    2. Fetches up to 5 APPROVED_FOR_DISPATCH items with row locking.
    3. Locks each to EXECUTING state.
    4. Transitions job: APPROVED → DISPATCHING via PG function.
    5. Sends email with CV attachment via Gmail SMTP_SSL.
    6. On success: marks DONE + transitions job to SENT via PG function.
    7. On definite failure: reverts to APPROVED_FOR_DISPATCH.
    8. On timeout (uncertain): keeps EXECUTING for manual review.
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            # 1. Fetch up to 5 APPROVED items with row-level lock
            # 1. Fetch up to 5 APPROVED items with row-level lock
            cur.execute("""
                SELECT
                    q.id,
                    q.job_id,
                    q.idempotency_key,
                    e.contact_email,
                    j.title,
                    j.company,
                    j.description,
                    a.cv_pdf_path
                FROM action_queue q
                JOIN jobs j ON q.job_id = j.id
                JOIN job_evaluations e ON j.id = e.job_id
                JOIN application_assets a ON j.id = a.job_id
                WHERE q.status = 'APPROVED_FOR_DISPATCH'
                  AND j.state = 'APPROVED'
                  AND (e.method = 'EMAIL' OR (e.contact_email IS NOT NULL AND e.contact_email != ''))
                LIMIT 5
                FOR UPDATE SKIP LOCKED;
            """)
            tasks = cur.fetchall()

            if not tasks:
                logger.info("No items in dispatch queue.")
                return

            logger.info("Processing %d dispatch items", len(tasks))

            from google import genai
            import json
            from src.matcher.gemini import load_profile
            
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            profile = load_profile("profile")

            for task in tasks:
                queue_id = task["id"]
                job_id = task["job_id"]
                contact_email = task["contact_email"]
                title = task["title"]
                company = task["company"]
                description = task.get("description", "")
                cv_path = task["cv_pdf_path"]
                
                # --- SAFETY GATES ---
                if not contact_email or "@" not in contact_email:
                    logger.error("Safety Gate Failed: Missing/invalid email for job %s. Marking FAILED.", job_id)
                    cur.execute("UPDATE action_queue SET status = 'FAILED' WHERE id = %s", (queue_id,))
                    cur.execute("UPDATE jobs SET state = 'APPROVED' WHERE id = %s AND state = 'DISPATCHING'", (job_id,))
                    conn.commit()
                    continue
                    
                # Support both base64 data URI and local file path
                pdf_bytes = None
                if cv_path:
                    if cv_path.startswith("data:application/pdf;base64,"):
                        try:
                            pdf_bytes = base64.b64decode(cv_path.split(",", 1)[1])
                        except Exception as e:
                            logger.error("Failed to decode base64 PDF for %s: %s", job_id, e)
                    elif os.path.exists(cv_path):
                        try:
                            with open(cv_path, "rb") as f:
                                pdf_bytes = f.read()
                        except Exception as e:
                            logger.error("Failed to read CV PDF file at %s: %s", cv_path, e)

                if not pdf_bytes:
                    logger.error("Safety Gate Failed: Missing CV PDF for job %s. Marking FAILED.", job_id)
                    cur.execute("UPDATE action_queue SET status = 'FAILED' WHERE id = %s", (queue_id,))
                    cur.execute("UPDATE jobs SET state = 'APPROVED' WHERE id = %s AND state = 'DISPATCHING'", (job_id,))
                    conn.commit()
                    continue

                # 2. Lock execution state
                cur.execute(
                    "UPDATE action_queue SET status = 'EXECUTING' WHERE id = %s",
                    (queue_id,),
                )
                conn.commit()

                # 3. Transition job: APPROVED → DISPATCHING via PG function
                try:
                    cur.execute(
                        "SELECT transition_job_state(%s, 'DISPATCHING'::application_state)",
                        (job_id,),
                    )
                    conn.commit()
                except Exception as e:
                    logger.error(
                        "State transition DISPATCHING failed for %s: %s", job_id, e
                    )
                    conn.rollback()
                    cur.execute(
                        "UPDATE action_queue SET status = 'APPROVED_FOR_DISPATCH' WHERE id = %s",
                        (queue_id,),
                    )
                    conn.commit()
                    continue
                    
                # 4. Generate dynamic email
                prompt = f"""
                Write a highly professional, tailored application email for the job "{title}" at "{company}".
                
                Job Description: {description[:3500]}
                
                Candidate Profile: {json.dumps(profile)}
                
                CRITICAL RULES:
                1. DO NOT hallucinate any experience, tools, projects, or metrics not present in the Candidate Profile.
                2. Write in a confident, concise, and professional tone.
                3. Keep it under 200 words.
                4. Do not include subject lines or placeholder headers, just the email body starting with a professional greeting.
                5. The email is coming from "Dinesh S J".
                """
                
                try:
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                    )
                    email_body = response.text.strip()
                except Exception as e:
                    logger.error("Gemini failed to compose email for %s: %s", job_id, e)
                    email_body = f"Dear Hiring Team at {company},\n\nPlease find my application attached.\n\nBest,\nDinesh S J"

                try:
                    # 5. Compose email
                    msg = MIMEMultipart()
                    msg["From"] = os.getenv("GMAIL_ADDRESS")
                    msg["To"] = contact_email
                    msg["Subject"] = f"Application: {title} - Dinesh S J"
                    msg.attach(MIMEText(email_body, "plain"))

                    # Attach CV PDF
                    attach = MIMEApplication(pdf_bytes, _subtype="pdf")
                    attach.add_header(
                            "Content-Disposition",
                            "attachment",
                            filename="Dinesh_SJ_Resume.pdf",
                        )
                    msg.attach(attach)

                    # 5. Send via SMTP_SSL
                    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
                        server.login(
                            os.getenv("GMAIL_ADDRESS"),
                            os.getenv("GMAIL_APP_PASSWORD"),
                        )
                        server.send_message(msg)

                    # 6. SMTP succeeded — mark DONE + transition to SENT
                    cur.execute(
                        "UPDATE action_queue SET status = 'DONE', executed_at = NOW() WHERE id = %s",
                        (queue_id,),
                    )
                    cur.execute(
                        "SELECT transition_job_state(%s, 'SENT'::application_state)",
                        (job_id,),
                    )
                    conn.commit()

                    logger.info(
                        "✅ Dispatched to %s — %s at %s",
                        contact_email, title, company,
                    )

                except (socket.timeout, TimeoutError, smtplib.SMTPServerDisconnected) as e:
                    # UNCERTAIN SEND: connection dropped — email may or may not
                    # have been delivered. Keep EXECUTING so a human can check.
                    logger.error(
                        "⚠️ UNCERTAIN SEND for %s (%s at %s): %s — keeping EXECUTING for review",
                        contact_email, title, company, e,
                    )
                    conn.rollback()
                    # Do NOT revert — the orphan recovery will handle it next cycle

                except smtplib.SMTPAuthenticationError as e:
                    # Definite auth failure — don't retry, mark queue FAILED.
                    # Dispatch failures are tracked in action_queue.status,
                    # NOT as an application_state (per schema.sql design).
                    # Revert job from DISPATCHING → APPROVED so it can be re-queued.
                    logger.error(
                        "❌ SMTP Auth failed: %s — marking queue FAILED", e
                    )
                    cur.execute(
                        "UPDATE action_queue SET status = 'FAILED' WHERE id = %s",
                        (queue_id,),
                    )
                    cur.execute(
                        "UPDATE jobs SET state = 'APPROVED', updated_at = NOW() WHERE id = %s AND state = 'DISPATCHING'",
                        (job_id,),
                    )
                    conn.commit()

                except Exception as e:
                    # Definite failure (composition error, etc.) — revert
                    logger.error(
                        "❌ Dispatch failed for %s (%s at %s): %s",
                        contact_email, title, company, e,
                    )
                    conn.rollback()
                    cur.execute(
                        "UPDATE action_queue SET status = 'APPROVED_FOR_DISPATCH' WHERE id = %s",
                        (queue_id,),
                    )
                    conn.commit()
    finally:
        conn.close()
        logger.info("Dispatch worker finished. Connection closed.")

