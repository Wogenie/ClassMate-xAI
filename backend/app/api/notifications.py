"""In-app notifications."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import notifier
from .deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_notifications(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = notifier.list_for_user(db, user.id)
    return [
        {
            "id": n.id,
            "kind": n.kind,
            "title": n.title,
            "body": n.body,
            "read": n.read,
            "created_at": n.created_at.isoformat() if n.created_at else "",
        }
        for n in rows
    ]


@router.post("/{notif_id}/read")
def mark_read(notif_id: int, user=Depends(get_current_user),
              db: Session = Depends(get_db)):
    notifier.mark_read(db, user.id, notif_id)
    return {"ok": True}