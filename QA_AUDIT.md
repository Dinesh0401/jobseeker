# QA Audit Report — Job Hunter v1

> **Auditor**: @qa
> **Date**: 2026-09-01
> **Revision**: 2 (post-reconciliation)
> **Scope**: All files across Milestones 1–4 + Phase 5A fixes

---

## 🔧 Reconciliation Fixes Applied

| # | Issue Found | Severity | Fix Applied |
|---|-------------|----------|-------------|
| 1 | Dispatcher bypassed `transition_job_state()` — did raw `UPDATE jobs SET state` | **Critical** | [`gmail.py`](file:///c:/Users/sjdin/jobseeker/src/dispatchers/gmail.py): Now calls `SELECT transition_job_state()` for DISPATCHING and SENT |
| 2 | Webhook had no `X-Telegram-Bot-Api-Secret-Token` header verification | **High** | [`index.ts`](file:///c:/Users/sjdin/jobseeker/supabase/functions/telegram-webhook/index.ts): Added secret token check as first security layer |
| 3 | SMTP uncertain-send (timeout after send, before DONE commit) | **High** | [`gmail.py`](file:///c:/Users/sjdin/jobseeker/src/dispatchers/gmail.py): Timeout/disconnect → stays `EXECUTING`, `_recover_stale_executing()` handles after 10min |
| 4 | `BOT_TOKEN` vs `TELEGRAM_BOT_TOKEN` env var mismatch | **Medium** | [`index.ts`](file:///c:/Users/sjdin/jobseeker/supabase/functions/telegram-webhook/index.ts): Standardized to `TELEGRAM_BOT_TOKEN` |
| 5 | Webhook approve didn't transition job state | **High** | [`index.ts`](file:///c:/Users/sjdin/jobseeker/supabase/functions/telegram-webhook/index.ts): Now calls `transition_job_state` RPC with rollback on failure |
| 6 | Webhook skip didn't reject the job | **Medium** | [`index.ts`](file:///c:/Users/sjdin/jobseeker/supabase/functions/telegram-webhook/index.ts): Skip now transitions job to `REJECTED` |
| 7 | SMTP auth failure triggered infinite retries | **Medium** | [`gmail.py`](file:///c:/Users/sjdin/jobseeker/src/dispatchers/gmail.py): `SMTPAuthenticationError` → `FAILED` (no retry) |

---

## ✅ PASS — Extraction Pipeline Integrity

| Check | Status |
|-------|--------|
| Email regex excludes noreply/example domains | ✅ |
| YoE extraction is deterministic regex (4 patterns + German) | ✅ |
| German detection uses 4-tier enum with priority order | ✅ |
| LLM prompt says "DO NOT OVERRIDE" deterministic facts | ✅ |
| 45+ unit tests cover all edge cases | ✅ |

## ✅ PASS — State Machine Enforcement

| Check | Status |
|-------|--------|
| 13-state ENUM in `schema.sql` | ✅ |
| `transition_job_state()` PG function with `FOR UPDATE` row lock | ✅ |
| Python `VALID_TRANSITIONS` mirrors SQL exactly | ✅ |
| Invalid transitions raise exception (18 test cases) | ✅ |
| `FAILED → APPROVED` retry path exists | ✅ |
| **Dispatcher uses PG function (not raw UPDATE)** | ✅ Fixed |
| **Webhook uses PG function via RPC** | ✅ Fixed |

## ✅ PASS — Security Model

| Check | Status |
|-------|--------|
| No hardcoded secrets in any source file | ✅ |
| `.env` and `*.key` and `*.pem` in `.gitignore` | ✅ |
| **Webhook verifies `X-Telegram-Bot-Api-Secret-Token`** | ✅ Fixed |
| Webhook validates chat_id against whitelist | ✅ |
| RLS enabled on all 4 tables (service_role only) | ✅ |
| Webhook returns 200 on error (prevents Telegram retry storm) | ✅ |

## ✅ PASS — Dispatch Idempotency

| Check | Status |
|-------|--------|
| `FOR UPDATE SKIP LOCKED` in dispatcher SQL | ✅ |
| Rate limit: `LIMIT 5` in query | ✅ |
| SMTP definite failure → reverts to `APPROVED_FOR_DISPATCH` | ✅ |
| **SMTP timeout (uncertain-send) → stays `EXECUTING`** | ✅ Fixed |
| **Orphan recovery: `_recover_stale_executing()` after 10min** | ✅ Fixed |
| **Auth failure → `FAILED` (no infinite retry)** | ✅ Fixed |
| `idempotency_key` UUID bound at queue creation | ✅ |

## ✅ PASS — CV Generation Integrity

| Check | Status |
|-------|--------|
| Only `profile/` JSON entries used (key validation) | ✅ |
| Non-existent keys logged as WARNING and skipped | ✅ |
| Zero synthetic experience — builder only selects, never generates | ✅ |
| LaTeX special character escaping for & % $ # _ { } ~ ^ | ✅ |

## ✅ PASS — Telegram Webhook

| Check | Status |
|-------|--------|
| Webhook is queue-only (no SMTP) | ✅ |
| **Two-layer auth: secret token + chat_id** | ✅ Fixed |
| Idempotent approve (`.eq('status', 'QUEUED')`) | ✅ |
| `answerCallbackQuery` for user feedback | ✅ |
| Inline `editMessageText` for UX | ✅ |
| **Skip action transitions job to REJECTED** | ✅ Fixed |
| **Approve failure triggers rollback** | ✅ Fixed |

## ⚠️ Non-Blocking Observations

| # | Observation | Severity | Action |
|---|-------------|----------|--------|
| 1 | `src/matcher/` and `src/dispatcher/` exist alongside `src/evaluators/matcher.py` and `src/dispatchers/gmail.py` | Low | Clean up in M5 |
| 2 | `collect.yml` inline Python is long | Low | Extract to `scripts/pipeline.py` in M5 |
| 3 | No mock tests for `matcher.py` (API-dependent) | Low | Add VCR-cassette tests in M5 |
| 4 | `followup.yml` inline Python could be extracted | Low | Refactor in M5 |

---

## Verdict

**✅ ALL MILESTONES PASS QA (Rev 2).** All 7 reconciliation fixes have been applied and verified. Zero critical or high-severity issues remain. The 4 low-severity observations are tracked for M5.
