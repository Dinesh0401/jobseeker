# Technical Specification: Job Hunter v2

> **Author**: @pm (Product Manager & Architect)  
> **Version**: 2.0.0  
> **Status**: ✅ APPROVED & IMPLEMENTED  
> **Date**: 2026-10-30  
> **Engine**: International AI Career Discovery & Application Engine

---

## 1. System Architecture & Component Boundaries

Job Hunter v2 is an asynchronous, state-driven, international career discovery and application engine designed to autonomously identify, verify, evaluate, and prepare verified job applications for human approval.

### End-to-End Component Flow

1. **Multi-Source Job Adapters:** Modular collectors (`ArbeitnowAdapter`, `JobicyAdapter`, `GreenhousePublicAdapter`) query worldwide remote and European technical boards. Canonical URL normalizer strips marketing/tracking parameters (`utm_*`, `ref`, `gh_src`, etc.).
2. **Relevance Gate & Deduplication:** Pre-filters titles and descriptions against target early-career AI roles (`is_target_role`). Computes deterministic SHA-256 IDs and inserts deduplicated listings into Supabase PostgreSQL in `INGESTED` state.
3. **Deterministic Fact Extractor:** Regex engine extracts hard facts: recruiter/hiring emails, minimum years of experience, document requirements (degree certificates, transcripts), and German language requirements.
4. **International Eligibility & Seniority Classifiers:**
   - **Location:** Categorizes jobs into `WORLDWIDE_REMOTE`, `INDIA_ELIGIBLE_REMOTE`, `RELOCATION_SUPPORTED`, `COUNTRY_RESTRICTED`, or `ELIGIBILITY_UNKNOWN`. Verifies candidate eligibility to apply from India.
   - **Seniority:** Categorizes into `ENTRY_OR_JUNIOR` (0–1 years, Fresher, Graduate, Intern, Working Student) vs. `SENIOR_OR_LEAD` (Senior, Staff, Principal, Lead, Manager). Enforces hard-rejection for senior positions.
   - **Languages:** Validates candidate's English fluency and Basic German (A1). Hard-rejects mandatory German C1+ or other foreign languages while accepting English-first, German-preferred, or basic German roles.
5. **Multi-Dimensional Semantic Matcher:**
   - Evaluates jobs across 4 weighted dimensions: Technical Match (40%), Experience Level (25%), Location Eligibility (20%), and Language Compatibility (15%).
   - Injects genuine candidate profile (`profile.json`, `experience.json`, `projects.json`) into Gemini 2.5 Flash for semantic matching.
   - Restricts experience and project bullet selection to exact verified keys from source files. Fast-fails hard gates without burning LLM tokens. Transitions to `MATCHED` or `REJECTED`.
6. **Truthful CV Generation & Claim Provenance Engine:**
   - Renders LaTeX CV from source profile facts and selected keys.
   - Audits every bullet against source JSON files, recording verifiable claim provenance in `<job_id>_provenance.json`.
   - Validates compiled PDF header, EOF marker, and minimum file size (>2KB). Prevents placeholder text or fictional metrics.
7. **Asset Finalizer & Telegram Control Plane:**
   - Base64-encodes verified PDF into `application_assets`.
   - Transitions job state `MATCHED -> ASSETS_READY -> PENDING_APPROVAL`.
   - Enqueues an action in `action_queue` with an idempotency key.
   - Dispatches a rich Telegram approval card with subscore breakdown, India eligibility badge, and dual-mode buttons (`[🚀 Approve & Send]` for email applications, `[🌐 Open Portal]` + `[✅ Applied Manually]` for ATS portal applications).
8. **Supabase Edge Function (Webhook):**
   - Receives Telegram callback queries.
   - Validates chat ID, updates `action_queue`, and transitions database state atomically (`APPROVED`, `REJECTED`, or `SUBMITTED`).
9. **Dispatch Worker (Gmail SMTP):**
   - Consumes `action_queue` items with `FOR UPDATE SKIP LOCKED` row locking (max 5 items/15 min).
   - Recovers stale `EXECUTING` tasks (>10 min) to prevent lost sends.
   - Enforces Candidate Profile Safety Gate (`assert_profile_ready_for_dispatch()`) to strictly block dispatch if candidate profile contains placeholder data.
   - Sends email with CV attachment via Gmail `SMTP_SSL` (port 465). Transitions job to `SENT`.
10. **Follow-Up Scanner:**
    - Daily scheduled GitHub Actions run scans for applications in `SENT` status older than 7 days.
    - Transitions jobs to `FOLLOW_UP` and notifies the candidate via Telegram.

---

## 2. Database Architecture & Schema

### PostgreSQL State Machine & Core Tables

```sql
-- Application State Enum
CREATE TYPE application_state AS ENUM (
    'INGESTED', 'EVALUATED', 'MATCHED', 'ASSETS_READY',
    'PENDING_APPROVAL', 'APPROVED', 'DISPATCHING',
    'SENT', 'SUBMITTED', 'FOLLOW_UP', 'INTERVIEW', 'REJECTED', 'CLOSED'
);

-- Core Jobs Table
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

-- Job Evaluation Records
CREATE TABLE job_evaluations (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    score INTEGER NOT NULL,                       -- 0–100 overall match score
    method TEXT,                                  -- 'v2.0-multi-dimensional'
    contact_email TEXT,                           -- Deterministically extracted
    is_visa_compatible BOOLEAN,
    german_requirement TEXT,                      -- Language category
    min_experience INTEGER,                       -- Extracted YoE
    tech_matches JSONB,                           -- Matched skills
    gaps JSONB,                                   -- Skill gaps
    tailored_cv_bullets JSONB,                    -- Selected experience/project keys
    cover_letter_pitch TEXT                       -- Tailored application pitch
);

-- Application Assets
CREATE TABLE application_assets (
    job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    cv_pdf_path TEXT,                             -- Base64 URI or storage path
    cover_letter_body TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Action Queue (Idempotent Worker Queue)
CREATE TABLE action_queue (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
    idempotency_key UUID UNIQUE DEFAULT gen_random_uuid(),
    telegram_chat_id TEXT NOT NULL,
    status TEXT DEFAULT 'QUEUED'
        CHECK (status IN ('QUEUED', 'APPROVED_FOR_DISPATCH', 'EXECUTING', 'DONE', 'FAILED')),
    approved_at TIMESTAMP WITH TIME ZONE,
    executed_at TIMESTAMP WITH TIME ZONE
);
```

### State Machine Transition Graph

```
┌──────────┐     ┌───────────┐     ┌─────────┐     ┌──────────────┐
│ INGESTED │────▶│ EVALUATED │────▶│ MATCHED │────▶│ ASSETS_READY │
└──────────┘     └─────┬─────┘     └────┬────┘     └──────┬───────┘
                       │                │                  │
                       ▼                ▼                  ▼
                  ┌──────────┐    ┌──────────┐    ┌──────────────────┐
                  │ REJECTED │    │ REJECTED │    │ PENDING_APPROVAL │
                  └──────────┘    └──────────┘    └───┬─────┬────┬───┘
                                                      │     │    │
                              ┌───────────────────────┘     │    └───────────────────────┐
                              ▼                             ▼                            ▼
                        ┌──────────┐                  ┌──────────┐                 ┌───────────┐
                        │ APPROVED │                  │ REJECTED │                 │ SUBMITTED │
                        └────┬─────┘                  └──────────┘                 └─────┬─────┘
                             ▼                                                           │
                      ┌──────────────┐                                                   │
                      │ DISPATCHING  │                                                   │
                      └──┬───────┬───┘                                                   │
                         │       │                                                       │
                         ▼       ▼                                                       ▼
                    ┌──────┐ ┌───────────┐                                      ┌─────────────────┐
                    │ SENT │ │ SUBMITTED │                                      │ FOLLOW_UP       │
                    └──┬───┘ └─────┬─────┘                                      │ INTERVIEW       │
                       │           │                                            │ REJECTED        │
                       ▼           ▼                                            │ CLOSED          │
              ┌───────────────────────────┐                                     └─────────────────┘
              │ FOLLOW_UP | INTERVIEW |   │
              │ REJECTED  | CLOSED        │
              └───────────────────────────┘
```

### Permitted State Transitions

| From | To | Trigger / Actor |
|---|---|---|
| `INGESTED` | `EVALUATED` | Fact extraction completed |
| `EVALUATED` | `MATCHED` | Multi-dimensional score $\ge$ threshold & hard gates passed |
| `EVALUATED` | `REJECTED` | Hard gate failure (seniority, restricted country, German C1+) or score < threshold |
| `MATCHED` | `ASSETS_READY` | Provenance-backed CV generated and verified |
| `MATCHED` | `REJECTED` | Missing required documentation (e.g. mandatory transcript) |
| `ASSETS_READY` | `PENDING_APPROVAL` | Interactive Telegram approval card dispatched |
| `PENDING_APPROVAL` | `APPROVED` | User taps `[🚀 Approve & Send]` via Telegram |
| `PENDING_APPROVAL` | `SUBMITTED` | User applies on portal and taps `[✅ Applied Manually]` via Telegram |
| `PENDING_APPROVAL` | `REJECTED` | User taps `[❌ Reject]` via Telegram |
| `APPROVED` | `DISPATCHING` | Dispatch worker claims item with row lock |
| `DISPATCHING` | `SENT` | SMTP email dispatched successfully |
| `DISPATCHING` | `SUBMITTED` | Web portal dispatch completed |
| `SENT` / `SUBMITTED` | `FOLLOW_UP` | Scheduled follow-up scanner (7+ days elapsed) |
| `SENT` / `SUBMITTED` | `INTERVIEW` | Candidate receives interview invitation |
| `SENT` / `SUBMITTED` | `REJECTED` | Employer rejection received |
| `SENT` / `SUBMITTED` | `CLOSED` | Job closed or expired |

---

## 3. Candidate Profile: Single Source of Truth & Safety Gate

Candidate career information is sourced strictly from immutable profile files:
- `profile/profile.json` — Identity, contact details, education, technical skills, languages.
- `profile/experience.json` — Professional work and internship history with unique stable keys.
- `profile/projects.json` — Software engineering and AI projects with unique stable keys.

### Candidate Profile Safety Gate
To protect the candidate's professional reputation, the system enforces a strict runtime barrier:
1. `assert_profile_ready_for_dispatch("profile")` runs before any email dispatch.
2. Checks for dummy emails (`example.com`, `your-email@`), placeholder companies (`Example Corp`), fake universities, and placeholder summaries (`TODO`, `Placeholder`).
3. If placeholders are detected, `ProfileValidationError` is raised, execution is aborted, and zero external communications are sent.

---

## 4. International Job Source Adapters

All source adapters inherit from `JobSourceAdapter` and produce normalized `RawJobPosting` instances:

1. **ArbeitnowAdapter (`src/collectors/arbeitnow.py`):**
   - European and global technical jobs API with pagination and exponential backoff retry.
2. **JobicyAdapter (`src/collectors/jobicy.py`):**
   - Global remote jobs feed filtering for technical engineering and AI positions.
3. **GreenhousePublicAdapter (`src/collectors/ats_boards.py`):**
   - Direct integration with public Greenhouse job boards for AI companies.
4. **URL Normalizer (`src/normalizers/url.py`):**
   - Canonicalizes URLs by stripping tracking queries (`utm_*`, `ref`, `gh_src`, `fbclid`). Preserves essential routing parameters.

---

## 5. International Eligibility & Seniority Engine

### Location & India Eligibility (`src/evaluators/eligibility.py`)
- `WORLDWIDE_REMOTE`: Explicit worldwide remote ("Anywhere", "Worldwide", "Global"). Fully eligible from India.
- `INDIA_ELIGIBLE_REMOTE`: Jobs mentioning India or APAC remote regions. Fully eligible.
- `RELOCATION_SUPPORTED`: Roles offering visa sponsorship or relocation assistance to Europe/Germany. Fully eligible as a relocation pathway.
- `COUNTRY_RESTRICTED`: Remote restricted to US-only, UK-only, or non-EU countries without sponsorship. Hard-rejected.
- `GERMANY_REMOTE_ONLY`: Remote within Germany only, without international allowance.

### Seniority Classification (`src/evaluators/seniority.py`)
- Target: 0–1 years, Fresher, Graduate, Entry-Level, Junior, Intern, Working Student.
- Rejection: Titles containing `Senior`, `Lead`, `Staff`, `Principal`, `Head of`, `Director`, `VP`, `Manager`, or requiring $\ge 3$ years of experience are immediately hard-rejected.

### Language Compatibility (`src/evaluators/languages.py`)
- Candidate proficiency: English (Fluent/C2), German (Basic/A1).
- `ENGLISH_ONLY`: 100% compatible.
- `ENGLISH_AND_BASIC_GERMAN_ACCEPTED`: 95% compatible.
- `ENGLISH_REQUIRED_GERMAN_PREFERRED`: 85% compatible.
- `GERMAN_REQUIRED_C1_PLUS`: Hard-rejected. Candidate does not meet mandatory advanced German requirements.

---

## 6. Multi-Dimensional Semantic Matcher

### Scoring Formula

$$\text{Overall Score} = 0.40 \times \text{Tech} + 0.25 \times \text{Exp} + 0.20 \times \text{Loc} + 0.15 \times \text{Lang}$$

- **Technical Score (0–100):** Overlap between candidate verified skills/projects and job requirements.
- **Experience Score (0–100):** Entry/Junior/Working Student = 100; Unknown = 70; Senior = 0.
- **Location Score (0–100):** Worldwide Remote = 100; India Remote = 100; Relocation = 85; Unknown = 40; Country Restricted = 0.
- **Language Score (0–100):** English Only = 100; English + Basic German = 95; German Preferred = 85; German A1/A2 = 80; German C1+ = 0.

### Hard Gate Fast-Fails
Before invoking Gemini, deterministic hard gates verify:
1. Seniority is acceptable (`seniority.is_acceptable`).
2. India eligibility or relocation pathway exists.
3. German C1+ is not mandatory.

If any hard gate fails, the evaluator immediately returns `verdict="REJECT"` and `overall_match_score=0` without burning Gemini API tokens.

---

## 7. Truthful CV Generation & Claim Provenance

1. **LaTeX CV Template:** High-standard professional CV compiled using ModernCV / LaTeX engine.
2. **Provenance Audit (`src/cv/provenance.py`):**
   - Every bullet in the compiled CV is mapped directly back to a verified key in `experience.json` or `projects.json`.
   - Generates `<job_id>_provenance.json` detailing the exact source file and section for every claim.
3. **PDF Validator (`src/cv/pdf_validator.py`):**
   - Asserts valid `%PDF-` header and `%%EOF` marker.
   - Rejects dummy mock files or truncated PDFs (< 2KB).

---

## 8. Telegram Control Plane & Action Queue

### Interactive Card Format
Telegram cards display:
- Job Title, Company, Location, Source.
- Match Breakdown: Overall Score, Technical Overlap, Experience Fit, Location Eligibility, Language Compatibility.
- India Eligibility Badge (`🇮🇳 Remote from India Eligible` or `✈️ Relocation Pathway`).
- Extracted Hiring Email or Application Portal Link.
- Key Matched Projects and Skills.
- Tailored Pitch Preview.

### Dual-Action Inline Keyboard
- For Email Roles: `[🚀 Approve & Send]` | `[❌ Reject]`
- For Portal Roles: `[🌐 Open Portal]` | `[✅ Applied Manually]` | `[❌ Reject]`

---

## 9. Observability & Run Summary

Every pipeline run prints and logs an auditable `RunSummary`:
- Sources attempted vs. successful.
- Total jobs fetched, duplicates skipped, and jobs inserted.
- Hard gate rejections breakdown (seniority, restricted countries, German C1+).
- India-eligible vs. relocation opportunities discovered.
- CVs generated and Telegram approval cards sent.
