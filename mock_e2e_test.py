import sys
import time
from pathlib import Path
import logging
from src.db.client import DatabaseClient
from src.config import load_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_mock_pdf_for_matched_jobs(output_dir: str = "output"):
    """Helper for local testing to create dummy PDFs for all MATCHED jobs and .tex files."""
    config = load_config()
    db = DatabaseClient(config.supabase)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    
    # Minimal valid PDF binary
    minimal_pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R/Resources<<>>>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f\n0000000009 00000 n\n0000000052 00000 n\n0000000101 00000 n\n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n178\n%%EOF\n"
    )
    
    # 1. Create for any .tex in output directory
    for tex_file in out.glob("*_cv.tex"):
        pdf_file = tex_file.with_suffix(".pdf")
        if not pdf_file.exists():
            with open(pdf_file, "wb") as f:
                f.write(minimal_pdf)
            logger.info("Created local mock PDF from tex: %s", pdf_file)

    # 2. Create for any MATCHED jobs in DB
    try:
        matched = db.get_jobs_by_state('MATCHED')
        for job in matched:
            job_id = job['id']
            pdf_path = out / f"{job_id[:16]}_cv.pdf"
            if not pdf_path.exists():
                with open(pdf_path, "wb") as f:
                    f.write(minimal_pdf)
                logger.info("Created local mock PDF for job %s: %s", job_id[:12], pdf_path)
    except Exception as e:
        logger.warning("Could not fetch matched jobs from DB: %s", e)

def insert_mock_e2e_job():
    config = load_config()
    db = DatabaseClient(config.supabase)
    
    # Generate unique URL to avoid skipping on conflict
    unique_suffix = int(time.time())
    url = f"https://example.com/mock-job-e2e-{unique_suffix}"
    
    job_id = db.generate_job_id(
        source="mock_e2e",
        title="Senior Python / Cloud Engineer",
        company="Mock Tech GmbH",
        url=url
    )
    
    description = """
    We are looking for a Senior Python / Cloud Engineer with Python, PostgreSQL, and AWS experience.
    Please send your CV and Cover Letter to jobs@mocktech-domain.com.
    German language requirement: B1/B2 preferred.
    """
    
    logger.info("Inserting mock job: %s", job_id)
    job = db.insert_job(
        source="mock_e2e",
        title="Senior Python / Cloud Engineer",
        company="Mock Tech GmbH",
        url=url,
        description=description.strip()
    )
    
    logger.info("Mock job inserted successfully.")
    logger.info("Next steps:")
    logger.info("1. Run: python -m src.pipeline --phase generate_tex")
    logger.info("2. For local testing without CI latex compiler: python mock_e2e_test.py --mock-pdf")
    logger.info("3. Run: python -m src.pipeline --phase finalize_assets")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--mock-pdf":
        create_mock_pdf_for_matched_jobs()
    else:
        insert_mock_e2e_job()

