"""Academic data: assignments, deadlines, quizzes, schedule, announcements,
missed classes, progress. All events are stored per-user with source + trust.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from ..models import AcademicEvent, MissedSummary, Notification, PollResult, SourcePool

STATUSES = {"not_started", "in_progress", "submitted", "completed"}
ATTR_BY_TYPE = {
    "assignment": "deadline",
    "quiz": "event_date",
    "exam": "event_date",
    "class": "event_date",
    "deadline": "deadline",
    "announcement": None,
    "lecture_topic": None,
    "course": None,
    "schedule_change": "event_date",
}


def upsert_event(
    db: Session,
    user_id: int,
    event: dict,
    source_data: dict,
    prefer_status_keep: bool = True,
) -> AcademicEvent:
    """Insert or merge an extracted fact. Confidence-aware dedup."""
    etype = event.get("type", "announcement")
    course = (event.get("course") or "").strip() or "General"
    title = (event.get("title") or "").strip()

    match_key = None
    if etype == "assignment" and event.get("deadline"):
        match_key = EventLookup(etype, course, event.get("deadline"))
    elif etype in ("quiz", "exam", "class", "schedule_change") and event.get("event_date"):
        match_key = EventLookup(etype, course, event.get("event_date"))
    elif etype in ("announcement", "lecture_topic", "course", "deadline"):
        match_key = None  # always create, they are informative

    existing = None
    if match_key:
        existing = _find_existing(db, user_id, etype, course, match_key)
    if existing is None and etype == "assignment" and not event.get("deadline"):
        # Assignments without a deadline were never deduped (no match_key), so
        # a repeated/duplicate message created an identical second row. Fall back
        # to matching on normalized course + title to collapse exact duplicates.
        existing = _find_existing_by_title(db, user_id, etype, course, title)

    if existing is not None:
        # Upgrade trust when a confirmed source repeats/refines a fact.
        if event.get("source") == "confirmed" and existing.confidence in ("LOW", "MEDIUM"):
            existing.confidence = event.get("confidence", "MEDIUM")
        if event.get("source") == "confirmed":
            existing.source = "confirmed"
        for field in ("description", "location", "topic", "start_time", "end_time", "deadline", "event_date"):
            if event.get(field):
                setattr(existing, field, event[field])
        if event.get("details"):
            existing.details = {**(existing.details or {}), **event["details"]}
        if existing.status == "not_started" and event.get("status"):
            existing.status = event["status"]
        existing.source_data = {
            **(existing.source_data or {}),
            **{k: v for k, v in source_data.items() if v},
        }
        db.commit()
        db.refresh(existing)
        return existing

    row = AcademicEvent(
        user_id=user_id,
        type=etype,
        course=course,
        title=title,
        description=event.get("description", ""),
        details=event.get("details") or {},
        event_date=event.get("event_date", ""),
        start_time=event.get("start_time", ""),
        end_time=event.get("end_time", ""),
        location=event.get("location", ""),
        topic=event.get("topic", ""),
        deadline=event.get("deadline", ""),
        status="not_started",
        confidence=event.get("confidence", "MEDIUM"),
        source=event.get("source", "community") or "community",
        source_data={k: v for k, v in source_data.items() if v},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _find_existing(db, user_id, etype, course, match) -> AcademicEvent | None:
    try:
        if match.field == "deadline":
            return (
                db.query(AcademicEvent)
                .filter_by(user_id=user_id, type=etype, course=course, deadline=match.value)
                .order_by(AcademicEvent.id.desc())
                .first()
            )
        return (
            db.query(AcademicEvent)
            .filter_by(user_id=user_id, type=etype, course=course, event_date=match.value)
            .order_by(AcademicEvent.id.desc())
            .first()
        )
    except Exception:
        return None


class EventLookup:
    def __init__(self, etype, course, value):
        self.field = "deadline" if value and "T" in value else "event_date"
        self.value = value


def _find_existing_by_title(db, user_id, etype, course, title) -> AcademicEvent | None:
    """Case/whitespace-insensitive match on normalized course + title, used to
    collapse exact duplicate assignments that lack a deadline."""
    norm = lambda s: " ".join((s or "").lower().split())
    t = norm(title)
    c = norm(course)
    if not t:
        return None
    try:
        rows = (
            db.query(AcademicEvent)
            .filter_by(user_id=user_id, type=etype)
            .all()
        )
    except Exception:
        return None
    for r in rows:
        if norm(r.course) == c or c in norm(r.course) or norm(r.course) in c:
            if norm(r.title) == t:
                return r
    return None# ---------------------------------------------------------------- queries

def list_events(db: Session, user_id: int, etype: str | None = None,
                status: str | None = None, course: str | None = None,
                limit: int = 200) -> list[AcademicEvent]:
    q = db.query(AcademicEvent)
    if etype:
        q = q.filter(AcademicEvent.type == etype)
    if status and etype == "assignment":
        q = q.filter(AcademicEvent.status == status)
    if course:
        q = q.filter(AcademicEvent.course.ilike(f"%{course}%"))
    return (
        q.filter(AcademicEvent.user_id == user_id)
        .order_by(AcademicEvent.created_at.desc())
        .limit(limit)
        .all()
    )


def _dt(deadline: str) -> datetime | None:
    if not deadline:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d"):
        try:
            d = datetime.strptime(deadline, fmt)
            if "T" not in deadline:
                d = d.replace(hour=23, minute=59)
            return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d
        except ValueError:
            continue
    return None


def upcoming_deadline_rows(db: Session, user_id: int) -> list[AcademicEvent]:
    """Assignments + standalone deadlines, sorted by soonest deadline."""
    rows = db.query(AcademicEvent).filter(
        AcademicEvent.user_id == user_id,
        AcademicEvent.type.in_(["assignment", "deadline"]),
    ).all()
    rows = [r for r in rows if _dt(r.deadline) is not None]
    rows = [r for r in rows if r.status not in ("completed", "submitted")]
    return sorted(rows, key=lambda r: _dt(r.deadline) or datetime.max.replace(tzinfo=timezone.utc))


def deadline_buckets(db: Session, user_id: int) -> dict[str, list[dict]]:
    now = datetime.now(timezone.utc)
    buckets = {"overdue": [], "due_today": [], "due_soon": [], "upcoming": []}
    for r in upcoming_deadline_rows(db, user_id):
        dt = _dt(r.deadline)
        if dt >= now:
            delta = dt - now
            if delta.total_seconds() <= 0:
                bucket = "due_today"
            elif delta <= timedelta(days=1):
                bucket = "due_soon"
            else:
                bucket = "upcoming"
            if dt.date() == now.date():
                bucket = "due_today"
        else:
            bucket = "overdue"
        buckets[bucket].append(_serialize(r))
    return buckets


def _event_dt(r: AcademicEvent) -> datetime | None:
    """Best-effort "when is this due / when does it happen" for an event.

    Assignments & standalone deadlines use the `deadline` field; classes,
    quizzes and exams use `event_date`.
    """
    if r.type in ("assignment", "deadline"):
        return _dt(r.deadline)
    return _dt(r.event_date or r.deadline)


def purge_stale_events(db: Session, user_id: int, days: int) -> int:
    """Delete passed events that are now `days` days (or more) past their date.

    Removes classes, quizzes, exams, assignments and standalone deadlines that
    are beyond the retention window so the lists stay clean. Returns the count
    of deleted rows.
    """
    from .. import config

    types = ("class", "quiz", "exam", "assignment", "deadline")
    rows = (
        db.query(AcademicEvent)
        .filter(AcademicEvent.user_id == user_id, AcademicEvent.type.in_(types))
        .all()
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = 0
    for r in rows:
        dt = _event_dt(r)
        if dt is not None and dt < cutoff:
            db.delete(r)
            deleted += 1
    if deleted:
        db.commit()
    return deleted


def purge_old_inbox(db: Session, user_id: int, keep_days: int = 7) -> int:
    """Delete raw inbox (SourcePool) messages older than `keep_days` days.

    Keeps the unified Inbox bounded so the stored message history cannot grow
    without limit and crash the DB. Runs weekly (Sundays) via the scheduler so
    each fresh week starts on Monday with only that week's messages retained.
    Returns the count of deleted rows.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    rows = (
        db.query(SourcePool)
        .filter(
            SourcePool.user_id == user_id,
            SourcePool.timestamp < cutoff,
        )
        .all()
    )
    deleted = 0
    for r in rows:
        db.delete(r)
        deleted += 1
    if deleted:
        db.commit()
    return deleted


def _serialize(r: AcademicEvent) -> dict:
    details = r.details or {}
    return {
        "id": r.id,
        "type": r.type,
        "course": r.course,
        "title": r.title,
        "description": r.description,
        "details": details,
        "event_date": r.event_date,
        "start_time": r.start_time,
        "end_time": r.end_time,
        "location": r.location,
        "topic": r.topic,
        "deadline": r.deadline,
        "status": r.status,
        "confidence": r.confidence,
        "source": r.source,
        "polled": r.polled,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "summary": details.get("summary", ""),
        "solution": details.get("solution", ""),
        "study_guide": details.get("study_guide", ""),
        "understanding": details.get("understanding", {}),
        "analysis_source": details.get("analysis_source", {}),
        "solve_blocked_reason": details.get("solve_blocked_reason", ""),
        "coverage_status": details.get("coverage_status", ""),
        "coverage": details.get("coverage", {}),
        "topics": details.get("topics", []),
        "coverage_evidence": details.get("coverage_evidence", ""),
        "requires_clarification": details.get("requires_clarification", False),
        "clarification": details.get("clarification", {}),
        "student_responses": details.get("student_responses", []),
        "winning_portion": details.get("winning_portion", ""),
        "portion_summary": details.get("portion_summary", ""),
        "portion_summary_basis": details.get("portion_summary_basis", ""),
    }


def set_assignment_status(db: Session, user_id: int, event_id: int, status: str) -> AcademicEvent | None:
    if status not in STATUSES:
        return None
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id, type="assignment").first()
    if row:
        row.status = status
        db.commit()
        db.refresh(row)
    return row


def patch_event(db: Session, user_id: int, event_id: int, **fields) -> AcademicEvent | None:
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
    if not row:
        return None
    for k, v in fields.items():
        if v is not None and hasattr(row, k):
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


def add_notification(db: Session, user_id: int, kind: str, title: str, body: str,
                     related_id: int = 0) -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title, body=body, related_id=related_id)
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


def progress_summary(db: Session, user_id: int) -> dict:
    events = list_events(db, user_id, limit=500)
    by_type = {}
    for e in events:
        by_type.setdefault(e.type, []).append(e)
    assignments = by_type.get("assignment", [])
    quizzes = by_type.get("quiz", [])
    exams = by_type.get("exam", [])
    classes = by_type.get("class", [])
    return {
        "assignments_total": len(assignments),
        "assignments_done": sum(1 for a in assignments if a.status in ("completed", "submitted")),
        "assignments_open": sum(1 for a in assignments if a.status in ("not_started", "in_progress")),
        "quizzes": len(quizzes),
        "exams": len(exams),
        "classes": len(classes),
        "announcements": len(by_type.get("announcement", [])),
        "completed_pct": round(
            100 * sum(1 for a in assignments if a.status == "completed") / len(assignments)
        ) if assignments else 0,
        "courses": sorted({e.course for e in events}),
    }


def _mk_missed(row) -> dict:
    return {
        "id": row.id,
        "course": row.course,
        "date": row.date,
        "topic": row.topic,
        "summary": row.summary,
        "basis": row.basis,
        "cross_check": row.cross_check or {},
    }


def overview(db: Session, user_id: int) -> dict:
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    def _mk(row):
        return _serialize(row)

    classes_today = [_mk(r) for r in list_events(db, user_id, etype="class") if r.event_date == today]
    upcoming_quizzes = [
        _mk(r) for r in list_events(db, user_id, etype="quiz")
        if r.event_date and (r.event_date >= today)
    ]
    upcoming_exams = [
        _mk(r) for r in list_events(db, user_id, etype="exam")
        if r.event_date and (r.event_date >= today)
    ]
    announcements = [_mk(r) for r in list_events(db, user_id, etype="announcement")][:5]
    missed = list_missed(db, user_id)[:5]
    return {
        "today": today,
        "classes_today": classes_today,
        "deadlines": deadline_buckets(db, user_id),
        "upcoming_quizzes": upcoming_quizzes,
        "upcoming_exams": upcoming_exams,
        "announcements": announcements,
        "missed": [_mk_missed(m) for m in missed],
        "progress": progress_summary(db, user_id),
    }


# ---------------------------------------------------------------- missed

def save_missed_summary(db: Session, user_id: int, course: str, date: str,
                        topic: str, summary: str, basis: str,
                        cross_check: dict | None = None) -> MissedSummary:
    m = MissedSummary(user_id=user_id, course=course, date=date, topic=topic,
                      summary=summary, basis=basis, cross_check=cross_check or {})
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


def list_missed(db: Session, user_id: int) -> list[MissedSummary]:
    return (
        db.query(MissedSummary)
        .filter_by(user_id=user_id)
        .order_by(MissedSummary.created_at.desc())
        .limit(50)
        .all()
    )


# ---------------------------------------------------------------- poll bookkeeping

def mark_polled(db: Session, user_id: int, event_id: int) -> None:
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
    if row:
        row.polled = True
        db.commit()


# ---------------------------------------------------------------- outgoing telegram log

def resolve_group(db: Session, user_id: int, fallback: str = "") -> str:
    """Return the ACTUAL school group where the bot has been ingesting messages,
    falling back to the configured `target_chat` (or an empty string).

    The bot listens on every chat it's added to, so we derive the real group
    from the most recent ingested message rather than trusting a manually-set
    target that might point at the bot's own chat.
    """
    row = (
        db.query(SourcePool)
        .filter_by(user_id=user_id)
        .order_by(SourcePool.id.desc())
        .first()
    )
    if row and row.thread_key:
        chat_id = str(row.thread_key).split("::", 1)[0].strip()
        if chat_id and chat_id.lower() not in ("sim", "none", ""):
            return chat_id
    return fallback or ""


def add_telegram_message(db: Session, user_id: int, chat: str, text: str,
                         sender_id: str = "classmate_ai_bot",
                         telegram_msg_id: str = "") -> dict:
    """Log a message the assistant posted to a Telegram group.

    Stored so the assistant's outbound posts are visible/traceable in the app
    (feature: "post back to Telegram"). Never raises on failure.
    """
    from ..models import TelegramMessage

    row = TelegramMessage(
        user_id=user_id, chat=chat, sender_id=sender_id, text=text,
        telegram_msg_id=str(telegram_msg_id or ""),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"id": row.id, "chat": row.chat, "sender_id": row.sender_id}


def list_telegram_messages(db: Session, user_id: int, limit: int = 50) -> list:
    from ..models import TelegramMessage

    rows = (
        db.query(TelegramMessage)
        .filter_by(user_id=user_id)
        .order_by(TelegramMessage.id.desc())
        .limit(limit)
        .all()
    )
    return [
        {"id": r.id, "chat": r.chat, "sender_id": r.sender_id, "text": r.text,
         "created_at": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


def list_inbox(db: Session, user_id: int, limit: int = 300) -> dict:
    """Group every stored Telegram message into assignment / exam / other
    buckets, newest first. `other` holds any text not assignment- or exam-like,
    so every sensed message is captured somewhere."""
    rows = (
        db.query(SourcePool)
        .filter(SourcePool.user_id == user_id)
        .order_by(SourcePool.id.desc())
        .limit(limit)
        .all()
    )

    def _label(r):
        name = (r.sender_name or "").strip()
        user = (r.sender_username or "").strip()
        if name and user and name != user:
            return f"{name}(@{user})"
        if name:
            return name
        if user:
            return f"@{user}"
        return "unknown sender"

    groups = {"assignment": [], "exam": [], "other": []}
    for r in reversed(rows):
        b = (r.bucket or "other")
        if b not in groups:
            b = "other"
        groups[b].append({
            "id": r.id,
            "thread_key": r.thread_key,
            "sender": _label(r),
            "sender_name": r.sender_name or "",
            "sender_username": r.sender_username or "",
            "is_lecturer": bool(r.sender_is_lecturer),
            "text": r.text or "",
            "media_type": r.media_type or "",
            "timestamp": r.timestamp.isoformat() if r.timestamp else None,
        })
    return groups