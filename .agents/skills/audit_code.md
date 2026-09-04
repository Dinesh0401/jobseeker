# Skill: Independent QA Audit

## Rules of Engagement
1. **Zero Silent Fixes**: @qa must observe, reproduce, and document failures in `QA_AUDIT.md` without modifying source files during the audit pass.
2. **Hard Audit Criteria**:
   - Deterministic email extraction matches regex; no unextracted contact emails injected by LLMs.
   - Database transactions are atomic and never wrap external network/LLM requests.
   - State machine rejects invalid transitions (e.g., `INGESTED` -> `SENT`).
   - Telegram callback requires secret tokens, chat verification, and valid `action_queue` UUIDs.
   - Email dispatch executes with idempotency checks against `application_assets.idempotency_key`.
   - CV generation strictly references source keys in `profile/`; zero inferred achievements or tools.
3. **Handoff**: @engineer receives `QA_AUDIT.md`, addresses each line item, and hands back to @qa for final verification pass.
