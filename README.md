# Job Hunter v1

> An autonomous job-seeking pipeline powered by Python, Supabase, Telegram, and Google Gemini.

## Overview

Job Hunter automates the entire job-application lifecycle:

1. **Collect** — Scrape job listings from configured sources
2. **Extract** — Deterministically pull emails, YoE, and language requirements via regex
3. **Match** — Semantic analysis with Gemini 2.5 Flash to score fit against your profile
4. **Present** — Surface matched jobs via Telegram bot with approve/reject buttons
5. **Dispatch** — Generate a tailored LaTeX CV, compose a cover letter, and send via SMTP

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  Collectors   │────▶│  Supabase (PG)   │◀────│  Telegram    │
│  (GH Actions) │     │  State Machine   │     │  Webhook     │
└──────────────┘     └───────┬──────────┘     └──────────────┘
                             │
                    ┌────────┴────────┐
                    │                 │
              ┌─────▼─────┐   ┌──────▼──────┐
              │  Gemini    │   │  CV Builder  │
              │  Matcher   │   │  (LaTeX)     │
              └───────────┘   └──────┬──────┘
                                     │
                              ┌──────▼──────┐
                              │  Dispatcher  │
                              │  (SMTP)      │
                              └─────────────┘
```

## Tech Stack

| Layer            | Technology                          |
|------------------|-------------------------------------|
| Core Runtime     | Python 3.11                         |
| Database         | Supabase PostgreSQL                 |
| Control Plane    | Telegram Bot API + Supabase Edge Fn |
| AI Processing    | Google Gemini 2.5 Flash             |
| Document Engine  | LaTeX / `pdflatex`                  |
| Mail Transport   | `smtplib` + Gmail App Password      |
| Scheduler        | GitHub Actions (cron)               |
| Tests            | `pytest`                            |

## Project Structure

```
jobseeker/
├── .agents/                    # AI agent configuration
│   ├── agents.md               # Team personas
│   └── skills/                 # Progressive disclosure skills
│       ├── spec_driven.md
│       ├── audit_code.md
│       └── job_hunter_stack.md
├── src/
│   ├── db/
│   │   └── client.py           # Database client & state machine
│   ├── evaluators/
│   │   └── extraction.py       # Deterministic regex extraction
│   ├── matcher/
│   │   └── gemini.py           # Gemini semantic matcher
│   ├── cv/
│   │   └── builder.py          # LaTeX CV compiler
│   ├── dispatcher/
│   │   └── mailer.py           # SMTP dispatcher
│   └── collectors/
│       └── scraper.py          # Job listing collectors
├── supabase/
│   └── functions/
│       └── telegram-webhook/   # Edge function
├── profile/
│   ├── projects.json           # Source-of-truth projects
│   └── experience.json         # Source-of-truth experience
├── .github/
│   └── workflows/              # GitHub Actions
├── schema.sql                  # Database schema
├── requirements.txt
├── pytest.ini
└── README.md
```

## Milestones

- [x] **M1**: Agent configuration + Technical Specification
- [x] **M2**: Schema + DB client + Regex extractor + Unit tests
- [x] **M3**: Telegram webhook + Callback verification
- [x] **M4**: Collectors + Matcher + CV builder + Dispatcher + Workflows
- [x] **QA**: Independent audit — all milestones pass ([QA_AUDIT.md](QA_AUDIT.md))

## License

MIT
