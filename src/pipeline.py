"""
Autonomous pipeline orchestrator for Job Hunter v1.

Phase 1 (generate_tex): INGESTED -> EVALUATED -> MATCHED -> CV .tex generation
Phase 2 (finalize_assets): Verify PDF -> ASSETS_READY -> Telegram -> PENDING_APPROVAL
"""

import argparse
import json
import logging
import os
from pathlib import Path

from src.config import load_config
from src.db.client import DatabaseClient
from src.collectors.scraper import run_collection
from src.evaluators.extraction import run_extraction
from src.evaluators.matcher import evaluate_job
from src.cv.builder import CVBuilder
from src.notifications.telegram import send_approval_card

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(name)s %(levelname)s %(message)s')
logger = logging.getLogger(__name__)

def phase_generate_tex(db: DatabaseClient, profile_path: str = "profile/profile.json", match_threshold: int = 60):
    """
    Runs the deterministic extraction and Gemini matcher.
    For MATCHED jobs, generates the .tex CV without compiling to PDF.
    """
    logger.info("Starting Phase 1: generate_tex")

    # 1. Collect new jobs
    new_count = run_collection(db)
    logger.info(f"Collected {new_count} new jobs")

    # 2. Extract deterministic facts from INGESTED jobs
    ingested = db.get_jobs_by_state('INGESTED')
    for job in ingested:
        extraction = run_extraction(job.get('description', ''))
        evaluation_data = {
            'contact_email': extraction.contact_email,
            'min_experience': extraction.min_experience,
            'german_requirement': extraction.german_requirement.value,
            'score': 0,
        }
        db.upsert_evaluation(job['id'], evaluation_data)
        db.transition_state(job['id'], 'EVALUATED')

    # 3. Run Gemini matcher on EVALUATED jobs
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    evaluated = db.get_jobs_by_state('EVALUATED')
    for job in evaluated:
        eval_record = db.get_evaluation(job['id'])
        deterministic_facts = {
            'contact_email': eval_record.get('contact_email'),
            'min_experience': eval_record.get('min_experience'),
            'german_requirement': eval_record.get('german_requirement', 'UNKNOWN'),
        }

        result = evaluate_job(
            title=job['title'],
            company=job['company'],
            description=job.get('description', ''),
            profile=profile,
            deterministic_facts=deterministic_facts,
        )

        db.upsert_evaluation(job['id'], {
            'score': result.get('score', 0),
            'method': result.get('method', 'UNKNOWN'),
            'contact_email': eval_record.get('contact_email'),  # Keep deterministic email
            'tech_matches': json.dumps(result.get('tech_matches', [])),
            'gaps': json.dumps(result.get('gaps', [])),
            'tailored_cv_bullets': json.dumps(result.get('tailored_cv_bullets', [])),
            'cover_letter_pitch': result.get('cover_letter_pitch', ''),
            'german_requirement': eval_record.get('german_requirement', 'UNKNOWN'),
            'min_experience': eval_record.get('min_experience'),
        })

        if result.get('score', 0) >= match_threshold and result.get('verdict') != 'SKIP':
            db.transition_state(job['id'], 'MATCHED')
            logger.info(f"MATCHED: {job['title']} at {job['company']} (score={result.get('score')})")
        else:
            db.transition_state(job['id'], 'REJECTED')
            logger.info(f"REJECTED: {job['title']} at {job['company']} (score={result.get('score', 0)})")

    # 4. Generate .tex CVs for MATCHED jobs
    matched = db.get_jobs_by_state('MATCHED')
    cv_builder = CVBuilder(profile_dir="profile", output_dir="output")

    for job in matched:
        eval_record = db.get_evaluation(job['id'])
        bullets = eval_record.get('tailored_cv_bullets', [])
        if isinstance(bullets, str):
            bullets = json.loads(bullets)

        logger.info(f"Building .tex for job {job['id']}...")
        # Compile_pdf=False so we yield to latex-action in CI
        cv_builder.build(
            job_id=job['id'],
            tailored_cv_bullets=bullets,
            job_title=job['title'],
            compile_pdf=False
        )
    
    logger.info("Phase 1 complete. Ready for LaTeX compilation.")

def phase_finalize_assets(db: DatabaseClient, output_dir: str = "output"):
    """
    Verifies PDF existence for MATCHED jobs.
    Transitions to ASSETS_READY, then sends Telegram cards and transitions to PENDING_APPROVAL.
    """
    logger.info("Starting Phase 2: finalize_assets")
    
    matched = db.get_jobs_by_state('MATCHED')
    for job in matched:
        job_id = job['id']
        pdf_path = Path(output_dir) / f"{job_id[:16]}_cv.pdf"
        
        # Rule: A job MUST NOT transition to ASSETS_READY unless the PDF exists.
        if not pdf_path.exists():
            error_msg = f"Missing PDF for job {job_id} at {pdf_path}. Cannot transition to ASSETS_READY."
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        # Insert application_assets
        eval_record = db.get_evaluation(job_id)
        cover_letter = eval_record.get('cover_letter_pitch', '')
        
        with db._conn.cursor() as cur:
            cur.execute("""
                INSERT INTO application_assets (job_id, cv_pdf_path, cover_letter_body)
                VALUES (%s, %s, %s)
                ON CONFLICT (job_id) DO UPDATE SET 
                    cv_pdf_path = EXCLUDED.cv_pdf_path,
                    cover_letter_body = EXCLUDED.cover_letter_body;
            """, (job_id, str(pdf_path.absolute()), cover_letter))
            db._conn.commit()
            
        db.transition_state(job_id, 'ASSETS_READY')
        logger.info(f"Assets verified. Transitioned {job_id} to ASSETS_READY.")

    # Process ASSETS_READY to PENDING_APPROVAL
    assets_ready = db.get_jobs_by_state('ASSETS_READY')
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("MY_TELEGRAM_CHAT_ID")
    
    for job in assets_ready:
        job_id = job['id']
        eval_record = db.get_evaluation(job_id)
        
        with db._conn.cursor() as cur:
            # Idempotency: Create action_queue row and get its ID
            # Check if one already exists for this job
            cur.execute("SELECT id FROM action_queue WHERE job_id = %s LIMIT 1", (job_id,))
            row = cur.fetchone()
            if row:
                queue_id = row['id']
                logger.info(f"action_queue item {queue_id} already exists for job {job_id}")
            else:
                cur.execute("""
                    INSERT INTO action_queue (job_id, telegram_chat_id, status)
                    VALUES (%s, %s, 'QUEUED') RETURNING id
                """, (job_id, chat_id))
                queue_id = cur.fetchone()['id']
                db._conn.commit()
                logger.info(f"Created action_queue {queue_id} for job {job_id}")

        # Send Telegram Card
        try:
            send_approval_card(
                chat_id=chat_id,
                bot_token=bot_token,
                queue_id=queue_id,
                job_title=job['title'],
                company=job['company'],
                score=eval_record.get('score', 0),
                email=eval_record.get('contact_email')
            )
        except Exception as e:
            logger.error(f"Failed to send Telegram card for {job_id}: {e}")
            # Stop processing this job so it doesn't move to PENDING_APPROVAL
            continue
        
        # Transition to PENDING_APPROVAL
        db.transition_state(job_id, 'PENDING_APPROVAL')
        logger.info(f"Transitioned {job_id} to PENDING_APPROVAL.")

    logger.info("Phase 2 complete.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunter Autonomous Pipeline")
    parser.add_argument("--phase", choices=["generate_tex", "finalize_assets"], required=True)
    args = parser.parse_args()

    config = load_config()
    db = DatabaseClient(config.supabase)

    if args.phase == "generate_tex":
        threshold = int(os.getenv("MATCH_THRESHOLD", "60"))
        phase_generate_tex(db, match_threshold=threshold)
    elif args.phase == "finalize_assets":
        phase_finalize_assets(db)
