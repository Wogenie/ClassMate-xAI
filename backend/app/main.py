"""Classmate xAI — FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, looputil, prompt_loader
from .database import init_db
from .telegram import scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("classmate")


@asynccontextmanager
async def lifespan(app: FastAPI):
    looputil.set_main_loop(asyncio.get_running_loop())
    init_db()
    prompt_loader.ensure_default_prompt_files()
    app.state.scheduler = scheduler.start_scheduler()

    # Re-start each user's enabled Telegram bot so the backend keeps receiving
    # messages after a restart (bots do not survive the process being down).
    from .telegram import bot_manager

    started = await bot_manager.auto_start_enabled_bots()
    if started:
        log.info("Auto-started Telegram bots for users: %s", started)

    log.info("Classmate xAI backend up on :%s", config.APP_PORT)
    yield
    try:
        app.state.scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="Classmate xAI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from .api import (  # noqa: E402
    assignments,
    assistant,
    auth,
    dashboard,
    ingest,
    missed,
    notifications,
    preferences,
    quizzes,
    schedule,
    settings,
)


def _include(router, prefix: str = ""):
    app.include_router(router, prefix=f"/api{prefix}")


_include(auth.router)
_include(settings.router)
_include(assignments.router)
_include(schedule.router)
_include(quizzes.router)
_include(missed.router)
_include(assistant.router)
_include(dashboard.router)
_include(ingest.router)
_include(notifications.router)
_include(preferences.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": "Classmate xAI"}


# ---- Production static hosting of the built SPA (same origin) ----
# When frontend/dist exists, serve it. The SPA catch-all returns index.html for
# any non-API path so client-side routing works on refresh/deep links.
_HAS_FRONTEND = config.FRONTEND_DIST.is_dir()
if _HAS_FRONTEND:
    assets_dir = config.FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path.startswith("api"):  # safety net; API routes resolve first
            raise Exception("unreachable")
        candidate = config.FRONTEND_DIST / full_path
        if full_path and candidate.is_file() and candidate.is_relative_to(
            config.FRONTEND_DIST
        ):
            return FileResponse(candidate)
        index = config.FRONTEND_DIST / "index.html"
        if index.is_file():
            return FileResponse(index)
        raise Exception("frontend not built")