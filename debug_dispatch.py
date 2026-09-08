import os
from src.db.client import get_connection

conn = get_connection()
with conn.cursor() as cur:
    cur.execute("""
        SELECT q.status, j.state, a.cv_pdf_base64 IS NOT NULL as has_pdf, e.contact_email
        FROM action_queue q
        LEFT JOIN jobs j ON q.job_id = j.id
        LEFT JOIN job_evaluations e ON j.id = e.job_id
        LEFT JOIN application_assets a ON j.id = a.job_id
        WHERE q.status = 'APPROVED_FOR_DISPATCH'
    """)
    rows = cur.fetchall()
    print("Items with APPROVED_FOR_DISPATCH:", rows)
