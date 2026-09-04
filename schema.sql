-- ============================================================
-- Job Hunter v1 — Database Schema
-- ============================================================
-- PostgreSQL / Supabase
--
-- Application lifecycle:
-- INGESTED → EVALUATED → MATCHED → ASSETS_READY
-- → PENDING_APPROVAL → APPROVED → DISPATCHING
-- → SENT / SUBMITTED
-- → FOLLOW_UP / INTERVIEW / REJECTED / CLOSED
--
-- Dispatch execution failures are tracked in action_queue.status,
-- NOT as an application_state.
-- ============================================================


-- ============================================================
-- CLEANUP (Ensures idempotent execution on fresh/test databases)
-- ============================================================

DROP TABLE IF EXISTS action_queue CASCADE;
DROP TABLE IF EXISTS application_assets CASCADE;
DROP TABLE IF EXISTS job_evaluations CASCADE;
DROP TABLE IF EXISTS jobs CASCADE;
DROP TYPE IF EXISTS application_state CASCADE;
DROP FUNCTION IF EXISTS update_jobs_updated_at() CASCADE;
DROP FUNCTION IF EXISTS transition_job_state CASCADE;


-- ============================================================
-- ENUMS
-- ============================================================

CREATE TYPE application_state AS ENUM (
    'INGESTED',
    'EVALUATED',
    'MATCHED',
    'ASSETS_READY',
    'PENDING_APPROVAL',
    'APPROVED',
    'DISPATCHING',
    'SENT',
    'SUBMITTED',
    'FOLLOW_UP',
    'INTERVIEW',
    'REJECTED',
    'CLOSED'
);


-- ============================================================
-- CORE TABLE: JOBS
-- ============================================================

CREATE TABLE jobs (
    id TEXT PRIMARY KEY,

    -- Example: linkedin, indeed, manual, email
    source TEXT NOT NULL,

    title TEXT NOT NULL,
    company TEXT NOT NULL,

    -- Used for URL-level deduplication
    url TEXT UNIQUE NOT NULL,

    description TEXT,

    state application_state NOT NULL DEFAULT 'INGESTED',

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


-- ============================================================
-- JOB EVALUATIONS
-- ============================================================

CREATE TABLE job_evaluations (
    job_id TEXT PRIMARY KEY
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    score INTEGER NOT NULL
        CHECK (score >= 0 AND score <= 100),

    -- Example: EMAIL, REGEX, GEMINI
    method TEXT,

    -- Deterministically extracted contact email
    contact_email TEXT,

    is_visa_compatible BOOLEAN,

    german_requirement TEXT
        CHECK (
            german_requirement IN (
                'MANDATORY_C1_PLUS',
                'PREFERRED_B1_B2',
                'OPTIONAL_A1_A2',
                'UNKNOWN'
            )
        ),

    -- Minimum years of experience extracted from job description
    min_experience INTEGER,

    -- Matched technologies
    tech_matches JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- Missing qualifications
    gaps JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- References to valid profile/project entries
    tailored_cv_bullets JSONB NOT NULL DEFAULT '[]'::JSONB,

    -- LLM-generated pitch
    cover_letter_pitch TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


-- ============================================================
-- APPLICATION ASSETS
-- ============================================================

CREATE TABLE application_assets (
    job_id TEXT PRIMARY KEY
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    -- Generated CV PDF path
    cv_pdf_path TEXT,

    -- Generated cover letter
    cover_letter_body TEXT,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);


-- ============================================================
-- ACTION QUEUE
-- Telegram approval → email dispatch pipeline
-- ============================================================

CREATE TABLE action_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    job_id TEXT NOT NULL
        REFERENCES jobs(id)
        ON DELETE CASCADE,

    -- Unique key used to prevent duplicate dispatch
    idempotency_key UUID NOT NULL DEFAULT gen_random_uuid(),

    -- Telegram chat allowed to approve this action
    telegram_chat_id TEXT NOT NULL,

    -- Dispatch execution state
    status TEXT NOT NULL DEFAULT 'QUEUED'
        CHECK (
            status IN (
                'QUEUED',
                'APPROVED_FOR_DISPATCH',
                'EXECUTING',
                'DONE',
                'FAILED'
            )
        ),

    approved_at TIMESTAMP WITH TIME ZONE,

    executed_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_action_queue_idempotency
        UNIQUE (idempotency_key)
);


-- ============================================================
-- INDEXES
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_jobs_state
    ON jobs(state);

CREATE INDEX IF NOT EXISTS idx_jobs_url
    ON jobs(url);

CREATE INDEX IF NOT EXISTS idx_jobs_created
    ON jobs(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_action_queue_pending
    ON action_queue(status)
    WHERE status = 'APPROVED_FOR_DISPATCH';

CREATE INDEX IF NOT EXISTS idx_action_queue_idempotency
    ON action_queue(idempotency_key);


-- ============================================================
-- STATE TRANSITION FUNCTION
-- ============================================================
-- PostgreSQL owns application-state transitions.
--
-- Invalid transitions raise an exception.
-- The row is locked with FOR UPDATE before changing state.
-- ============================================================

CREATE OR REPLACE FUNCTION transition_job_state(
    p_job_id TEXT,
    p_new_state application_state
)
RETURNS VOID AS $$
DECLARE
    v_current application_state;
    v_valid BOOLEAN := FALSE;
BEGIN

    -- Lock the job row so concurrent workers cannot
    -- perform conflicting state transitions.
    SELECT state
    INTO v_current
    FROM jobs
    WHERE id = p_job_id
    FOR UPDATE;


    -- Job must exist
    IF v_current IS NULL THEN
        RAISE EXCEPTION 'Job not found: %', p_job_id;
    END IF;


    -- ========================================================
    -- VALID TRANSITION MATRIX
    -- ========================================================

    v_valid := CASE

        -- INGESTED
        WHEN v_current = 'INGESTED'
             AND p_new_state = 'EVALUATED'
        THEN TRUE


        -- EVALUATED
        WHEN v_current = 'EVALUATED'
             AND p_new_state IN (
                 'MATCHED',
                 'REJECTED'
             )
        THEN TRUE


        -- MATCHED
        WHEN v_current = 'MATCHED'
             AND p_new_state IN (
                 'ASSETS_READY',
                 'REJECTED'
             )
        THEN TRUE


        -- ASSETS_READY
        WHEN v_current = 'ASSETS_READY'
             AND p_new_state = 'PENDING_APPROVAL'
        THEN TRUE


        -- PENDING_APPROVAL
        WHEN v_current = 'PENDING_APPROVAL'
             AND p_new_state IN (
                 'APPROVED',
                 'REJECTED'
             )
        THEN TRUE


        -- APPROVED
        WHEN v_current = 'APPROVED'
             AND p_new_state = 'DISPATCHING'
        THEN TRUE


        -- DISPATCHING
        WHEN v_current = 'DISPATCHING'
             AND p_new_state IN (
                 'SENT',
                 'SUBMITTED'
             )
        THEN TRUE


        -- SENT / SUBMITTED
        WHEN v_current IN (
                 'SENT',
                 'SUBMITTED'
             )
             AND p_new_state IN (
                 'FOLLOW_UP',
                 'INTERVIEW',
                 'REJECTED',
                 'CLOSED'
             )
        THEN TRUE


        ELSE FALSE

    END;


    -- ========================================================
    -- REJECT INVALID TRANSITION
    -- ========================================================

    IF NOT v_valid THEN

        RAISE EXCEPTION
            'Invalid state transition: % -> %',
            v_current,
            p_new_state;

    END IF;


    -- ========================================================
    -- UPDATE STATE
    -- ========================================================

    UPDATE jobs
    SET
        state = p_new_state,
        updated_at = NOW()
    WHERE id = p_job_id;

END;
$$ LANGUAGE plpgsql;


-- ============================================================
-- ROW LEVEL SECURITY
-- ============================================================

ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;

ALTER TABLE job_evaluations ENABLE ROW LEVEL SECURITY;

ALTER TABLE application_assets ENABLE ROW LEVEL SECURITY;

ALTER TABLE action_queue ENABLE ROW LEVEL SECURITY;


-- ============================================================
-- SERVICE ROLE POLICIES
-- ============================================================

CREATE POLICY "Service role access on jobs"
    ON jobs
    FOR ALL
    USING (auth.role() = 'service_role');


CREATE POLICY "Service role access on job_evaluations"
    ON job_evaluations
    FOR ALL
    USING (auth.role() = 'service_role');


CREATE POLICY "Service role access on application_assets"
    ON application_assets
    FOR ALL
    USING (auth.role() = 'service_role');


CREATE POLICY "Service role access on action_queue"
    ON action_queue
    FOR ALL
    USING (auth.role() = 'service_role');


-- ============================================================
-- UPDATED_AT TRIGGER
-- ============================================================

CREATE OR REPLACE FUNCTION update_jobs_updated_at()
RETURNS TRIGGER AS $$
BEGIN

    NEW.updated_at = NOW();

    RETURN NEW;

END;
$$ LANGUAGE plpgsql;


DROP TRIGGER IF EXISTS trg_jobs_updated_at ON jobs;
CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_jobs_updated_at();


-- ============================================================
-- END OF SCHEMA
-- ===========================================================