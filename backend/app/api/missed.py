"""Missed-class summaries."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agent import graph as agent
from ..database import get_db
from ..services import academic
from .deps import get_current_user

router = APIRouter(prefix="/missed", tags=["missed"])


class MissedGenRequest(BaseModel):
    course: str
    date: str


@router.get("")
def missed(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rows = academic.list_missed(db, user.id)
    return [
        {
            "id": m.id,
            "course": m.course,
            "date": m.date,
            "topic": m.topic,
            "summary": m.summary,
            "basis": m.basis,
            "cross_check": m.cross_check or {},
        }
        for m in rows
    ]


@router.post("/generate")
def generate(body: MissedGenRequest,
             user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Reconstruct a missed class by fusing course outline + Telegram + RAG."""
    result = agent.missed_summary_with_outline(db, user.id, body.course, body.date)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("error", "Failed"))
    return result
