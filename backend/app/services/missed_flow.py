"""Missed-class confirmation flow.

A class is recorded in the Missed dashboard ONLY when the assistant asks the
group ("did anyone miss X?") and a group member actually responds. This module:

  - ask_group_missed(db, user_id, topic, course): posts the request via the
    user's bot, tracks it as an open MissedRequest (with its Telegram msg id).
  - confirm_missed_group_reply(db, user_id, thread_id, sender, text): called on
    every incoming group message; if it replies to an open MissedRequest, build
    and store the missed-class summary (deduped per course+topic).
"""
import logging
from datetime import date as _date, datetime, timezone

from ..models import MissedRequest
from . import academic

log = logging.getLogger("classmate.missed")

_ASK_TEXT = (
    "👋 Did anyone miss **{topic}** ({course})? "
    "Reply to this message if you were absent so I can prepare a catch-up summary."
)


def ask_group_missed(db, user_id: int, topic: str, course: str = "") -> dict:
    """Post a 'did anyone miss X?' request to the group and remember it."""
    from .. import looputil, llm as llm_service
    from ..telegram.bot_manager import send_message

    course = (course or "").strip() or "General"
    settings = llm_service.get_decrypted_settings(db, user_id)
    chat = academic.resolve_group(db, user_id, fallback=settings.get("target_chat", ""))
    if not chat:
        return {"sent": False, "error": "No target group configured."}
    text = _ASK_TEXT.format(topic=topic[:200], course=course)
    try:
        msg_id = looputil.run_coro(send_message(user_id, chat, text), timeout=20.0)
    except Exception as exc:  # noqa: BLE001
        log.warning("missed-request broadcast failed user=%s: %s", user_id, exc)
        return {"sent": False, "error": str(exc)[:200]}
    if not msg_id:
        return {"sent": False, "error": "Bot could not send the message."}
    db.add(MissedRequest(
        user_id=user_id, course=course, topic=(topic or "").strip(),
        telegram_message_id=str(msg_id),
    ))
    try:
        academic.add_telegram_message(
            db, user_id, chat, text, sender_id="classmate_ai_bot",
            telegram_msg_id=str(msg_id),
        )
    except Exception:  # noqa: BLE001  traceability only
        pass
    db.commit()
    return {"sent": True, "chat": chat, "telegram_message_id": msg_id}


def confirm_missed_group_reply(db, user_id: int, thread_id, sender: str,
                               text: str) -> bool:
    """Match an incoming group message against open missed-requests.

    A reply (Telegram reply_to_msg_id) that matches an open request counts as a
    confirmation: build + store the missed-class summary for that course/topic.

    Falls back to ANY message while a request is open only when the LLM is
    unavailable (never drop a possible confirmation). Returns True when a
    missed-class summary was created/updated.
    """
    text = (text or "").strip()
    if not text:
        return False

    open_req = (
        db.query(MissedRequest)
        .filter_by(user_id=user_id)
        .filter(MissedRequest.completed_at.is_(None))
        .order_by(MissedRequest.requested_at.desc())
        .first()
    )
    if open_req is None:
        return False

    matched = False
    if thread_id:
        matched = str(thread_id) == str(open_req.telegram_message_id)
    if not matched:
        # While a request is open, treat a substantive reply as a confirmation
        # (generous capture; dedupe below prevents duplicates).
        matched = len(text) >= 6
    if not matched:
        return False

    return _record_missed_from_reply(db, user_id, open_req.topic, open_req.course,
                                     sender, text, open_req)


def _record_missed_from_reply(db, user_id: int, topic: str, course: str,
                              sender: str, text: str,
                              req: "MissedRequest | None",
                              date_str: str = "") -> bool:
    """Create (deduped) the missed-class summary for an answered request."""
    topic = (topic or "").strip()
    course = (course or "General").strip()
    try:
        from . import coverage as cov

        existing = any(
            (m.topic or "").strip().lower() == topic.lower()
            and (m.course or "").strip().lower() == course.lower()
            for m in academic.list_missed(db, user_id)
        )
        if not existing:
            if not date_str:
                date_str = _date.today().isoformat()
            basis = f"group reply · {sender or 'student'} confirmed they missed it"
            cov.build_missed_summary(
                db, user_id, course, topic, date_str, basis,
                context=text[:600], save=True,
            )
        if req is not None:
            req.completed_at = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("missed confirm failed user=%s: %s", user_id, exc)
        db.rollback()
        return False


def _dt_from(row, attr: str):
    """Return an aware datetime for a row attribute (handles naive storage)."""
    v = getattr(row, attr, None)
    if v is None:
        return None
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def confirm_ask_group_reply(db, user_id: int, thread_id, sender: str,
                            text: str) -> bool:
    """Fallback so a reply to a missed-class question posted through ANY tool
    (ask_group / post_to_telegram, which don't create a MissedRequest) still
    records the missed class.

    The assistant's outbound question is tracked in TelegramMessage. A
    substantive incoming reply while a recent missed-class ask is outstanding is
    treated as a confirmation: build + store the missed summary, and record a
    completed MissedRequest so we never double-confirm the same ask.
    """
    from ..models import TelegramMessage

    text = (text or "").strip()
    if len(text) < 6:
        return False

    ask = _recent_missed_ask(db, user_id, TelegramMessage)
    if ask is None:
        return False

    asked_at = _dt_from(ask, "created_at")
    since = datetime.now(timezone.utc) - asked_at if asked_at else None
    if since is not None and since.total_seconds() > _ASK_OPEN_HOURS * 3600:
        return False

    tid = str(getattr(ask, "telegram_msg_id", "") or "")
    if tid and thread_id:
        if str(thread_id) != tid:
            return False
    elif since is not None and since.total_seconds() < 0:
        return False

    topic = (text[:200] or "the missed class").strip()
    course = _guess_course_from_ask(db, user_id, ask.text)
    date_str = _ask_date(ask.text or "")
    ask_tid = str(getattr(ask, "telegram_msg_id", "") or "")
    if ask_tid:
        already = (
            db.query(MissedRequest)
            .filter(MissedRequest.user_id == user_id,
                    MissedRequest.telegram_message_id == ask_tid)
            .first()
        )
        if already is not None:
            return False
    req = MissedRequest(
        user_id=user_id, course=course, topic=topic,
        telegram_message_id=ask_tid,
    )
    db.add(req)
    db.flush()
    return _record_missed_from_reply(db, user_id, topic, course, sender, text,
                                     req, date_str=date_str)


_ASK_OPEN_HOURS = 48

import re as _re


def _looks_like_missed_ask(text: str) -> bool:
    """True when an outbound assistant message is asking the group about a
    missed/covered class (topic recap), whatever tool posted it."""
    t = (text or "").lower()
    tokens = [
        "did anyone miss", "who missed", "missed the class", "missed today",
        "missed this morning", "missed yesterday", "missed the lecture",
        "missed todays", "missed yesterdays",
        "what was", "what were", "what topics", "what did",
        "covered in", "was covered", "cover", "recap", "recapped",
        "class about", "lecture about", "class is about", "lecture is about",
        "today's class", "todays class", "yesterday's class", "yesterdays class",
        "this morning", "this afternoon", "earlier today",
    ]
    if any(k in t for k in tokens):
        # Require it to actually reference a class / lecture / topic session.
        if any(w in t for w in ("class", "lecture", "topic", "lesson")):
            return True
    return False


def _recent_missed_ask(db, user_id: int, TelegramMessage) -> "object | None":
    rows = (
        db.query(TelegramMessage)
        .filter(TelegramMessage.user_id == user_id,
                TelegramMessage.sender_id == "classmate_ai_bot")
        .order_by(TelegramMessage.id.desc())
        .limit(15)
        .all()
    )
    for row in rows:
        if _looks_like_missed_ask(row.text or ""):
            return row
    return None


def _guess_course_from_ask(db, user_id: int, ask_text: str) -> str:
    """Best-effort course name from the assistant's outbound question text."""
    candidates = []
    for ev in academic.list_events(db, user_id, etype="course", limit=30):
        c = (ev.course or "").strip()
        if c and c.lower() not in ("general", "announcement"):
            candidates.append(c)
    low = ask_text.lower()
    for c in candidates:
        if c.lower() in low:
            return c
    # Fallback: uppercase acronyms in the ask (e.g. "DSA", "ML") often are the
    # course code even before a course event exists.
    import re as _re

    acro = _re.findall(r"\b[A-Z][A-Z0-9]{1,5}\b", ask_text or "")
    for a in acro:
        if a.lower() in low:
            return a
    # remove "class"/"lecture" filler: "what was yesterday's DSA class about?"
    words = _re.sub(r"[^a-zA-Z0-9 ]+", " ", ask_text or "").split()
    stop = {"what", "was", "were", "the", "class", "lecture", "about", "todays",
            "yesterday", "today", "this", "morning", "afternoon", "hey", "everyone",
            "can", "someone", "share", "covered", "did", "we", "in"}
    for w in words:
        if w.lower() not in stop and len(w) > 2:
            return w[:60]
    return "General"


def _ask_date(ask_text: str) -> str:
    """Yesterday when the ask references yesterday, else today."""
    t = (ask_text or "").lower()
    if any(k in t for k in ("yesterday", "yesterdays", "last class", "previous class",
                            "last lecture", "yesterday's", "yesterdays class")):
        from datetime import timedelta

        return (_date.today() - timedelta(days=1)).isoformat()
    return _date.today().isoformat()