# Job Hunter v2 — International AI Career Discovery & Application Engine

> An autonomous, deterministic, and verifiable career discovery and application engine built with Python 3.11+, Supabase PostgreSQL, Telegram Bot API, and Google Gemini 2.5 Flash.

---

## Overview

**Job Hunter v2** is a personal job discovery engine designed for international AI career opportunities. It targets **early-career roles (0–1 years, junior, fresher, working student, intern)** in Generative AI, LLM Engineering, and Python AI Systems, with dedicated support for **applying from India** (worldwide remote or European relocation pathways).

### Key Architectural Pillars

1. **Candidate Profile Source-of-Truth & Safety Gate:** Real career experience comes exclusively from `profile/` JSON files. Dispatch is blocked if placeholder or dummy data is detected. Zero hallucinated achievements or fictional metrics.
2. **Modular International Job Adapters:** Ingests opportunities from multiple international sources (Arbeitnow, Jobicy, Greenhouse ATS) with canonical URL tracking-parameter stripping.
3. **Deterministic Eligibility & Seniority Engine:**
   - **India Eligibility:** Distinguishes `WORLDWIDE_REMOTE` and `INDIA_ELIGIBLE_REMOTE` from restricted-country roles.
   - **Seniority Gate:** Strictly rejects mid/senior/lead/manager roles ($\ge 3$ years YoE) to focus exclusively on early-career opportunities.
   - **Language Compatibility:** Validates candidate's English fluency and basic German (A1), blocking mandatory German C1+ positions.
4. **Multi-Dimensional Semantic Matcher:** 4-tier weighted evaluation (Technical Match 40%, Experience 25%, Location 20%, Language 15%) with token-saving fast-fail hard gates.
5. **Truthful CV Generation & Claim Provenance:** Generates tailored LaTeX CVs with auditable provenance mapping every statement directly to verified source keys (`<job_id>_provenance.json`).
6. **Telegram Approval Control Plane:** Interactive multi-score decision cards with dual pathways: one-click email application dispatch (`[🚀 Approve & Send]`) and portal submission tracking (`[🌐 Open Portal]` + `[✅ Applied Manually]`).
7. **Idempotent Dispatch Worker:** Gmail SMTP_SSL worker with row-level locking (`FOR UPDATE SKIP LOCKED`), 5 emails/15-minute rate limiting, and stale execution recovery.

---

## Architecture Diagram

```
┌─────────────────┐       ┌────────────────────┐       ┌─────────────────┐
│  Job Adapters   │──────▶│   Supabase (PG)    │◀──────│  Telegram Bot   │
│  (Arbeitnow,    │       │   State Machine    │       │  Edge Function  │
│   Jobicy, ATS)  │       │  & Action Queue    │       │   (Webhooks)    │
└─────────────────┘       └─────────┬──────────┘       └─────────────────┘
                                    │
                         ┌──────────┴──────────┐
                         │                     │
                  ┌──────▼──────┐       ┌──────▼──────┐
                  │ Multi-Score │       │ CV Builder  │
                  │   Matcher   │       │ & Provenance│
                  │  (Gemini)   │       │  (LaTeX)    │
                  └─────────────┘       └──────┬──────┘
                                               │
                                        ┌──────▼──────┐
                                        │ Dispatcher  │
                                        │ (Gmail SMTP)│
                                        └─────────────┘
```

---

## State Machine Flow

```
INGESTED ──▶ EVALUATED ──▶ MATCHED ──▶ ASSETS_READY ──▶ PENDING_APPROVAL
                 │            │                               │
                 ▼            ▼                     ┌─────────┼─────────┐
              REJECTED     REJECTED                 ▼         ▼         ▼
                                                 APPROVED  SUBMITTED  REJECTED
                                                    │
                                                    ▼
                                               DISPATCHING ──▶ SENT ──▶ FOLLOW_UP
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Language & Runtime** | Python 3.11+ / Python 3.14 |
| **Data Validation** | Pydantic v2 |
| **Database** | Supabase PostgreSQL (State Machine, Row-Level Locking) |
| **Edge Functions** | Deno / TypeScript (Telegram Webhook) |
| **Semantic Intelligence** | Google Gemini 2.5 Flash |
| **Document Generation** | LaTeX (`pdflatex` / `xu-cheng/latex-action@v3`) |
| **Mail Transport** | Python `smtplib` (Gmail SMTP_SSL on port 465) |
| **CI/CD & Scheduler** | GitHub Actions (Hourly collection, 15m dispatch, daily follow-up) |
| **Testing** | `pytest`, `pytest-cov`, `pytest-asyncio` (142 unit & integration tests) |

---

## Project Structure

```
jobseeker/
├── .github/workflows/
│   ├── collect.yml             # Hourly job collection, evaluation & CV compilation
│   ├── dispatch.yml            # 15-minute cron for approved application dispatch
│   └── followup.yml            # Daily scanner for follow-up notifications
├── profile/
│   ├── profile.json            # Identity, education, skills, languages
│   ├── experience.json         # Source-of-truth employment & internships
│   └── projects.json           # Source-of-truth technical projects
├── src/
│   ├── collectors/
│   │   ├── base.py             # Adapter interface & RawJobPosting model
│   │   ├── arbeitnow.py        # Arbeitnow API adapter
│   │   ├── jobicy.py           # Jobicy global remote adapter
│   │   ├── ats_boards.py       # Public ATS Greenhouse adapter
│   │   └── aggregator.py       # Multi-source coordinator & role pre-filter
│   ├── normalizers/
│   │   └── url.py              # Canonical URL normalizer
│   ├── evaluators/
│   │   ├── extraction.py       # Deterministic regex facts extractor
│   │   ├── eligibility.py      # India & worldwide remote classifier
│   │   ├── seniority.py        # Early career (0-1 yr) vs senior classifier
│   │   └── languages.py        # Language requirements classifier
│   ├── matching/
│   │   ├── models.py           # Evaluation schemas & result models
│   │   └── evaluator.py        # Multi-dimensional scoring & hard gates
│   ├── profiles/
│   │   ├── models.py           # Pydantic schemas for candidate profile
│   │   ├── validator.py        # Profile validation & dispatch safety gate
│   │   └── loader.py           # Profile loader utilities
│   ├── cv/
│   │   ├── builder.py          # LaTeX CV renderer & builder
│   │   ├── provenance.py       # Auditable claim provenance tracker
│   │   └── pdf_validator.py    # Binary PDF header/EOF validator
│   ├── notifications/
│   │   └── telegram.py         # Multi-score Telegram card generator
│   ├── dispatchers/
│   │   └── gmail.py            # Idempotent SMTP worker with row locks
│   ├── observability/
│   │   └── metrics.py          # RunSummary pipeline metrics logger
│   ├── db/
│   │   └── client.py           # Supabase client & state transition manager
│   ├── pipeline.py             # Autonomous pipeline runner
│   └── config.py               # Configuration loader
├── tests/                      # 142 passing tests
├── schema.sql                  # PostgreSQL schema, enums & transition function
└── Technical_Specification.md  # Comprehensive architectural specification
```

---

## Running the Tests

To run the complete automated test suite:

```bash
py -3.14 -m pytest
```

---

## Safety & Candidate Data Integrity

1. **Candidate Profile Source of Truth:** The system will never invent or fabricate companies, dates, metrics, degrees, or skills.
2. **Pre-flight Dispatch Barrier:** `src/profiles/validator.py` ensures that real applications are locked until `profile/*.json` are updated with the candidate's genuine credentials.
3. **No Automatic Dispatch:** Every application requires human approval via Telegram before any email is sent or portal submission is confirmed.
