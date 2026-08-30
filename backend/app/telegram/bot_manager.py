"""Per-user Telegram bot manager.

Each user's OWN bot token (entered in the web Settings) powers a private
Telethon client. Clients run as asyncio tasks inside the app's event loop so
FastAPI endpoints can start/stop them at any time.
"""
import asyncio
import logging
from pathlib import Path

from telethon import TelegramClient, events

from .. import config, llm as llm_service

log = logging.getLogger("classmate.bots")

_clients: dict[int, TelegramClient] = {}
_tasks: dict[int, asyncio.Task] = {}
_start_lock = asyncio.Lock()
_sessions_dir = config.DATA_DIR / "bot_sessions"
_sessions_dir.mkdir(parents=True, exist_ok=True)


async def _make_client(user_id: int, settings: dict) -> TelegramClient:
    api_id = settings.get("telegram_api_id") or config.BOT_MODE_API_ID
    api_hash = settings.get("telegram_api_hash") or config.BOT_MODE_API_HASH
    session_file = str(_sessions_dir / f"user_{user_id}")
    return TelegramClient(session_file, int(api_id) if str(api_id).isdigit() else config.BOT_MODE_API_ID, api_hash)


async def _run_bot(user_id: int, settings: dict) -> None:
    from .ingestion import telegram_event_handler

    client = await _make_client(user_id, settings)
    _clients[user_id] = client

    @client.on(events.NewMessage)
    async def on_message(event):
        await telegram_event_handler(user_id, event)

    try:
        await client.start(bot_token=settings["telegram_bot_token"])
        me = await client.get_me()
        log.info("Bot online for user %s (@%s)", user_id, getattr(me, "username", "?"))
        await client.run_until_disconnected()
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        log.error("Bot task failed for user %s: %s", user_id, exc)
    finally:
        await client.disconnect()
        _clients.pop(user_id, None)


async def start_user_bot(user_id: int) -> str:
    """Start (or restart) the user's bot. Returns a human readable status."""
    async with _start_lock:
        await stop_user_bot(user_id)
        from ..database import SessionLocal

        db = SessionLocal()
        try:
            settings = llm_service.get_decrypted_settings(db, user_id)
        finally:
            db.close()

        if not settings["telegram_bot_token"]:
            return "No Telegram bot token configured."
        if not settings["groq_api_key"]:
            return "No Groq API key configured — bot can run but the agent cannot reason yet."

        task = asyncio.create_task(_run_bot(user_id, settings))
        _tasks[user_id] = task
        return "Bot started."


async def stop_user_bot(user_id: int) -> None:
    task = _tasks.pop(user_id, None)
    if task:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass
    client = _clients.pop(user_id, None)
    if client:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def is_running(user_id: int) -> bool:
    return user_id in _tasks and not _tasks[user_id].done()


async def send_message(user_id: int, chat: str, text: str) -> int | None:
    """Send a text message and return the Telegram message id (None on failure)."""
    client = _clients.get(user_id)
    if not client or not client.is_connected():
        return None
    entity = await _resolve_entity(client, chat)
    if entity is None:
        return None
    msg = await client.send_message(entity, text)
    return getattr(msg, "id", None)


async def get_client(user_id: int) -> TelegramClient | None:
    return _clients.get(user_id)


async def _resolve_entity(client: TelegramClient, chat: str):
    chat = str(chat).strip()
    try:
        if chat.lstrip("-").isdigit():
            return int(chat)
        return chat
    except Exception:
        return chat


# ------------------------------------------------------------- testers

async def test_telegram_connection(bot_token: str, api_id: str = "", api_hash: str = "",
                                   target_chat: str = "") -> dict:
    """Spin up a throwaway client to validate the bot token + resolve target chat."""
    api_id = api_id or str(config.BOT_MODE_API_ID)
    api_hash = api_hash or config.BOT_MODE_API_HASH
    client = TelegramClient(
        str(_sessions_dir / "connection_test"), int(api_id), api_hash,
    )
    try:
        await client.start(bot_token=bot_token)
        me = await client.get_me()
        info = {
            "ok": True,
            "message": f"Connected as @{getattr(me, 'username', 'bot')} ({me.id})",
        }
        if target_chat:
            try:
                entity = await client.get_entity(target_chat)
                info["chat"] = getattr(entity, "title", str(entity.id))
                info["message"] += f". Target chat resolved: '{info['chat']}'"
            except Exception as exc:  # noqa: BLE001
                info["message"] += f". Warning: could not resolve target chat ({exc})."
        return info
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Telegram connection failed: {exc}"}
    finally:
        try:
            await client.disconnect()
        except Exception:  # noqa: BLE001
            pass


def test_groq_connection(api_key: str) -> dict:
    try:
        from langchain_groq import ChatGroq
        from langchain_core.messages import HumanMessage

        llm = ChatGroq(model_name=config.DEFAULT_LLM_MODEL, groq_api_key=api_key, temperature=0)
        res = llm.invoke([HumanMessage(content="Reply with exactly: OK")])
        ok = "ok" in res.content.lower()
        return {"ok": ok, "message": res.content.strip()[:80] if ok else f"Unexpected reply: {res.content[:80]}"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "message": f"Groq call failed: {str(exc)[:160]}"}