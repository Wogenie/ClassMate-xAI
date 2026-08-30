"""Lecture-Sync Polls (spec §H): deploy a native Telegram poll after a class
(or on demand via the agent), tally votes, pick the winning topic, and generate
a missed-class summary from the course RAG store. Summary includes confidence +
source basis.

Voting behavior: a poll finalizes as soon as `config.POLL_MIN_VOTES` students
answer — the option with the MOST votes wins and its topic is summarized. The
fixed `POLL_VOTE_WINDOW_SECONDS` is only the safety fallback for low-traffic
groups. The summary lands in the app as a MissedSummary + in-app notification.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone

from telethon import types
from telethon.tl.types import InputMediaPoll, Poll, PollAnswer

from .. import config, llm as llm_service
from ..knowledge import rag
from ..models import AcademicEvent, PollResult
from ..services import academic, notifier
from . import bot_manager

log = logging.getLogger("classmate.polls")

GENERIC_OPTIONS = [
    "New topic (lecture slides)",
    "Problem solving / exercises",
    "Semester project work",
    "Mid-term / exam review",
    "Class was cancelled",
    "Other",
]


def _options_for_course(db, user_id: int, course: str):
    topics = academic.list_events(db, user_id, etype="lecture_topic")
    topics = [t for t in topics if t.course.lower() == course.lower()][:8]
    names = []
    for t in topics:
        name = (t.topic or t.title or "").strip()
        if name and name not in names:
            names.append(name)
    names = names or list(GENERIC_OPTIONS)
    return names[:10]


async def _post_poll(db, user_id: int, course: str, question: str,
                     options: list[str], thread_id: str = "") -> PollResult | None:
    """Send a native Telegram poll to the school group and persist a
    PollResult row. Returns the row, or None when it cannot be posted."""
    settings = llm_service.get_decrypted_settings(db, user_id)
    chat = academic.resolve_group(db, user_id, fallback=settings.get("target_chat", ""))
    client = await bot_manager.get_client(user_id)
    if not chat or not client or not client.is_connected():
        return None

    options = [str(o).strip() for o in (options or []) if str(o).strip()][:8]
    if len(options) < 2:
        return None

    try:
        msg = await client.send_message(
            chat,
            file=InputMediaPoll(
                poll=Poll(
                    id=0,
                    question=question,
                    answers=[
                        PollAnswer(text=opt, option=bytes([i]))
                        for i, opt in enumerate(options)
                    ],
                    closed=False,
                    public_voters=False,
                )
            ),
            reply_to=thread_id if str(thread_id).strip() else None,
        )
        row = PollResult(
            user_id=user_id,
            course=course,
            thread_id=str(thread_id or ""),
            question=question,
            polling_message_id=msg.id,
            options=options,
            votes={},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        log.info("Poll deployed user=%s course=%s msg=%s", user_id, course, msg.id)
        return row
    except Exception as exc:  # noqa: BLE001
        log.warning("Poll deploy failed user=%s: %s", user_id, exc)
        return None


# ------------------------------------------------------------- deployment

async def deploy_poll_for_class(db, user_id: int, event: AcademicEvent) -> bool:
    """Post-class lecture-sync poll for a class event (scheduler path)."""
    options = _options_for_course(db, user_id, event.course)
    thread_id = (event.source_data or {}).get("thread_id") if event.source_data else None
    row = await _post_poll(
        db, user_id, event.course,
        f"📚 {event.course} — what did the class cover today?",
        options, thread_id=thread_id,
    )
    if row is None:
        return False
    asyncio.create_task(_tally_later(user_id, event.id, row.id,
                                     config.POLL_VOTE_WINDOW_SECONDS))
    return True


async def deploy_poll_for_group(db, user_id: int, course: str, question: str,
                                options: list[str], thread_id: str = "") -> int | None:
    """Agent-facing: post an on-demand poll to the school group. No class event
    is attached (nothing gets marked 'polled'). Returns the PollResult id."""
    row = await _post_poll(db, user_id, course, question, options, thread_id=thread_id)
    if row is None:
        return None
    asyncio.create_task(_tally_later(user_id, None, row.id,
                                     config.POLL_VOTE_WINDOW_SECONDS))
    return row.id


async def deploy_coverage_poll(db, user_id: int, event: AcademicEvent,
                               question: str, options: list[str],
                               thread_id: str = "") -> int | None:
    """Post a clarification POLL for an AMBIGUOUS quiz/exam. On finalize, the
    majority option resolves the coverage (INFERRED) and generates a portion
    summary grounded in outline + docs. Returns the PollResult id."""
    if not thread_id and event.source_data:
        thread_id = event.source_data.get("thread_id") or ""
    row = await _post_poll(db, user_id, event.course, question, options,
                           thread_id=thread_id)
    if row is None:
        return None
    row.related_event_id = event.id
    db.commit()
    asyncio.create_task(_tally_later(user_id, None, row.id,
                                     config.POLL_VOTE_WINDOW_SECONDS))
    return row.id


# ------------------------------------------------------------- tallying

async def _tally_later(user_id: int, event_id: int | None, poll_id: int,
                       window_seconds: int) -> None:
    """Give voters a short grace period, then start the poll-watching loop."""
    await asyncio.sleep(config.POLL_TALLY_INTERVAL_SECONDS)
    from ..database import SessionLocal

    db = SessionLocal()
    try:
        await tally_poll(db, user_id, event_id, poll_id, window_seconds=window_seconds)
    finally:
        db.close()


async def _fetch_poll_votes(client, row: PollResult) -> dict | None:
    """Read current Telegram poll vote counts. Returns {option: votes}."""
    try:
        msg = await client.get_messages(row.thread_id or None, ids=row.polling_message_id)
        results = msg.media.poll.results.results
        votes = {}
        for r in results:
            idx = int.from_bytes(r.option, byteorder="big")
            votes[row.options[idx] if idx < len(row.options) else str(idx)] = r.voters
        return votes
    except Exception as exc:  # noqa: BLE001
        log.warning("Poll vote fetch failed user=%s poll=%s: %s", row.user_id, row.id, exc)
        return None


def _majority_winner(row: PollResult) -> str:
    """The option with the largest number of votes. Empty when nobody voted."""
    votes = row.votes or {}
    if not votes:
        return ""
    return max(votes.items(), key=lambda kv: (kv[1],))[0]


async def tally_poll(db, user_id: int, event_id: int | None, poll_id: int,
                     window_seconds: int | None = None,
                     min_votes: int | None = None) -> None:
    """Watch a poll until `min_votes` students answer (majority wins) or the
    vote window elapses, then summarize the winning topic and deliver it in-app."""
    client = await bot_manager.get_client(user_id)
    row = db.query(PollResult).filter_by(id=poll_id, user_id=user_id).first()
    if row is None or client is None:
        return
    if row.summary_generated:
        return

    min_votes = min_votes if min_votes is not None else config.POLL_MIN_VOTES
    window_seconds = window_seconds if window_seconds is not None else config.POLL_VOTE_WINDOW_SECONDS
    interval = config.POLL_TALLY_INTERVAL_SECONDS
    start = time.monotonic()

    while True:
        fetched = await _fetch_poll_votes(client, row)
        if fetched is not None:
            row.votes = fetched
            db.commit()
        total = sum(row.votes.values()) if row.votes else 0
        elapsed = time.monotonic() - start
        if total >= min_votes or elapsed >= window_seconds:
            break
        await asyncio.sleep(interval)

    winner = _majority_winner(row)
    db.refresh(row)
    row.winning_topic = winner
    db.commit()
    total_votes = sum(row.votes.values()) if row.votes else 0
    log.info("Tally user=%s poll=%s votes=%s winner='%s'",
             user_id, poll_id, total_votes, winner)

    event = None
    if event_id:
        event = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()

    if not winner:
        if event is not None:
            academic.mark_polled(db, user_id, event_id)
        return

    basis = f"lecture-sync poll · {total_votes} vote(s) · majority “{winner}”"

    # Coverage polls resolve an ambiguous quiz/exam portion (INFERRED) and build
    # a portion summary instead of a missed-class summary.
    if row.related_event_id:
        await _finalize_coverage_poll(db, user_id, row, winner, total_votes)
        return

    # Never fabricate a summary when the class was cancelled.
    if winner.strip().lower().startswith("class was cancelled"):
        log.info("Class cancelled user=%s course=%s — skipped summary", user_id, row.course)
        if event is not None:
            academic.mark_polled(db, user_id, event_id)
        notifier.push(
            db, user_id, "missed", f"📭 {row.course} — class was cancelled",
            "No summary needed — the class didn't take place.",
        )
        return

    date_str = (event.event_date if event and event.event_date
                else datetime.now(timezone.utc).date().isoformat())
    summary, cross_check = await _summarize(db, user_id, row.course, winner, basis)
    academic.save_missed_summary(
        db, user_id, row.course, date_str, winner, summary, basis,
        cross_check=cross_check,
    )
    row.summary_generated = True
    db.commit()
    if event is not None:
        academic.mark_polled(db, user_id, event_id)
    notifier.push(
        db, user_id, "missed", f"📋 {row.course} — {winner}",
        f"Today's lecture summary is ready ({basis}).",
    )


async def _finalize_coverage_poll(db, user_id: int, row: PollResult,
                                  winner: str, total_votes: int) -> None:
    """Coverage poll won — resolve the quiz/exam's portion from the majority,
    generate a portion summary, and notify the student in-app + Telegram."""
    from ..services import coverage as cov

    event = db.query(AcademicEvent).filter_by(id=row.related_event_id, user_id=user_id).first()
    if event is None:
        return
    if winner:
        cov.finalize_from_poll(db, user_id, event, winner, total_votes)
    row.summary_generated = True
    db.commit()
    notifier.push(
        db, user_id, "quiz", f"📌 {event.course} — portion confirmed",
        f"Students voted “{winner}” ({total_votes} vote(s)). Portion marked INFERRED "
        f"(student consensus) with a summary in the dashboard.",
        related_id=event.id,
    )


async def _summarize(db, user_id: int, course: str, topic: str, basis: str) -> tuple[str, dict]:
    """Build the missed-class summary through the shared core (cross-check the
    reported topic against the attached course outline, then write the detailed
    summary). Returns (summary, cross_check); the caller persists the row."""
    from ..services import coverage as cov

    return cov.build_missed_summary(db, user_id, course, topic, "", basis, save=False)