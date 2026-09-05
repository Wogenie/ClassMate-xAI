"""Telegram ingestion pipeline.

New messages flow into a per-thread context window, are classified by the
extraction analyst (LLM), and any detected facts are persisted as structured
academic events (assignments, quizzes, schedule, deadlines...). Documents and
screenshots are read and embedded into the user's course RAG store.
"""
import json
import logging
import tempfile
from datetime import date, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config, llm as llm_service, prompt_loader
from ..knowledge import documents, rag
from ..models import SourcePool
from ..services import academic, notifier

log = logging.getLogger("classmate.ingestion")

MAX_CONTEXT = 10


def _thread_key(chat_id, thread_id) -> str:
    return f"{chat_id}::{thread_id or ''}"


def _bucket_for(message_text: str) -> str:
    """Classify a raw message into assignment / exam / other so the unified
    inbox can group them. Heuristic on the text (no LLM needed at store time)."""
    import re as _re

    low = (message_text or "").lower()
    assignment_words = ["assignment", "assigment", "homework", "hw ",
                        "assignment on", "submit", "due on", "due by", "deadline", "project"]
    exam_words = ["exam", "mid", "midterm", "final", "quiz", "test",
                  "assessment", "test on", "cat ", "continuous assessment"]
    if any(w in low for w in exam_words):
        return "exam"
    if any(w in low for w in assignment_words):
        return "assignment"
    return "other"


def _sender_label(name: str, username: str) -> str:
    """Render a sender nicely as 'Abuga(@WogenieL)' for the inbox."""
    name = (name or "").strip()
    user = (username or "").strip()
    if name and user:
        if name == user:
            return f"@{user}"
        return f"{name}(@{user})"
    if user:
        return f"@{user}"
    return name or "unknown sender"


def _push_context(db: Session, user_id: int, chat_id, thread_id, msg_id,
                  sender_name: str, text: str, media_type: str,
                  sender_username: str = "") -> None:
    row = SourcePool(
        user_id=user_id,
        thread_key=_thread_key(chat_id, thread_id),
        telegram_msg_id=msg_id,
        sender_name=sender_name,
        sender_username=sender_username or "",
        text=text or "",
        media_type=media_type,
        bucket=_bucket_for(text),
    )
    db.add(row)
    db.commit()


def _recent_context(db: Session, user_id: int, chat_id, thread_id) -> list[str]:
    rows = (
        db.query(SourcePool)
        .filter_by(user_id=user_id, thread_key=_thread_key(chat_id, thread_id))
        .order_by(SourcePool.id.desc())
        .limit(MAX_CONTEXT)
        .all()
    )
    return [
        f"[{r.sender_name}: {r.text[:300]}]" + (" 📎" if r.media_type else "")
        for r in reversed(rows)
    ]


def classify(db: Session, user_id: int, message_text: str, sender_name: str,
             thread_key: str, context: list[str]) -> dict:
    """Run the extraction analyst over a message with its context window.

    When no LLM is configured, or the LLM call fails (e.g. the Groq free-tier
    daily token limit), fall back to a lightweight rule-based extractor so
    obvious exam/quiz/assignment/class/deadline messages are STILL captured in
    the dashboard instead of being silently dropped."""
    llm = llm_service.get_llm(db, user_id)
    if llm is None:
        h = _heuristic_extract(message_text)
        return h if h["facts"] else {**h, "reason": "no LLM configured"}

    known_courses = "\n".join(_known_courses(db, user_id)) or "(none known yet)"
    sys = prompt_loader.load_prompt("extraction.txt").format(
        today=date.today().isoformat(),
        sender_name=sender_name,
        thread_key=thread_key,
        message_text=message_text,
        history="\n".join(context) if context else "(none)",
        known_courses=known_courses,
    )
    from langchain_core.messages import HumanMessage, SystemMessage

    try:
        res = llm.invoke([SystemMessage(content=sys)])
        raw = res.content.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        payload = json.loads(raw[raw.index("{"):])
        return payload
    except Exception as exc:  # noqa: BLE001
        log.warning("Extraction failed for user %s: %s", user_id, exc)
        h = _heuristic_extract(message_text)
        return h if h["facts"] else {**h, "reason": f"extraction error: {exc}"}


def _heuristic_extract(message_text: str) -> dict:
    """Zero-LLM fallback extractor for obvious event messages. Captures a basic
    exam/quiz/assignment/class fact with a course guess and any mention of a
    date/deadline. Only fires when the text clearly looks like such an event."""
    import re as _re

    t = (message_text or "").strip()
    fact: dict = {}
    low = t.lower()

    type_words = {
        "exam": ["exam", "mid", "final", "test", "test on", "assessment"],
        "quiz": ["quiz", "quizzes"],
        "assignment": ["assignment", "assigment", "homework", "hw", "project",
                       "assignment on", "submit", "due on", "due by", "deadline"],
        "class": ["class", "lecture", "lesson", "cancel", "cancelled"],
    }
    for etype, words in type_words.items():
        if any(w in low for w in words):
            fact["type"] = etype
            break
    if "type" not in fact:
        return {"facts": [], "should_ask_group": False, "ask_question": ""}

    fact["title"] = t[:180]

    # course guess: take the first capitalized token sequence before "exam/quiz/... on"
    m = _re.search(r"(?i)([a-zA-Z][a-zA-Z ]{1,30}?)(?=\s+(?:mid|final|exam|quiz|test|assignment|class)\b)", t)
    if m:
        fact["course"] = m.group(1).strip()
    if not fact.get("course"):
        fact["course"] = ""
    fact["confidence"] = "low"
    fact["source"] = "confirmed"
    return {"facts": [fact], "should_ask_group": False, "ask_question": ""}


def _known_courses(db: Session, user_id: int) -> list[str]:
    """Collect every course name the user has ever referenced, so the extraction
    analyst can attribute an incoming message to a specific course (DSA, Physics,
    ...) instead of defaulting to 'General'. Sources: every `course` value seen on
    academic events plus course-outline names and course-code preferences."""
    from ..models import AcademicEvent, UserPreference

    names: set[str] = set()

    rows = (
        db.query(AcademicEvent.course)
        .filter(AcademicEvent.user_id == user_id)
        .distinct()
        .all()
    )
    for (c,) in rows:
        c = (c or "").strip()
        if c and c.lower() not in ("general", "announcement"):
            names.add(c)

    rows = (
        db.query(AcademicEvent.title)
        .filter(AcademicEvent.user_id == user_id, AcademicEvent.type == "course")
        .all()
    )
    for (t,) in rows:
        t = (t or "").strip()
        if t and t.lower() not in ("general", "announcement"):
            names.add(t)

    prefs = (
        db.query(UserPreference.value)
        .filter(UserPreference.user_id == user_id)
        .all()
    )
    import re as _re
    for (v,) in prefs:
        v = (v or "").strip()
        for tok in _re.findall(r"\b[A-Z]{2,}\b", v):
            names.add(tok)

    return sorted(names)


def _auto_solve_in_background(user_id: int, event_id: int, etype: str) -> None:
    """Trigger the LLM pipeline off the request path (per-student, own LLM).

    Assignments -> run the Assignment Understanding Agent, then (only if
    sufficiently understood) generate + store a solution & summary.
    Quizzes/exams -> generate + store a study guide.
    Only runs when the user has their own Groq key (agent handles that).
    """
    def _run():
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            if etype == "assignment":
                agent.solve_assignment(db, user_id, event_id)
            elif etype in ("quiz", "exam"):
                agent.generate_study_guide(db, user_id, event_id)
        finally:
            db.close()

    try:
        import threading

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("auto-solve scheduling failed user=%s: %s", user_id, exc)


def _auto_analyze_assignment_in_background(user_id: int, event_id: int) -> None:
    """Run the Assignment Understanding Agent first; only then (if the solver
    gate allows) generate the solution. Keeps 'solve when sufficiently
    understood' per the assignment spec."""
    from ..services import assignment_agent

    def _run():
        from .. import llm as llm_service
        from ..database import SessionLocal
        from ..models import AcademicEvent

        db = SessionLocal()
        try:
            llm_service.get_or_create_settings(db, user_id)
            row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
            if row is None or row.type != "assignment":
                return
            understanding = assignment_agent.analyze_assignment(db, user_id, row)
            ok, reason = assignment_agent.should_solve(understanding)
            details = row.details or {}
            if ok:
                details["solve_blocked_reason"] = ""
                row.details = details
                db.commit()
                agent.solve_assignment(db, user_id, event_id)
            else:
                details["solve_blocked_reason"] = reason
                row.details = details
                db.commit()
        except Exception as exc:  # noqa: BLE001
            log.warning("assignment auto-analysis failed user=%s: %s", user_id, exc)
            from ..database import SessionLocal as _S
            try:
                db2 = _S()
                row = db2.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
                if row is not None:
                    row.details = {**(row.details or {}), "solve_blocked_reason": str(exc)[:300]}
                    db2.commit()
                db2.close()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()

    try:
        import threading

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("auto-analysis scheduling failed user=%s: %s", user_id, exc)


def _detect_coverage_in_background(user_id: int, event_id: int,
                                   message_text: str, context: list[str]) -> None:
    """Run Dynamic Quiz Coverage Detection off the request path.

    Classifies EXPLICIT / INFERRED / AMBIGUOUS coverage for a stored quiz/exam,
    extracting topics grounded in source-aware RAG. Never raises.
    """
    from ..services import coverage as cov

    def _run():
        from .. import llm as llm_service
        from ..database import SessionLocal
        from ..models import AcademicEvent

        db = SessionLocal()
        try:
            llm_service.get_or_create_settings(db, user_id)
            row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
            if row is None or row.type not in ("quiz", "exam"):
                return
            state = cov.detect_coverage(db, user_id, row, message_text, context)
            payload = {
                "coverage_status": state["coverage_status"],
                "coverage": state["coverage"],
                "topics": state["topics"],
                "coverage_evidence": state["evidence"],
                "requires_clarification": state["requires_clarification"],
                "coverage_chapter": (state["course"] or ""),
            }
            if payload["coverage_status"]:
                cov.save_coverage(db, row, payload)
            if state["requires_clarification"]:
                cov.build_clarification(db, user_id, row, message_text)
                cov.ask_group_in_background(db, user_id, event_id, message_text)
            # Auto-build the outline-grounded PORTION SUMMARY once coverage is
            # known (the announcement may only name the chapters/topics, so the
            # summarizer fuses it with the embedded course outline + docs).
            d = row.details or {}
            if payload.get("coverage_status") and not d.get("portion_summary"):
                cov.generate_portion_summary(db, user_id, row)
        except Exception as exc:  # noqa: BLE001
            log.warning("coverage detection failed user=%s: %s", user_id, exc)
        finally:
            db.close()

    try:
        import threading

        t = threading.Thread(target=_run, daemon=True)
        t.start()
    except Exception as exc:  # noqa: BLE001
        log.warning("coverage scheduling failed user=%s: %s", user_id, exc)


def persist_facts(db: Session, user_id: int, payload: dict,
                  source_data: dict, text: str = "", context: list[str] | None = None) -> list[dict]:
    persisted = []
    for fact in payload.get("facts", []) or []:
        if not isinstance(fact, dict):
            continue
        row = academic.upsert_event(db, user_id, fact, source_data)
        entry = {
            "id": row.id,
            "type": row.type,
            "course": row.course,
            "title": row.title,
            "deadline": row.deadline,
            "event_date": row.event_date,
            "confidence": row.confidence,
            "source": row.source,
        }
        # The injected announcement becomes the summary IMMEDIATELY (sync, no
        # LLM). The understanding agent then overwrites it with the detailed
        # summary in the background once a file/answer improves it further.
        if row.type == "assignment":
            details = row.details or {}
            already_full = ((details.get("analysis_source") or {}).get("status") == "full")
            if not already_full:
                from ..services import assignment_agent
                assignment_agent.instant_summary(db, user_id, row)
                _auto_analyze_assignment_in_background(user_id, row.id)
        elif row.type in ("quiz", "exam"):
            details = row.details or {}
            already = bool(details.get("solution")) or bool(details.get("study_guide"))
            if not already:
                _auto_solve_in_background(user_id, row.id, row.type)
            # Dynamic Quiz Coverage Detection (EXPLICIT / INFERRED / AMBIGUOUS).
            _detect_coverage_in_background(user_id, row.id, text, context)
        elif row.type in ("lecture_topic", "class"):
            # A class the group mentions as covered is NOT automatically added to
            # the missed-class dashboard. Missed classes are recorded only when the
            # assistant asks the group and someone confirms they missed it.
            pass
        persisted.append(entry)
    return persisted


def process_message(db: Session, user_id: int, chat_id, thread_id, msg_id,
                    sender_name: str, text: str, media_path: str = "",
                    media_type: str = "", is_lecturer: bool = False,
                    raw_event: object = None, sender_username: str = "") -> dict:
    """Full pipeline for one incoming message. Returns a result dict."""
    text = (text or "").strip()
    settings = llm_service.get_decrypted_settings(db, user_id)

    # 1. context window (retains every message for the unified inbox)
    _push_context(db, user_id, chat_id, thread_id, msg_id, sender_name, text,
                  media_type, sender_username=sender_username)
    context = _recent_context(db, user_id, chat_id, thread_id)

    # 2. document / screenshot ingestion into the course RAG store
    doc_text = ""
    if media_path and media_type in ("document", "photo"):
        doc_text = _safe_read_media(db, user_id, settings, media_path, media_type, text)
        if doc_text:
            course = _guess_course(db, user_id, thread_id)
            rag.ingest_document_text(user_id, course, doc_text, filename=Path(media_path).name, source="telegram")

    combined = "\n\n".join(x for x in [text, doc_text] if x).strip()[:6000]

    # 3. classify
    payload = classify(
        db, user_id, combined or "(document attached)", sender_name,
        _thread_key(chat_id, thread_id), context,
    )
    source_data = {
        "message_id": msg_id,
        "chat_id": chat_id,
        "thread_id": thread_id,
        "sender": _sender_label(sender_name, sender_username),
        "sender_username": sender_username or "",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "raw_text": text,
        "is_lecturer": is_lecturer,
    }

    # 4. persist facts
    persisted = persist_facts(db, user_id, payload, source_data, text=combined or text, context=context)

    # 4b. if any assignment is waiting for group answers to 'Ask details',
    #     judge this message: genuine answer -> update the assignment dashboard.
    try:
        from ..services import assignment_agent
        assignment_agent.handle_group_message(
            db, user_id, sender_name, combined or text,
            thread_id=str(thread_id or ""),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("assignment group-answer check failed user=%s: %s", user_id, exc)

    # 4c. if the assistant asked the group "did anyone miss X?" and someone
    #     replies (reply-to match / any substantive reply while open), record
    #     the missed class. Auto-sensing alone never creates a missed entry.
    try:
        from ..services import missed_flow
        missed_flow.confirm_missed_group_reply(
            db, user_id, thread_id, sender_name, combined or text,
        )
        missed_flow.confirm_ask_group_reply(
            db, user_id, thread_id, sender_name, combined or text,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("missed-confirm check failed user=%s: %s", user_id, exc)

    # 5. notify for confirmed important facts
    for p in persisted:
        if p["source"] == "confirmed" and p["type"] in ("assignment", "quiz", "exam", "deadline"):
            notifier.push(
                db, user_id, p["type"], f"{p['type'].title()}: {p['title'] or p['course']}",
                p.get("deadline") or p.get("event_date") or "Check the dashboard for details.",
                related_id=p["id"], tg_send=False,
            )

    # 6. Ask the group ONLY through the deliberate 'Ask details' flow
    #     (assignment_agent.ask_group_details). The old automatic
    #     "Clarification needed" echo re-posted content back into the group,
    #     which students perceived as noise — so it is disabled here.
    asked = False

    return {
        "classified": bool(persisted),
        "facts": persisted,
        "should_ask_group": asked,
        "reason": payload.get("reason", ""),
    }


def _safe_read_media(db, user_id, settings, media_path, media_type, caption) -> str:
    try:
        if media_type in ("document", "photo") and Path(media_path).exists():
            return documents.read_file(media_path)
    except Exception as exc:  # noqa: BLE001
        log.warning("Media read failed user=%s: %s", user_id, exc)
    return ""


def _guess_course(db: Session, user_id: int, thread_id) -> str:
    prefix = str(thread_id or "").strip()
    if prefix.isdigit():
        return f"Thread {prefix}"
    return "General"


# ----------------------------------------------------------------- telegram glue

async def telegram_event_handler(user_id: int, event) -> None:
    """Bound to the user's Telethon NewMessage handler."""
    from ..database import SessionLocal

    # Never ingest the bot's OWN outgoing messages (polls, clarification
    # questions, missed-class asks, replies the assistant posts). Otherwise the
    # assistant's own posts would be re-classified as new facts/assignments.
    if getattr(event, "out", False) or getattr(getattr(event, "message", None), "out", False):
        return

    message = event.message
    chat_id = event.chat_id
    thread_id = getattr(message, "reply_to_msg_id", None)
    sender = await event.get_sender()
    sender_name = ""
    sender_username = ""
    if sender is not None:
        first = getattr(sender, "first_name", "") or ""
        last = getattr(sender, "last_name", "") or ""
        display = (first + (" " + last if last else "")).strip()
        sender_username = getattr(sender, "username", "") or ""
        sender_name = display or sender_username or str(getattr(sender, "id", ""))

    text = (message.text or message.message or "").strip()
    media_type = "none"
    media_path = ""
    if message.media:
        if hasattr(message.media, "photo") and message.media.photo:
            media_type = "photo"
        elif hasattr(message.media, "document") and message.media.document:
            media_type = "document"
        if media_type != "none":
            try:
                tmp = tempfile.mkdtemp(prefix="classmate_media_")
                media_path = await message.download_media(file=tmp)
            except Exception as exc:  # noqa: BLE001
                log.warning("Media download failed user=%s: %s", user_id, exc)
                media_path = ""

    db = SessionLocal()
    try:
        result = process_message(
            db, user_id, chat_id, thread_id, message.id, sender_name, text,
            media_path=media_path, media_type=media_type,
            is_lecturer=bool(getattr(sender, "bot", False)),
            sender_username=sender_username,
        )
        log.info("Ingestion user=%s chat=%s -> %s", user_id, chat_id,
                 f"{len(result['facts'])} facts" if result["facts"] else "no fact")
    finally:
        db.close()


# ----------------------------------------------------------------- simulate (dev helper)

def simulate_message(db: Session, user_id: int, text: str, sender_name: str,
                     thread_id: str = "", group_id: str = "",
                     sender_username: str = "") -> dict:
    """Feed a message through the pipeline without a real Telegram group.
    Used by the web UI to demo ingestion instantly.
    """
    return process_message(
        db, user_id, group_id or "sim", thread_id, 0, sender_name, text,
        media_type="none", sender_username=sender_username,
    )