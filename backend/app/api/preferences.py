"""Adaptive behavior: the user teaches the agent persistent rules."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..schemas import RuleRequest
from ..services import memory
from .deps import get_current_user

router = APIRouter(prefix="/preferences", tags=["preferences"])


@router.get("")
def list_rules(user=Depends(get_current_user), db: Session = Depends(get_db)):
    rules = memory.list_rules(db, user.id)
    return [
        {"id": r.id, "kind": r.kind, "value": r.value,
         "created_at": r.created_at.isoformat() if r.created_at else ""}
        for r in rules
    ]


@router.post("")
def add_rule(body: RuleRequest, user=Depends(get_current_user),
             db: Session = Depends(get_db)):
    kind = memory.remember_from_statement(db, user.id, body.statement)
    return {"ok": True, "kind": kind, "statement": body.statement}