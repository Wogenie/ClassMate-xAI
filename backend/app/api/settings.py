"""Per-user credentials 'input area' (Settings): bot token, Groq key, target
chat, connection test, and bot start/stop. Keys are encrypted at rest."""
from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import llm as llm_service, security
from ..database import get_db
from ..schemas import (
    ConnectionTestRequest,
    ConnectionTestResult,
    SettingsUpdate,
    SettingsView,
)
from ..telegram import bot_manager
from .deps import get_current_user

router = APIRouter(prefix="/settings", tags=["settings"])


def _mask(value: str) -> str:
    if not value:
        return ""
    return value[:5] + "••••" if len(value) > 5 else "••••"


@router.get("", response_model=SettingsView)
def get_settings(user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = llm_service.get_or_create_settings(db, user.id)
    return SettingsView(
        telegram_bot_token=_mask(security.decrypt_secret(row.telegram_bot_token)),
        groq_api_key=_mask(security.decrypt_secret(row.groq_api_key)),
        telegram_api_id=_mask(security.decrypt_secret(row.telegram_api_id)),
        telegram_api_hash=_mask(security.decrypt_secret(row.telegram_api_hash)),
        target_chat=row.target_chat or "",
        bot_enabled=row.bot_enabled,
        notifications_enabled=row.notifications_enabled,
        ocr_screenshots=row.ocr_screenshots,
        poll_after_class=row.poll_after_class,
        bot_running=bot_manager.is_running(user.id),
    )


@router.put("", response_model=SettingsView)
def update_settings(body: SettingsUpdate, user=Depends(get_current_user),
                    db: Session = Depends(get_db)):
    llm_service.save_settings(
        db, user.id,
        body.model_dump(),
    )
    if body.bot_enabled:
        from .. import looputil
        from ..telegram import bot_manager

        looputil.call_coro(bot_manager.start_user_bot(user.id))
    return get_settings(user=user, db=db)


@router.post("/test", response_model=ConnectionTestResult)
async def test_connection(body: ConnectionTestRequest,
                          user=Depends(get_current_user),
                          db: Session = Depends(get_db)):
    """Validate the provided Groq key and/or Telegram bot token on demand."""
    result = ConnectionTestResult()
    mode = (body.mode or "all").lower()

    if mode in ("all", "groq") and body.groq_api_key:
        groq = await run_in_threadpool(bot_manager.test_groq_connection, body.groq_api_key)
        result.groq_ok = groq["ok"]
        result.groq_message = groq["message"]
    elif mode in ("all", "groq"):
        result.groq_message = "Provide a Groq API key to test it."

    if mode in ("all", "telegram") and body.telegram_bot_token:
        tg = await bot_manager.test_telegram_connection(
            body.telegram_bot_token,
            api_id=body.telegram_api_id,
            api_hash=body.telegram_api_hash,
            target_chat=body.target_chat,
        )
        result.telegram_ok = tg["ok"]
        result.telegram_message = tg["message"]
    elif mode in ("all", "telegram"):
        result.telegram_message = "Provide a Telegram bot token to test it."

    return result


@router.post("/start")
async def start_bot(user=Depends(get_current_user), db: Session = Depends(get_db)):
    llm_service.get_or_create_settings(db, user.id)
    status = await bot_manager.start_user_bot(user.id)
    return {"ok": True, "status": status}


@router.post("/stop")
async def stop_bot(user=Depends(get_current_user), db: Session = Depends(get_db)):
    await bot_manager.stop_user_bot(user.id)
    row = llm_service.get_or_create_settings(db, user.id)
    row.bot_enabled = False
    db.commit()
    return {"ok": True, "status": "Bot stopped."}