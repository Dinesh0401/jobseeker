"""
Runner script for local Gmail SMTP dispatcher test.
Executes dispatch_approved_applications() with full INFO logging.
"""

import logging
import sys

# Configure logging to show all operations cleanly
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger("dispatcher-test")

if __name__ == "__main__":
    logger.info("Starting local application dispatch worker...")
    try:
        from src.dispatchers.gmail import dispatch_approved_applications
        dispatch_approved_applications()
        logger.info("Dispatch run completed.")
    except Exception as e:
        logger.error(f"Dispatch worker encountered an error: {e}", exc_info=True)
        sys.exit(1)
