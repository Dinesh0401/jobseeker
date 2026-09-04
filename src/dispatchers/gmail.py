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

import os
import logging
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication

from src.db.client import get_connection

logger = logging.getLogger(__name__)


def _recover_stale_executing(conn):
    """
    Recover EXECUTING items that are older than 10 minutes.

    These are orphans from a previous run that crashed after
    SMTP send but before the DONE commit (uncertain-send case).
    They are reverted to APPROVED_FOR_DISPATCH for re-evaluation.
    """
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE action_queue
            SET status = 'APPROVED_FOR_DISPATCH'
            WHERE status = 'EXECUTING'
              AND created_at < NOW() - INTERVAL '10 minutes'
            RETURNING id;
        """)
        recovered = cur.fetchall()
        if recovered:
            conn.commit()
            logger.warning(
                "Recovered %d stale EXECUTING items: %s",
                len(recovered),
                [r["id"] for r in recovered],
            )


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
        # Step 0: Recover any orphaned EXECUTING items
        _recover_stale_executing(conn)

        with conn.cursor() as cur:
            # 1. Fetch up to 5 APPROVED items with row-level lock
            cur.execute("""
                SELECT
                    q.id,
                    q.job_id,
                    q.idempotency_key,
                    e.contact_email,
                    j.title,
                    j.company,
                    a.cover_letter_body,
                    a.cv_pdf_path
                FROM action_queue q
                JOIN jobs j ON q.job_id = j.id
                JOIN job_evaluations e ON j.id = e.job_id
                JOIN application_assets a ON j.id = a.job_id
                WHERE q.status = 'APPROVED_FOR_DISPATCH'
                  AND e.method = 'EMAIL'
                LIMIT 5
                FOR UPDATE SKIP LOCKED;
            """)
            tasks = cur.fetchall()

            if not tasks:
                logger.info("No items in dispatch queue.")
                return

            logger.info("Processing %d dispatch items", len(tasks))

            for task in tasks:
                queue_id = task["id"]
                job_id = task["job_id"]
                contact_email = task["contact_email"]
                title = task["title"]
                company = task["company"]
                cover_letter = task["cover_letter_body"]
                cv_path = task["cv_pdf_path"]

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

                try:
                    # 4. Compose email
                    msg = MIMEMultipart()
                    msg["From"] = os.getenv("GMAIL_ADDRESS")
                    msg["To"] = contact_email
                    msg["Subject"] = f"Application: {title} - Dinesh S J"
                    msg.attach(MIMEText(cover_letter or "", "plain"))

                    # Attach CV PDF if exists
                    if cv_path and os.path.exists(cv_path):
                        with open(cv_path, "rb") as f:
                            attach = MIMEApplication(f.read(), _subtype="pdf")
                            attach.add_header(
                                "Content-Disposition",
                                "attachment",
                                filename="Dinesh_SJ_Resume.pdf",
                            )
                            msg.attach(attach)
                    else:
                        logger.warning(
                            "CV PDF not found at %s for job %s", cv_path, job_id
                        )

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

