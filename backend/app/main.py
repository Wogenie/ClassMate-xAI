"""ClassMateX — FastAPI application entrypoint.

Run:  uvicorn app.main:app --reload --port 8000
"""
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    log.info("ClassMateX backend up on :%s", config.APP_PORT)
    yield
    try:
        app.state.scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        pass


app = FastAPI(title="ClassMateX", version="0.1.0", lifespan=lifespan)

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
    return {"status": "ok", "app": "ClassMateX"}