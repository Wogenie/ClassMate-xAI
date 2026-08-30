"""Proactive background scheduler:
  1. Deadline monitor  (spec §D) — detect due-soon / due-today / overdue and notify.
  2. Post-class lecture-sync polls (spec §H).
A single periodic sweep keeps per-user logic simple and resilient.
"""
import asyncio
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .. import config
from ..models import UserSettings

log = logging.getLogger("classmate.scheduler")

_deadline_notified: set[tuple[int, int, str]] = set()


def start_scheduler():
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        sweep_all_users,
        "interval",
        minutes=config.DEADLINE_SWEEP_MINUTES,
        id="deadline_sweep",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sweep_assignment_analyses,
        "interval",
        minutes=config.ASSIGNMENT_SWEEP_MINUTES,
        id="assignment_analysis_sweep",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sweep_quiz_summaries,
        "interval",
        minutes=config.QUIZ_SWEEP_MINUTES,
        id="quiz_summary_sweep",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    return scheduler


def sweep_quiz_summaries():
    """Every few minutes, build coverage + outline-grounded summaries for
    quizzes/exams that still lack a 'portion summary' (off the request path)."""
    from ..services import coverage

    try:
        done = coverage.sweep_pending_quiz_summaries(limit=config.QUIZ_SWEEP_BATCH)
        if done:
            log.info("Summarized %s quiz/exam(s) in background sweep", done)
    except Exception as exc:  # noqa: BLE001
        log.warning("Quiz/exam summary sweep failed: %s", exc)


def sweep_assignment_analyses():
    """Every few minutes, (re)analyze assignments that still lack a summary (or
    that are stuck on the raw-announcement fallback, respecting a cooldown). Runs
    off the request path so page loads never trigger embedding/LLM work."""
    from ..services import assignment_agent

    try:
        done = assignment_agent.sweep_pending_analyses()
        if done:
            log.info("Analyzed %s assignment(s) in background sweep", done)
    except Exception as exc:  # noqa: BLE001
        log.warning("Assignment analysis sweep failed: %s", exc)


def sweep_all_users():
    from .. import config as cfg
    from ..database import SessionLocal
    from ..services import academic

    db = SessionLocal()
    try:
        users = db.query(UserSettings).filter(
            UserSettings.bot_enabled.is_(True)
        ).all()
        for settings in users:
            user_id = settings.user_id
            try:
                _check_deadlines(db, user_id)
                # Auto-remove passed events that are now N days past their date
                # (class, quiz, exam, assignment, deadline).
                purged = academic.purge_stale_events(db, user_id, cfg.EVENT_RETENTION_DAYS)
                if purged:
                    log.info("Purged %s stale event(s) for user=%s", purged, user_id)
                asyncio.create_task(_maybe_deploy_polls(db, user_id))
            except Exception as exc:  # noqa: BLE001
                log.warning("Sweep failed for user %s: %s", user_id, exc)
    finally:
        db.close()


def _check_deadlines(db, user_id: int):
    from .. import config as cfg
    from ..services import academic, notifier

    now = datetime.now(timezone.utc)
    buckets = academic.deadline_buckets(db, user_id)
    for phase, rows in buckets.items():
        for r in rows:
            key = (user_id, r["id"], phase)
            if key in _deadline_notified:
                continue
            _deadline_notified.add(key)
            deadline = r["deadline"] or "unknown"
            if phase == "overdue":
                notifier.push(db, user_id, "deadline", f"⏰ Overdue: {r['title'] or r['course']}",
                              f"This deadline was {deadline}. Take action if still possible.", r["id"])
            elif phase == "due_today":
                notifier.push(db, user_id, "deadline", f"📌 Due today: {r['title'] or r['course']}",
                              f"Deadline {deadline} — {r['course']}.", r["id"])

    # Fresh granular reminders (24h / 12h ... before the deadline) for any open
    # item that hasn't been submitted/completed yet. `deadline_buckets` already
    # excludes submitted/completed assignments, but a standalone deadline row has
    # no status, so we double-check status here as well.
    for r in academic.list_events(db, user_id, etype="assignment", limit=200):
        status = (r.status or "").lower()
        if status in ("completed", "submitted"):
            continue
        dt = academic._dt(r.deadline)
        if dt is None:
            continue
        remaining = dt - now
        if remaining.total_seconds() < 0:
            continue
        hours_left = remaining.total_seconds() / 3600.0
        for h in sorted(cfg.DEADLINE_REMINDER_HOURS, reverse=True):
            stage = f"h{h}"
            key = (user_id, r.id, stage)
            if key in _deadline_notified:
                continue
            if hours_left <= h:
                _deadline_notified.add(key)
                notifier.push(
                    db, user_id, "deadline",
                    f"⏳ {r.title or r.course} due in ~{h}h",
                    f"Deadline {r.deadline}, {hours_left:.1f}h left — submit before it expires.",
                    r.id,
                )

    # in-memory set resets on restart (acceptable for MVP)


async def _maybe_deploy_polls(db, user_id: int):
    from .. import llm as llm_service
    from ..services import academic
    from . import bot_manager, polling

    settings = llm_service.get_decrypted_settings(db, user_id)
    if not settings.get("poll_after_class"):
        return
    if not bot_manager.is_running(user_id):
        return
    if not academic.resolve_group(db, user_id, fallback=settings.get("target_chat", "")):
        return

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    classes = academic.list_events(db, user_id, etype="class")
    for event in classes:
        if event.polled or event.event_date != today:
            continue
        end_time = event.end_time or event.start_time or ""
        try:
            hh, mm = (end_time.split(":") or ["", ""])[:2]
            end_dt = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
        except Exception:
            continue
        window = now - end_dt
        if window.total_seconds() >= config.POLL_AFTER_CLASS_MINUTES * 60:
            try:
                ok = await polling.deploy_poll_for_class(db, user_id, event)
                if ok:
                    log.info("Deployed post-class poll user=%s course=%s", user_id, event.course)
            except Exception as exc:  # noqa: BLE001
                log.warning("Poll deploy failed user=%s: %s", user_id, exc)