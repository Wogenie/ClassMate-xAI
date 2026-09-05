"""SQLAlchemy models for Classmate xAI."""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship

from .database import Base


def _now():
    return datetime.now(timezone.utc)


# Mutable JSON column types: in-place edits to the loaded dict/list are tracked
# by SQLAlchemy. Without this, code like `d = row.details or {}; d['x'] = 1;
# row.details = d` silently fails to persist when d is the object already on
# the instance (history sees the identical object as 'unchanged').
Json = MutableDict.as_mutable(JSON)
JsonList = MutableList.as_mutable(JSON)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(80), unique=True, index=True, nullable=False)
    password_hash = Column(String(256), nullable=False)
    email = Column(String(200), index=True, nullable=True)
    name = Column(String(160), nullable=True)
    google_id = Column(String(80), index=True, nullable=True)
    profile_picture = Column(String(300), nullable=True)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    settings = relationship(
        "UserSettings", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    preferences = relationship(
        "UserPreference", back_populates="user", cascade="all, delete-orphan"
    )


class UserSettings(Base):
    """Per-user credentials (encrypted at rest) + connection preferences.

    Every user of the platform provides their own Telegram bot token and Groq
    API key through the web interface; they are never shared or hardcoded.
    """

    __tablename__ = "user_settings"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    telegram_bot_token = Column(Text, default="")   # encrypted
    telegram_api_id = Column(Text, default="")      # encrypted (optional)
    telegram_api_hash = Column(Text, default="")    # encrypted (optional)
    groq_api_key = Column(Text, default="")         # encrypted

    target_chat = Column(String(200), default="")   # group username or numeric id
    bot_enabled = Column(Boolean, default=False)
    notifications_enabled = Column(Boolean, default=True)
    ocr_screenshots = Column(Boolean, default=True)
    poll_after_class = Column(Boolean, default=True)

    updated_at = Column(DateTime, default=_now, onupdate=_now)

    user = relationship("User", back_populates="settings")


class UserPreference(Base):
    """Scoped adaptive memory -> rules the master agent learns about a user.

    Examples:
      ("trust", "Alice is the lecturer")
      ("not_trust", "Bob is not the lecturer")
      ("alias", "ML means Machine Learning")
      ("priority", "always show deadlines first")
      ("notif", "no telegram notifications")
    These modify per-user memory, never the global system prompt.
    """

    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    kind = Column(String(40), index=True)  # trust | not_trust | alias | priority | notif | note
    value = Column(Text)                    # the learned statement
    created_at = Column(DateTime, default=_now)

    user = relationship("User", back_populates="preferences")


class SourcePool(Base):
    """Context window of the last N raw Telegram messages per user/chat-thread."""

    __tablename__ = "source_pool"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    thread_key = Column(String(200), index=True)  # chat_id::thread_id
    telegram_msg_id = Column(Integer)
    sender_name = Column(String(120), default="")
    sender_username = Column(String(120), default="")
    sender_is_lecturer = Column(Boolean, default=False)
    timestamp = Column(DateTime, default=_now)
    text = Column(Text, default="")
    media_type = Column(String(30), default="")   # none, photo, document...
    bucket = Column(String(30), default="other")  # assignment | exam | other
    raw_json = Column(Json, default=lambda: MutableDict())


class AcademicEvent(Base):
    """A single structured academic fact extracted from Telegram.

    type in {assignment, quiz, exam, class, deadline, course, announcement,
             lecture_topic}
    """

    __tablename__ = "academic_events"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    type = Column(String(30), index=True)
    course = Column(String(120), index=True)
    title = Column(String(300), default="")
    description = Column(Text, default="")
    details = Column(Json, default=lambda: MutableDict())
    event_date = Column(String(20), default="")   # ISO date
    start_time = Column(String(10), default="")
    end_time = Column(String(10), default="")
    location = Column(String(160), default="")
    topic = Column(String(300), default="")
    deadline = Column(String(30), default="")     # ISO datetime (so we can compare)
    status = Column(String(30), default="not_started")  # assignments lifecycle
    confidence = Column(String(12), default="MEDIUM")
    source = Column(String(30), default="community")    # confirmed|community|inferred
    source_data = Column(Json, default=lambda: MutableDict())            # {message_id, chat_id, thread_id, timestamp, raw_text, sender}
    polled = Column(Boolean, default=False)             # class already polled/summarized
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class PollResult(Base):
    __tablename__ = "poll_results"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    course = Column(String(120))
    thread_id = Column(String(60), default="")
    question = Column(Text, default="")
    polling_message_id = Column(Integer, default=0)
    options = Column(JsonList, default=lambda: MutableList())
    winning_topic = Column(String(300), default="")
    votes = Column(Json, default=lambda: MutableDict())
    summary_generated = Column(Boolean, default=False)
    related_event_id = Column(Integer, default=0)  # coverage polls link to a quiz/exam
    created_at = Column(DateTime, default=_now)


class MissedSummary(Base):
    __tablename__ = "missed_summaries"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    course = Column(String(120))
    date = Column(String(20), default="")
    topic = Column(String(300), default="")
    summary = Column(Text, default="")
    basis = Column(String(300), default="")   # e.g. "poll: 3 votes -> Kinematics"
    cross_check = Column(Json, default=lambda: MutableDict())   # outline cross-check verdict: {matched, item, confidence, ...}
    created_at = Column(DateTime, default=_now)


class MissedRequest(Base):
    """An open 'did anyone miss X?' request the assistant sent to the group.
    A class is added to the missed dashboard only when a group member replies
    to this request (desired flow: assistant asks -> any response = missed)."""

    __tablename__ = "missed_requests"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    course = Column(String(120))
    topic = Column(String(300))
    telegram_message_id = Column(String(40), default="")
    requested_at = Column(DateTime, default=_now)
    completed_at = Column(DateTime, nullable=True)


class DocumentChunkRef(Base):
    """Bookkeeping of documents ingested into the user's RAG store."""

    __tablename__ = "document_refs"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    course = Column(String(120), default="general")
    filename = Column(String(300), default="")
    source = Column(String(300), default="telegram")  # telegram | upload
    chunk_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)


class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    role = Column(String(20))            # user | assistant
    content = Column(Text, default="")
    created_at = Column(DateTime, default=_now)


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    kind = Column(String(40))            # deadline | quiz | assignment | announcement | missed | system
    title = Column(String(200), default="")
    body = Column(Text, default="")
    related_id = Column(Integer, default=0)
    read = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)


class TelegramMessage(Base):
    """Outbound messages the assistant posted to a Telegram group.

    Lets the assistant's write access be tracked in-app (sender_id is
    'classmate_ai_bot' for messages the assistant posts).
    """

    __tablename__ = "telegram_messages"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, index=True)
    chat = Column(String(200), default="")
    sender_id = Column(String(120), default="classmate_ai_bot")
    text = Column(Text, default="")
    telegram_msg_id = Column(String(40), default="")
    created_at = Column(DateTime, default=_now)