# ClassMateX

> **Never ask "what did we learn today?" again.**

A **Telegram-powered AI student companion** that turns messy messages from your
course groups and uploaded course documents into organized, source-traceable,
personalized academic knowledge — exposed through a clean web dashboard and an
AI assistant that behaves like a smart classmate.

**Core principle:** *Don't make the student ask a classmate what happened.
Make ClassMateX remember it.*

---

## What it does (mapped to the spec)

| Spec feature | Implementation |
|---|---|
| **A. Schedule ingestion** | Incoming messages → LLM extraction → structured `class` events (date, time, room, topic) + `schedule_change`. |
| **B. Course outline & doc ingestion** | PDF/DOCX/PPTX/TXT/OCR-screenshots parsed and embedded into per-course ChromaDB (local embeddings). Upload via web or auto-ingest docs your bot sees. |
| **C. Assignment Guardian** | Detects assignments with full requirements, deadlines, submission format; lifecycle `not_started → in_progress → submitted → completed` in the UI. |
| **D. Deadline monitor** | Background sweep -> Overdue / Due today / Due soon / Upcoming buckets + web & Telegram notifications. |
| **E. Quiz & Exam tracker** | Quizzes & exams with date/topics/scope; practice/study guidance possible via RAG. |
| **F. Assessment summarization** | Every fact keeps source = `confirmed` / `community` / `inferred` + confidence + message id. |
| **G. Missed-class assistant** | Schedule + lecture-sync poll + RAG over course material → catch-up summary with basis. Never posts if class was cancelled. |
| **H. Lecture-sync poll** | Native Telegram poll after each class, votes tallied, winner summarized from course materials. |
| **5. AI Assistant** | LangGraph master agent, retrieval-first, grounded only in the student's own data. |
| **7. Trust & grounding** | No invented facts; uncertain → the agent explicitly says so and can `ask_group`. |
| **11. Editable/adaptive agent** | One editable `master_agent.txt` prompt + per-user learned rules (see below). No prompt sprawl. |
| **Web UI** | Exactly 3–4 concise dashboards: Overview, Assistant, Assignments & Deadlines, Schedule·Quizzes·Missed. **Community matching is intentionally deferred.** |

## Everyone brings their own keys

There is **no shared/hardcoded key**. Each user:

1. Registers (`/register`)
2. Opens **Setup & Connection** and enters:
   - Telegram **bot token** (from @BotFather) — the bot does the listening & posting
   - **Groq API key** (powers the assistant + ingestion)
   - Target chat (`@group_username` or numeric ID)
   - Optional API ID / hash (only needed for user-account mode)
3. Clicks **Test both**, then **Start bot**.

Keys are **encrypted at rest** (Fernet) and masked in the UI.

## Adaptive behavior (teach your classmate)

In **Settings → Teach the agent**, tell it things like:
- *"Alice is actually the lecturer"*
- *"Don't trust announcements from Bob"*
- *"When I say ML, I mean Machine Learning"*
- *"Always show me deadlines first"*

These become **per-user scoped rules** injected into the master prompt — they
never modify the global prompt file.

## Architecture

```
React + Tailwind (frontend)          Telegram group (Telethon bot per user)
        │  HTTP / WebSockets                     │
        └───────────────┬────────────────────────┘
                        ▼
                 FastAPI backend
                  (JWT auth, per-user encrypted settings, SQLite)
                        │
                        ▼
            LangGraph MASTER AGENT (Groq LLM)
        intent router · tools · user memory
              │                │
              ▼                ▼
        RAG (ChromaDB)   Academic services
        local embeddings (assignments, schedule, quizzes,
        per-course stores   deadlines, polls, missed, progress)
                        │
                  Notifications (web + Telegram)
```

## Project layout

```
backend/app/
  main.py                  FastAPI app + scheduler startup
  config.py / database.py  env config, SQLAlchemy
  models.py / schemas.py   ORM + Pydantic
  security.py              JWT + password + Fernet encryption
  llm.py                   per-user Groq access (own key)
  prompt_loader.py         editable prompt files
  prompts/                 master_agent.txt · extraction.txt
  agent/                   LangGraph master agent + tools
  knowledge/               RAG + document readers (OCR included)
  services/                academic · memory · notifier
  telegram/                bot_manager · ingestion · polling · scheduler
  api/                     auth, settings, dashboards, assistant, ingest...
frontend/src/
  pages/                   Login Register Setup Overview Assistant Assignments Schedule Settings
  components/              Layout · Markdown
scripts/                   .bat helpers (Windows)
```

## Run it locally (Windows)

```bat
scripts\install_backend.bat       # creates backend\.venv, installs deps
scripts\install_frontend.bat      # npm install
scripts\run_backend.bat           # uvicorn on :8000
scripts\run_frontend.bat          # Vite dev server on :5173
```

1. Open http://localhost:5173 → register → **Setup & Connection** → paste your
   bot token + Groq key + target chat → **Test both** → **Start bot**.
2. Backend API + docs: http://localhost:8000/docs

No Docker required. Python 3.10+ and Node 18+ are the only prerequisites.

## Editing prompts without touching code

Edit `backend/app/prompts/master_agent.txt` (assistant behavior) or
`extraction.txt` (what ingestion extracts). Files are re-read on every call —
save, no restart.

## Security notes

- Keys encrypted at rest; masked in the UI; never returned by the API.
- Per-user data isolation on both the structured DB and the vector store.
- A hardcoded Groq key that leaked in the sample notebook is **not** used here
  — rotate it if it's still active.

## Status & roadmap

- Working: ingestion, extraction, RAG, assistant, dashboards, deadline monitor,
  lecture-sync polls, notifications, adaptive memory, document upload.
- Deferred per spec: **community / peer matching** (do later).
- OCR needs the Tesseract binary installed for screenshots; without it the app
  degrades gracefully.