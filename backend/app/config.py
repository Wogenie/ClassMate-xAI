"""Application configuration loaded from environment (.env supported)."""
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("CLASSMATE_DATA_DIR", BACKEND_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Load a backend/.env if present (python-dotenv is optional at import time).
try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass


def _secret_key() -> str:
    key = os.environ.get("CLASSMATE_SECRET_KEY", "")
    if key:
        return key
    f = DATA_DIR / ".secret_key"
    if not f.exists():
        f.write_text(os.urandom(48).hex())
    return f.read_text().strip()


SECRET_KEY = _secret_key()

DATABASE_URL = os.environ.get(
    "CLASSMATE_DATABASE_URL", f"sqlite:///{DATA_DIR / 'classmate.db'}"
)
CHROMA_DIR = Path(os.environ.get("CLASSMATE_CHROMA_DIR", DATA_DIR / "chroma"))

APP_PORT = int(os.environ.get("CLASSMATE_PORT", "8000"))

CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
] + [
    o.strip()
    for o in os.environ.get("CLASSMATE_CORS_ORIGINS", "").split(",")
    if o.strip()
]

# Default Groq model. Override with CLASSMATE_LLM_MODEL env var.
DEFAULT_LLM_MODEL = os.environ.get("CLASSMATE_LLM_MODEL", "openai/gpt-oss-20b")

# Models offered in the Assistant chat picker. The labels are shown to users.
LLM_MODEL_CHOICES = {
    "openai/gpt-oss-20b": "GPT-OSS 20B · fastest",
    "openai/gpt-oss-120b": "GPT-OSS 120B · best quality",
    "qwen/qwen3.6-27b": "Qwen 3.6 27B · balanced",
}
LLM_MODELS = list(LLM_MODEL_CHOICES.keys())

# Bot-mode fallback credentials when the user only supplies a bot token.
# Telethon accepts these sample credentials for bot-only operations.
BOT_MODE_API_ID = int(os.environ.get("CLASSMATE_API_ID", "6"))
BOT_MODE_API_HASH = os.environ.get(
    "CLASSMATE_API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e"
)

JWT_ALGO = "HS256"
JWT_EXPIRE_MINUTES = int(os.environ.get("CLASSMATE_JWT_EXPIRE_MINUTES", "1440"))

# Google Sign-in (server-side OAuth client). The same value is also used by the
# frontend through VITE_GOOGLE_CLIENT_ID. Empty → sign-in is disabled cleanly.
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"

# Deadlines / polling scheduler tuning
DEADLINE_SWEEP_MINUTES = int(os.environ.get("CLASSMATE_DEADLINE_SWEEP_MIN", "15"))
POLL_SWEEP_MINUTES = int(os.environ.get("CLASSMATE_POLL_SWEEP_MIN", "15"))
POLL_AFTER_CLASS_MINUTES = int(os.environ.get("CLASSMATE_POLL_AFTER_MIN", "15"))
POLL_VOTE_WINDOW_SECONDS = int(os.environ.get("CLASSMATE_POLL_VOTE_WINDOW_S", "600"))
# A poll finalizes as soon as this many students answer (majority wins); the
# fixed window above is only the safety fallback for low-traffic classes.
POLL_MIN_VOTES = int(os.environ.get("CLASSMATE_POLL_MIN_VOTES", "3"))
POLL_TALLY_INTERVAL_SECONDS = int(os.environ.get("CLASSMATE_POLL_TALLY_INTERVAL_S", "30"))

# Deadline reminders (hours before the deadline) that trigger a push when the
# submission/event is still open (not completed/submitted).
DEADLINE_REMINDER_HOURS = [
    int(x) for x in os.environ.get("CLASSMATE_DEADLINE_REMINDER_HOURS", "24,12").split(",")
    if x.strip().lstrip("-").isdigit()
] or [24, 12]

# Assignment understanding: background sweep cadence + how long to wait before
# re-analyzing an assignment whose summary is still the raw announcement.
ASSIGNMENT_SWEEP_MINUTES = int(os.environ.get("CLASSMATE_ASSIGNMENT_SWEEP_MIN", "2"))
ANALYSIS_COOLDOWN_SECONDS = int(os.environ.get("CLASSMATE_ANALYSIS_COOLDOWN_S", "900"))

# Quiz/exam coverage + portion-summary backfill sweep (course-outline-grounded
# descriptions for every quiz/exam that still lacks one).
QUIZ_SWEEP_MINUTES = int(os.environ.get("CLASSMATE_QUIZ_SWEEP_MIN", "5"))
QUIZ_SWEEP_BATCH = int(os.environ.get("CLASSMATE_QUIZ_SWEEP_BATCH", "2"))

# Auto-cleanup: remove a passed event (class/quiz/assignment/deadline) N days
# after its deadline/date has passed.
EVENT_RETENTION_DAYS = int(os.environ.get("CLASSMATE_EVENT_RETENTION_DAYS", "2"))