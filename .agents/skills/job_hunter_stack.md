# Skill: Job Hunter V1 Guardrails

## Locked Technology Stack
- **Core Runtime**: Python 3.11
- **Database / State Store**: Supabase PostgreSQL (Source of Truth)
- **Control Plane**: Telegram Bot API + Supabase Edge Functions (Deno/TypeScript)
- **AI Processing**: Google Gemini 2.5 Flash (Semantic analysis only)
- **Document Engine**: LaTeX / `pdflatex`
- **Mail Transport**: Python `smtplib` + Gmail App Password
- **Automation / Scheduler**: GitHub Actions (`cron` triggers)
- **Test Framework**: `pytest`

## Strict System Invariants
1. **State Ownership**: PostgreSQL owns state transitions. Gemini reasoning NEVER mutates application state directly.
2. **Deterministic Pre-Filtering**: Email addresses, years of experience, and German proficiency requirements MUST be extracted deterministically with Python before LLM invocation.
3. **Decoupled Control Loop**: Telegram webhook only updates `action_queue`. Asynchronous workers handle actual dispatch.
4. **CV Integrity**: The CV compiler must only select and format entries present in `profile/projects.json` and `profile/experience.json`. It is strictly forbidden from generating synthetic experience.
5. **Idempotent Dispatch**: No email is sent without verifying that the `action_queue` item is in `APPROVED_FOR_DISPATCH` state and recording an `idempotency_key`.
