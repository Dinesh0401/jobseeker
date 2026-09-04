# Technical Specification: Job Hunter v1

> **Author**: @pm (Product Manager & Architect)
> **Version**: 1.1.0
> **Status**: ✅ APPROVED
> **Date**: 2026-09-01

---

## 1. System Architecture and Component Boundaries

The Job Hunter v1 is an asynchronous, state-driven application designed to autonomously evaluate, prepare, and queue job applications for human approval.

**Component Flow:**

1. **Collectors:** Python scripts (triggered via GitHub Actions) ingest job postings from RSS, APIs, and IMAP emails.
2. **Deterministic Extractor:** Python regex engine normalizes URLs, deduplicates records, and extracts hard facts (emails, experience, German proficiency).
3. **Semantic Evaluator:** Gemini 2.5 Flash analyzes the job against the candidate profile and extracted facts.
4. **Asset Generator:** Dynamic generation of LaTeX-based CVs and customized outreach pitches.
5. **Database (Source of Truth):** Supabase PostgreSQL manages all application state, evaluations, and queueing.
6. **Control Plane:** Telegram Bot API displays interactive cards. A Supabase Edge Function (webhook) receives approvals.
7. **Dispatch Worker:** GitHub Actions cron job consumes the queue, executing idempotent operations via Gmail SMTP or preparing ATS instructions.

---

## 2. PostgreSQL Database Schema

```sql
-- ============================================================
-- ENUMS
-- ============================================================
CREATE TYPE application_state AS ENUM (
    'INGESTED', 'EVALUATED', 'MATCHED', 'ASSETS_READY',
    'PENDING_APPROVAL', 'APPROVED', 'DISPATCHING',
    'SENT', 'SUBMITTED', 'FOLLOW_UP', 'INTERVIEW', 'REJECTED', 'CLOSED'
);

-- ============================================================
-- CORE TABLES
-- ============================================================
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,                          -- SHA256(source+title+company+url)
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    description TEXT,
    state application_state DEFAULT 'INGESTED',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE job_evaluations (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,                       -- 0–100 match score
    method TEXT,                                  -- e.g. 'gemini-2.5-flash'
    contact_email TEXT,                           -- Deterministically extracted
    is_visa_compatible BOOLEAN,
    german_requirement TEXT,                      -- MANDATORY_C1_PLUS | PREFERRED_B1_B2 | OPTIONAL_A1_A2 | UNKNOWN
    min_experience INTEGER,                       -- Extracted YoE baseline
    tech_matches JSONB,                           -- Matched technologies
    gaps JSONB                                    -- Missing qualifications
);

CREATE TABLE application_assets (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    cv_pdf_path TEXT,
    cover_letter_body TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE action_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    idempotency_key UUID UNIQUE DEFAULT gen_random_uuid(),  -- Bound at queue creation
    telegram_chat_id TEXT NOT NULL,
    status TEXT DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'APPROVED_FOR_DISPATCH', 'EXECUTING', 'DONE', 'FAILED')),
    approved_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX idx_jobs_state ON jobs(state);
CREATE INDEX idx_jobs_url ON jobs(url);
CREATE INDEX idx_action_queue_pending ON action_queue(status) WHERE status = 'APPROVED_FOR_DISPATCH';
CREATE INDEX idx_action_queue_idempotency ON action_queue(idempotency_key);
```

---

## 3. Explicit Application State Machine

State transitions are strictly enforced by PostgreSQL logic.

```
┌──────────┐     ┌───────────┐     ┌─────────┐     ┌──────────────┐
│ INGESTED │────▶│ EVALUATED │────▶│ MATCHED │────▶│ ASSETS_READY │
└──────────┘     └─────┬─────┘     └────┬────┘     └──────┬───────┘
                       │                │                  │
                       ▼                ▼                  ▼
                  ┌──────────┐    ┌──────────┐    ┌──────────────────┐
                  │ REJECTED │    │ REJECTED │    │ PENDING_APPROVAL │
                  └──────────┘    └──────────┘    └────────┬─────────┘
                                                    ┌──────┴──────┐
                                                    ▼             ▼
                                              ┌──────────┐  ┌──────────┐
                                              │ APPROVED │  │ REJECTED │
                                              └────┬─────┘  └──────────┘
                                                   ▼
                                            ┌──────────────┐
                                            │ DISPATCHING  │
                                            └──┬───────┬───┘
                                               ▼       ▼
                                          ┌──────┐ ┌───────────┐
                                          │ SENT │ │ SUBMITTED │
                                          └──┬───┘ └─────┬─────┘
                                             │           │
                                             ▼           ▼
                                    ┌───────────────────────────┐
                                    │ FOLLOW_UP | INTERVIEW |   │
                                    │ REJECTED  | CLOSED        │
                                    └───────────────────────────┘

                                    FAILED resets to APPROVED for retry
```

### Valid Transitions

| From               | To                                            | Trigger                        |
|--------------------|-----------------------------------------------|--------------------------------|
| `INGESTED`         | `EVALUATED`                                   | Extraction pipeline completes  |
| `EVALUATED`        | `MATCHED` \| `REJECTED`                       | Gemini score above/below gate  |
| `MATCHED`          | `ASSETS_READY` \| `REJECTED`                  | CV/cover letter generated      |
| `ASSETS_READY`     | `PENDING_APPROVAL`                            | Telegram card sent             |
| `PENDING_APPROVAL` | `APPROVED` \| `REJECTED`                      | Telegram callback              |
| `APPROVED`         | `DISPATCHING`                                 | Worker picks up from queue     |
| `DISPATCHING`      | `SENT` \| `SUBMITTED` \| `FAILED`             | SMTP result / ATS instruction  |
| `SENT`/`SUBMITTED` | `FOLLOW_UP` \| `INTERVIEW` \| `REJECTED` \| `CLOSED` | Manual or timed trigger |
| `FAILED`           | `APPROVED`                                    | Reset for retry                |

### State Transition Function

```sql
CREATE OR REPLACE FUNCTION transition_job_state(
    p_job_id TEXT,
    p_new_state application_state
) RETURNS VOID AS $$
DECLARE
    v_current application_state;
    v_valid BOOLEAN := FALSE;
BEGIN
    SELECT state INTO v_current FROM jobs WHERE id = p_job_id FOR UPDATE;

    IF v_current IS NULL THEN
        RAISE EXCEPTION 'Job not found: %', p_job_id;
    END IF;

    v_valid := CASE
        WHEN v_current = 'INGESTED'         AND p_new_state = 'EVALUATED'          THEN TRUE
        WHEN v_current = 'EVALUATED'        AND p_new_state IN ('MATCHED', 'REJECTED') THEN TRUE
        WHEN v_current = 'MATCHED'          AND p_new_state IN ('ASSETS_READY', 'REJECTED') THEN TRUE
        WHEN v_current = 'ASSETS_READY'     AND p_new_state = 'PENDING_APPROVAL'   THEN TRUE
        WHEN v_current = 'PENDING_APPROVAL' AND p_new_state IN ('APPROVED', 'REJECTED') THEN TRUE
        WHEN v_current = 'APPROVED'         AND p_new_state = 'DISPATCHING'        THEN TRUE
        WHEN v_current = 'DISPATCHING'      AND p_new_state IN ('SENT', 'SUBMITTED', 'FAILED') THEN TRUE
        WHEN v_current IN ('SENT', 'SUBMITTED') AND p_new_state IN ('FOLLOW_UP', 'INTERVIEW', 'REJECTED', 'CLOSED') THEN TRUE
        WHEN v_current = 'FAILED'           AND p_new_state = 'APPROVED'           THEN TRUE
        ELSE FALSE
    END;

    IF NOT v_valid THEN
        RAISE EXCEPTION 'Invalid state transition: % -> %', v_current, p_new_state;
    END IF;

    UPDATE jobs SET state = p_new_state WHERE id = p_job_id;
END;
$$ LANGUAGE plpgsql;
```

---

## 4. Deterministic Extraction Pipeline

Executed **before** LLM invocation:

### 4.1 Contact Email
- Regex extracts standard email formats from job description
- **Exclusion filter**: Strips `noreply@`, `example@`, `no-reply@`, `donotreply@`
- Returns `Optional[str]`

### 4.2 Experience Requirements
- Regex maps natural-language experience phrases to integer baselines
- Patterns: `"5+ years"`, `"minimum 3 years"`, `"3-5 years experience"`
- Returns `Optional[int]` (lowest bound)

### 4.3 German Proficiency
- Regex classifies into enumerated tiers:
  - `MANDATORY_C1_PLUS` — fluent/native/C1/C2 required
  - `PREFERRED_B1_B2` — intermediate preferred
  - `OPTIONAL_A1_A2` — basic/beginner mentioned
  - `UNKNOWN` — no German signals detected

**Constraint**: LLM will only evaluate these extracted strings/integers. It is forbidden from independently searching for or inventing contact details.

---

## 5. Gemini Matcher Contract

### Input
- Candidate `profile.json`
- Job description text
- Deterministic facts (emails, experience, language tier)

### Output
Strictly structured JSON:
```json
{
  "score": 78,
  "method": "gemini-2.5-flash",
  "tech_matches": ["Python", "PostgreSQL", "Docker"],
  "gaps": ["Kubernetes", "Go"],
  "tailored_cv_bullets": [
    "profile.experience[exp_techcorp].responsibilities[0]",
    "profile.projects[project_dashboard]"
  ],
  "cover_letter_pitch": "2-3 sentence tailored pitch..."
}
```

**Constraint**: API call must execute independently. Open database transactions are forbidden during LLM network requests.

---

## 6. Telegram Webhook Security Model

The Supabase Edge Function acts solely as a **queue mutator**.

1. **Verification**: Validates `chat_id` against `MY_TELEGRAM_CHAT_ID` environment variable
2. **Payload**: Expects strict `approve:<UUID>` format
3. **Mutation**: Updates `action_queue` to `APPROVED_FOR_DISPATCH` only if current status is `QUEUED`
4. **Constraint**: The webhook does NOT execute SMTP operations

---

## 7. Dispatch and Idempotency Model

1. **Worker Consumption**: GitHub Actions cron job queries `action_queue WHERE status = 'APPROVED_FOR_DISPATCH'`
2. **Rate Limit**: Maximum **5 emails per cron run** (15-minute interval) to protect Gmail reputation
3. **Execution Lock**: Updates status to `EXECUTING`
4. **Idempotency**: Validates `action_queue.idempotency_key` against external dispatch history
5. **Confirmation**: Only upon successful SMTP 200 OK does status change to `DONE` and application state to `SENT`
6. **Timeouts**: SMTP timeout reverts status to `APPROVED_FOR_DISPATCH` for retry, preserving the original idempotency key

---

## 8. CV Generation Integrity Rules

- `cv_builder.py` injects `tailored_cv_bullets` directly into a `.tex` template
- **LaTeX Compilation**: Uses `xu-cheng/latex-action` GitHub Action (Docker-based, zero config)
- **Integrity Constraint**: Bullets provided by Gemini must strictly map to entities within `profile/projects.json` and `profile/experience.json`. Synthesizing unverified employers, tools, or responsibilities is a system violation.

---

## 9. GitHub Actions Responsibilities

| Workflow          | Schedule          | Responsibility                                               |
|-------------------|-------------------|--------------------------------------------------------------|
| `collect.yml`     | Every 1 hour      | Collectors + deterministic pipeline + LLM + Telegram cards   |
| `dispatch.yml`    | Every 15 minutes  | Process `APPROVED_FOR_DISPATCH` queue items (max 5/run)      |
| `followup.yml`    | Daily             | Flag `SENT` applications older than 7 days for review        |

---

## 10. Secret Management

Secrets (`DATABASE_URL`, `BOT_TOKEN`, `GEMINI_API_KEY`, `GMAIL_APP_PASSWORD`) are strictly isolated in GitHub Repository Secrets and Supabase Vault. No hardcoded credentials.

| Secret                    | Storage                  | Access Scope         |
|---------------------------|--------------------------|----------------------|
| `SUPABASE_URL`            | GitHub Actions Secret    | Python workers       |
| `SUPABASE_SERVICE_KEY`    | GitHub Actions Secret    | Python workers       |
| `TELEGRAM_BOT_TOKEN`      | Supabase Vault           | Edge Function only   |
| `MY_TELEGRAM_CHAT_ID`     | Supabase Vault           | Edge Function only   |
| `GEMINI_API_KEY`          | GitHub Actions Secret    | Python workers       |
| `GMAIL_APP_PASSWORD`      | GitHub Actions Secret    | Dispatcher only      |
| `GMAIL_SENDER_ADDRESS`    | GitHub Actions Secret    | Dispatcher only      |

---

## 11. Resolved Decisions

| Decision              | Resolution                                                |
|-----------------------|-----------------------------------------------------------|
| Dispatch Rate Limit   | Cap at **5 emails per 15-minute cron run**                |
| LaTeX Environment     | Use **`xu-cheng/latex-action`** GitHub Action (Docker)    |

---

## 12. File Manifest

```
jobseeker/
├── .agents/
│   ├── agents.md
│   └── skills/
│       ├── spec_driven.md
│       ├── audit_code.md
│       └── job_hunter_stack.md
├── .github/
│   └── workflows/
│       ├── collect.yml
│       ├── dispatch.yml
│       └── followup.yml
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── db/
│   │   ├── __init__.py
│   │   └── client.py
│   ├── evaluators/
│   │   ├── __init__.py
│   │   └── extraction.py
│   ├── matcher/
│   │   ├── __init__.py
│   │   └── gemini.py
│   ├── cv/
│   │   ├── __init__.py
│   │   ├── builder.py
│   │   └── templates/
│   │       └── base.tex
│   ├── dispatcher/
│   │   ├── __init__.py
│   │   └── mailer.py
│   └── collectors/
│       ├── __init__.py
│       └── scraper.py
├── supabase/
│   └── functions/
│       └── telegram-webhook/
│           └── index.ts
├── profile/
│   ├── profile.json
│   ├── projects.json
│   └── experience.json
├── tests/
│   ├── __init__.py
│   ├── test_extraction.py
│   ├── test_state_machine.py
│   └── test_idempotency.py
├── schema.sql
├── requirements.txt
├── pytest.ini
├── .env.example
├── .gitignore
└── README.md
```

---

## 13. Milestone Breakdown

| Milestone | Scope                                                    | Status |
|-----------|----------------------------------------------------------|--------|
| **M1**    | Agent config + Technical Specification                   | ✅      |
| **M2**    | `schema.sql` + `src/db/` + `src/evaluators/` + tests    | 🔲      |
| **M3**    | `supabase/functions/telegram-webhook/`                   | 🔲      |
| **M4**    | Collectors + Matcher + CV + Dispatcher + GH Workflows    | 🔲      |
