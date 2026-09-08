import os
from src.db.client import get_connection

print("Simulating Telegram 'Approve' button press...")

conn = get_connection()
with conn.cursor() as cur:
    # 1. Update action_queue
    cur.execute("""
        UPDATE action_queue 
        SET status = 'APPROVED_FOR_DISPATCH' 
        WHERE status = 'QUEUED'
    """)
    queue_updated = cur.rowcount
    
    # 2. Update job state
    cur.execute("""
        UPDATE jobs 
        SET state = 'APPROVED' 
        WHERE state = 'PENDING_APPROVAL'
    """)
    jobs_updated = cur.rowcount

conn.commit()

print(f"Success! Updated {queue_updated} queue items and {jobs_updated} jobs.")
print("The job is now APPROVED and ready for dispatch.")
