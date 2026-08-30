"""Notifications: in-app (database) + optional Telegram push through the
user's own bot. Sends messages to the user's configured target chat."
"""
from sqlalchemy.orm import Session

from .. import looputil
from ..models import Notification
from .. import llm as llm_service
from ..telegram import bot_manager
from . import academic


def push(db: Session, user_id: int, kind: str, title: str, body: str,
         related_id: int = 0, tg_send: bool = False) -> Notification:
    # tg_send defaults to False: the bot does NOT post confirmations/notices
    # into the group. The only group posts are deliberate info-requests
    # (e.g. the assignment 'Ask details' broadcast), which use send_message
    # directly rather than this helper.
    n = academic.add_notification(db, user_id, kind, title, body, related_id)
    if tg_send:
        settings = llm_service.get_decrypted_settings(db, user_id)
        if settings.get("notifications_enabled", True):
            # Post where the academic conversation actually happens.
            chat = academic.resolve_group(db, user_id, fallback=settings.get("target_chat", ""))
            if chat:
                text = f"🔔 *{title}*\n{body}"
                looputil.call_coro(
                    bot_manager.send_message(user_id, chat, text)
                )
    return n


def list_for_user(db: Session, user_id: int) -> list[Notification]:
    return (
        db.query(Notification)
        .filter_by(user_id=user_id)
        .order_by(Notification.created_at.desc())
        .limit(100)
        .all()
    )


def mark_read(db: Session, user_id: int, notif_id: int) -> None:
    row = db.query(Notification).filter_by(id=notif_id, user_id=user_id).first()
    if row:
        row.read = True
        db.commit()