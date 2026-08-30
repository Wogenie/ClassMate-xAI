"""Pydantic request/response schemas."""
from typing import Any, Optional

from pydantic import BaseModel, Field


# ---------- Auth ----------
class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class GoogleTokenRequest(BaseModel):
    credential: str  # the Google Identity Services ID token (JWT)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    email: str = ""
    name: str = ""
    picture: str = ""


# ---------- Settings (credential input area) ----------
class SettingsUpdate(BaseModel):
    telegram_bot_token: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    groq_api_key: str = ""
    target_chat: str = ""
    bot_enabled: bool = False
    notifications_enabled: bool = True
    ocr_screenshots: bool = True
    poll_after_class: bool = True


class SettingsView(BaseModel):
    telegram_bot_token: str = ""       # masked, never the real value
    groq_api_key: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    target_chat: str = ""
    bot_enabled: bool = False
    notifications_enabled: bool = True
    ocr_screenshots: bool = True
    poll_after_class: bool = True
    bot_running: bool = False


class ConnectionTestRequest(BaseModel):
    telegram_bot_token: str = ""
    groq_api_key: str = ""
    target_chat: str = ""
    telegram_api_id: str = ""
    telegram_api_hash: str = ""
    mode: str = "all"  # all | groq | telegram


class ConnectionTestResult(BaseModel):
    groq_ok: bool = False
    groq_message: str = ""
    telegram_ok: bool = False
    telegram_message: str = ""


# ---------- Academic ----------
class AssignmentStatusUpdate(BaseModel):
    status: str


class AssignmentAnswerRequest(BaseModel):
    answer: str  # the student's reply to the dynamically generated questions  # not_started | in_progress | submitted | completed


class EventPatch(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    deadline: Optional[str] = None
    course: Optional[str] = None
    topic: Optional[str] = None


class BigFatThing(BaseModel):
    """Used so the API layer *never* serializes secrets."""

    value: Any


# ---------- Assistant ----------
class ChatRequest(BaseModel):
    message: str
    history: Optional[list] = None  # list of {role, content}
    model: Optional[str] = None  # Groq model id chosen in the Assistant chat


class RuleRequest(BaseModel):
    statement: str  # e.g. "Alice is actually the lecturer"


class SimulateRequest(BaseModel):
    text: str
    sender_name: str = "Someone"
    thread_id: str = ""
    group_id: str = ""