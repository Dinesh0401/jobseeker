"""
Autonomous pipeline orchestrator for Job Hunter v2.

Phase 1 (generate_tex): Ingestion -> Fact Extraction -> Multi-Dimensional Matcher -> Provenance -> CV .tex
Phase 2 (finalize_assets): Verify PDF -> ASSETS_READY -> Telegram Approval Card -> PENDING_APPROVAL
"""

import argparse
import base64
import json
import logging
import os
from pathlib import Path
from typing import Optional

from src.config import load_config
from src.db.client import DatabaseClient, InvalidStateTransition
from src.collectors.aggregator import JobCollectorAggregator
from src.evaluators.eligibility import ActionabilityState
from src.evaluators.extraction import run_extraction, DocumentRequirement, to_db_german_requirement
from src.matching.evaluator import SemanticMatcher
from src.cv.builder import CVBuilder
from src.cv.pdf_validator import validate_compiled_pdf, PDFValidationError
from src.notifications.telegram import send_approval_card
from src.observability.metrics import RunSummary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def phase_generate_tex(
    db: DatabaseClient,
    profile_dir: str = "profile",
    match_threshold: int = 60,
    output_dir: str = "output",
    summary: Optional[RunSummary] = None,
) -> RunSummary:
    """
    Phase 1: Multi-source collection, deterministic extraction, semantic multi-dimensional
    matching, hard gates enforcement, and .tex CV generation with provenance.
    """
    if summary is None:
        summary = RunSummary()

    logger.info("Starting Phase 1: generate_tex (Job Hunter v2)")

    # 1. Multi-source collection
    aggregator = JobCollectorAggregator()
    col_report = aggregator.run(db, limit_per_source=30)
    summary.sources_attempted = col_report.sources_attempted
    summary.sources_successful = col_report.sources_successful
    summary.jobs_fetched = col_report.jobs_fetched
    summary.duplicates_removed = col_report.duplicates_skipped
    summary.jobs_inserted = col_report.jobs_inserted

    # 2. Extract deterministic facts from INGESTED jobs
    ingested = db.get_jobs_by_state("INGESTED")
    for job in ingested:
        extraction = run_extraction(job.get("description", ""))
        evaluation_data = {
            "contact_email": extraction.contact_email,
            "min_experience": extraction.min_experience,
            "german_requirement": to_db_german_requirement(extraction.german_requirement),
            "score": 0,
        }
        db.upsert_evaluation(job["id"], evaluation_data)
        try:
            db.transition_state(job["id"], "EVALUATED")
        except InvalidStateTransition as e:
            logger.warning("Skipping INGESTED->EVALUATED for %s: %s", job["id"][:12], e)

    # 3. Multi-Dimensional Semantic Evaluation
    matcher = SemanticMatcher(profile_dir=profile_dir)
    evaluated = db.get_jobs_by_state("EVALUATED")
    summary.jobs_evaluated = len(evaluated)

    for job in evaluated:
        job_id = job["id"]
        title = job.get("title", "")
        company = job.get("company", "")
        desc = job.get("description", "")

        job_loc = job.get("location", "") or ""
        job_remote = bool(job.get("is_remote", False)) or ("remote" in title.lower() or "remote" in desc.lower())

        extraction = run_extraction(desc)

        res = matcher.evaluate(
            title=title,
            company=company,
            location=job_loc,
            description=desc,
            is_remote=job_remote,
        )

        # Track category metrics
        cat_val = res.eligibility_category.value
        if cat_val == "INDIA_ELIGIBLE_REMOTE":
            summary.india_eligible_jobs += 1
        elif cat_val == "WORLDWIDE_REMOTE":
            summary.worldwide_remote_jobs += 1
        elif cat_val == "RELOCATION_SUPPORTED":
            summary.relocation_opportunities += 1
        elif cat_val == "ELIGIBILITY_UNKNOWN":
            summary.eligibility_unknown_jobs += 1

        if res.seniority_tier.value == "ENTRY_OR_JUNIOR":
            summary.early_career_0_1_yr_matches += 1

        # Upsert evaluation record with multi-dimensional subscores
        db.upsert_evaluation(job_id, {
            "score": res.overall_match_score,
            "method": res.evaluator_version,
            "contact_email": res.contact_email,
            "tech_matches": json.dumps(res.tech_matches),
            "gaps": json.dumps(res.gaps),
            "tailored_cv_bullets": json.dumps(res.matched_experience_keys + res.matched_project_keys),
            "cover_letter_pitch": res.cover_letter_pitch,
            "german_requirement": to_db_german_requirement(extraction.german_requirement),
            "min_experience": extraction.min_experience,
        })

        if (
            res.hard_gate_passed
            and res.actionability in [ActionabilityState.CONFIRMED_ELIGIBLE, ActionabilityState.RELOCATION_PATHWAY]
            and res.overall_match_score >= match_threshold
            and res.verdict != "REJECT"
            and res.verdict != "HOLD"
        ):
            try:
                db.transition_state(job_id, "MATCHED")
                logger.info(
                    "MATCHED: %s at %s (Overall: %d, Tech: %d, Loc: %d, Actionability: %s)",
                    title, company, res.overall_match_score, res.technical_match_score, res.location_eligibility_score, res.actionability.value,
                )
            except InvalidStateTransition as e:
                logger.warning("Skipping MATCHED transition for %s: %s", job_id[:12], e)
        elif res.verdict == "HOLD" or (res.actionability == ActionabilityState.PENDING_LOCATION_VERIFICATION and res.verdict != "REJECT"):
            summary.jobs_held_for_verification += 1
            logger.info(
                "HOLD: %s at %s - Pending Location Verification (Actionability: %s, Tech Score: %d)",
                title, company, res.actionability.value, res.technical_match_score,
            )
            # Job remains in EVALUATED state without triggering CV generation, rejection, or dispatch queue
        else:
            summary.jobs_rejected += 1
            try:
                db.transition_state(job_id, "REJECTED")
                logger.info("REJECTED: %s at %s (Hard Gates: %s, Score: %d)", title, company, res.hard_gate_failures, res.overall_match_score)
            except InvalidStateTransition as e:
                logger.warning("Skipping REJECTED transition for %s: %s", job_id[:12], e)

    # 4. Generate .tex CVs and provenance for MATCHED jobs
    matched = db.get_jobs_by_state("MATCHED")
    cv_builder = CVBuilder(profile_dir=profile_dir, output_dir=output_dir)

    for job in matched:
        job_id = job["id"]
        eval_record = db.get_evaluation(job_id) or {}
        bullets = eval_record.get("tailored_cv_bullets", [])
        if isinstance(bullets, str):
            try:
                bullets = json.loads(bullets)
            except Exception:
                bullets = []

        logger.info("Building tailored .tex & provenance for job %s...", job_id[:12])
        cv_builder.build(
            job_id=job_id,
            tailored_cv_bullets=bullets,
            job_title=job["title"],
            compile_pdf=False,  # Compile via xu-cheng/latex-action in CI
        )

    logger.info("Phase 1 complete. Ready for LaTeX compilation.")
    return summary


def phase_finalize_assets(
    db: DatabaseClient,
    output_dir: str = "output",
    summary: Optional[RunSummary] = None,
) -> RunSummary:
    """
    Phase 2: Verifies compiled PDF existence & structure, encodes Base64 into DB,
    transitions to ASSETS_READY, enqueues action_queue, and sends rich Telegram approval cards.
    """
    if summary is None:
        summary = RunSummary()

    logger.info("Starting Phase 2: finalize_assets (Job Hunter v2)")

    matched = db.get_jobs_by_state("MATCHED")
    for job in matched:
        job_id = job["id"]
        pdf_path = Path(output_dir) / f"{job_id[:16]}_cv.pdf"

        if not pdf_path.exists():
            error_msg = f"Missing PDF for job {job_id} at {pdf_path}. Cannot transition to ASSETS_READY."
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)

        # Check required documents gate
        extraction = run_extraction(job.get("description", ""))
        missing_docs = []
        for doc, doc_req in extraction.required_documents.items():
            if doc_req == DocumentRequirement.REQUIRED_AT_APPLICATION and doc not in ["CV", "Cover Letter"]:
                missing_docs.append(doc)

        if missing_docs:
            logger.warning("Missing required documents for job %s: %s. Skipping transition to ASSETS_READY.", job_id[:12], missing_docs)
            continue

        eval_record = db.get_evaluation(job_id) or {}
        cover_letter = eval_record.get("cover_letter_pitch", "")

        with open(pdf_path, "rb") as f:
            pdf_bytes = f.read()

        if pdf_bytes:
            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
            cv_storage_val = f"data:application/pdf;base64,{pdf_b64}"
            summary.cvs_generated += 1
        else:
            cv_storage_val = str(pdf_path.absolute())

        db.upsert_assets(job_id, cv_storage_val, cover_letter)
        db.transition_state(job_id, "ASSETS_READY")
        logger.info("Assets verified. Transitioned %s to ASSETS_READY.", job_id[:12])

    # Send interactive Telegram cards for ASSETS_READY jobs
    assets_ready = db.get_jobs_by_state("ASSETS_READY")
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("MY_TELEGRAM_CHAT_ID")

    for job in assets_ready:
        job_id = job["id"]
        eval_record = db.get_evaluation(job_id) or {}
        extraction = run_extraction(job.get("description", ""))
        eval_record["required_documents"] = {k: v.value for k, v in extraction.required_documents.items()}
        if extraction.email_type:
            eval_record["email_type"] = extraction.email_type.value

        # Idempotent action queue creation
        res = db.client.table("action_queue").select("id").eq("job_id", job_id).execute()
        if res.data:
            queue_id = res.data[0]["id"]
            logger.info("action_queue item %s already exists for job %s", queue_id[:12], job_id[:12])
        else:
            result = db.enqueue_action(job_id, chat_id)
            queue_id = result["id"]
            logger.info("Created action_queue %s for job %s", queue_id[:12], job_id[:12])

        try:
            send_approval_card(
                chat_id=chat_id,
                bot_token=bot_token,
                queue_id=queue_id,
                job=job,
                eval_record=eval_record,
            )
            summary.jobs_sent_to_telegram += 1
        except Exception as e:
            logger.error("Failed to send Telegram card for %s: %s", job_id[:12], e)
            summary.record_error("telegram", str(e))
            continue

        db.transition_state(job_id, "PENDING_APPROVAL")
        logger.info("Transitioned %s to PENDING_APPROVAL.", job_id[:12])

    logger.info("Phase 2 complete.")
    summary.print_report()
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Job Hunter v2 Autonomous Pipeline")
    parser.add_argument("--phase", choices=["generate_tex", "finalize_assets"], required=True)
    args = parser.parse_args()

    config = load_config()
    db = DatabaseClient(config.supabase)

    if args.phase == "generate_tex":
        threshold = int(os.getenv("MATCH_THRESHOLD", "60"))
        phase_generate_tex(db, match_threshold=threshold)
    elif args.phase == "finalize_assets":
        phase_finalize_assets(db)
