"""SQLAlchemy engine, session factory and Base."""
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    # check_same_thread=False lets background threads (Telegram ingestion,
    # scheduler sweeps, assignment auto-analysis) open sessions from other
    # threads. The timeout sets SQLite's busy_timeout so concurrent writers
    # WAIT for the lock instead of raising "database is locked" and dropping
    # group replies / analysis updates.
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30

engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
    _migrate()


def _migrate():
    """Best-effort additive migrations for existing SQLite databases."""
    if not config.DATABASE_URL.startswith("sqlite"):
        return
    from sqlalchemy import text

    with engine.connect() as conn:
        # users: Google sign-in columns (auth.txt). Google-only accounts have
        # username == email and an empty password_hash (field stays NOT NULL).
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(users)"))]
            for col, decl in (
                ("email", "VARCHAR(200)"),
                ("name", "VARCHAR(160)"),
                ("google_id", "VARCHAR(80)"),
                ("profile_picture", "VARCHAR(300)"),
                ("updated_at", "DATETIME"),
            ):
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE users ADD COLUMN {col} {decl}"))
                    conn.commit()
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS ix_users_google_id ON users (google_id)"
            ))
            conn.commit()
        except Exception:  # noqa: BLE001  (never block startup on a schema tweak)
            pass
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(poll_results)"))]
            if cols and "related_event_id" not in cols:
                conn.execute(
                    text("ALTER TABLE poll_results ADD COLUMN related_event_id INTEGER DEFAULT 0")
                )
                conn.commit()
        except Exception:  # noqa: BLE001  (never block startup on a schema tweak)
            pass
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(missed_summaries)"))]
            if cols and "cross_check" not in cols:
                conn.execute(
                    text("ALTER TABLE missed_summaries ADD COLUMN cross_check JSON")
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            pass
        try:
            cols = [r[1] for r in conn.execute(text("PRAGMA table_info(source_pool)"))]
            for col, decl in (
                ("sender_username", "VARCHAR(120)"),
                ("bucket", "VARCHAR(30)"),
            ):
                if cols and col not in cols:
                    conn.execute(text(f"ALTER TABLE source_pool ADD COLUMN {col} {decl}"))
                    conn.commit()
        except Exception:  # noqa: BLE001
            pass
            if cols and "telegram_msg_id" not in cols:
                conn.execute(
                    text("ALTER TABLE telegram_messages ADD COLUMN telegram_msg_id VARCHAR(40) DEFAULT ''")
                )
                conn.commit()
        except Exception:  # noqa: BLE001
            pass