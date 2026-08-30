"""Quizzes & exams tracker + Dynamic Quiz Coverage Detection endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..agent import graph as agent
from ..database import get_db
from ..models import AcademicEvent
from ..services import academic, coverage as cov
from .deps import get_current_user

router = APIRouter(prefix="/quizzes", tags=["quizzes"])


class ClarifyOptionRequest(BaseModel):
    option: str


@router.get("")
def quizzes(user=Depends(get_current_user), db: Session = Depends(get_db)):
    quizzes = [academic._serialize(q) for q in academic.list_events(db, user.id, etype="quiz")]
    exams = [academic._serialize(e) for e in academic.list_events(db, user.id, etype="exam")]
    return {"quizzes": quizzes, "exams": exams}


@router.post("/study-guide/{event_id}")
def study_guide(event_id: int,
                user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate (or regenerate) a study guide + practice questions for a quiz/exam."""
    result = agent.generate_study_guide(db, user.id, event_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.post("/coverage/{event_id}/detect")
def detect_coverage(event_id: int,
                    user=Depends(get_current_user), db: Session = Depends(get_db)):
    """(Re)detect coverage for a quiz/exam (EXPLICIT / INFERRED / AMBIGUOUS)."""
    row = _get_quiz_row(db, user.id, event_id)
    text = row.description or row.title or ""
    state = cov.detect_coverage(db, user.id, row, text, [])
    payload = {
        "coverage_status": state["coverage_status"],
        "coverage": state["coverage"],
        "topics": state["topics"],
        "coverage_evidence": state["evidence"],
        "requires_clarification": state["requires_clarification"],
    }
    if payload["coverage_status"]:
        cov.save_coverage(db, row, payload)
    if state["requires_clarification"]:
        cov.build_clarification(db, user.id, row, text)
        cov.ask_group_in_background(db, user.id, row.id, text)
    return academic._serialize(row)


@router.get("/coverage/{event_id}")
def get_coverage(event_id: int,
                 user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Return current coverage state + clarification options."""
    row = _get_quiz_row(db, user.id, event_id)
    text = row.description or row.title or ""
    cover = cov.get_coverage(row)
    if not cover.get("clarification", {}).get("asked"):
        cov.build_clarification(db, user.id, row, text)
        cover = cov.get_coverage(row)
    return {"coverage": cover, "event": academic._serialize(row)}


@router.post("/coverage/{event_id}/ask-group")
def ask_group(event_id: int,
              user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Broadcast the pending clarification as a Telegram POLL to the school
    group (dynamic options come from the course materials)."""
    row = _get_quiz_row(db, user.id, event_id)
    text = row.description or row.title or ""
    cov.build_clarification(db, user.id, row, text)
    cov.ask_group_in_background(db, user.id, event_id, text)
    return academic._serialize(row)


@router.post("/portion-summary/{event_id}")
def portion_summary(event_id: int,
                    user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate (or regenerate) the PORTION summary from outline + course docs."""
    row = _get_quiz_row(db, user.id, event_id)
    summary = cov.generate_portion_summary(db, user.id, row)
    return {"summary": summary, "event": academic._serialize(row)}


@router.post("/coverage/{event_id}/respond")
def respond(event_id: int, body: ClarifyOptionRequest,
            user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Record a student's clarification answer, then try to resolve consensus."""
    row = _get_quiz_row(db, user.id, event_id)
    cov.add_student_response(db, row, body.option, sender=user.username)
    result = cov.resolve_from_responses(db, user.id, row)
    cover = cov.get_coverage(row)
    if result.get("consensus"):
        cover = cov.get_coverage(row)
    return {"consensus": result["consensus"], "reason": result.get("reason", ""),
            "coverage": cover, "event": academic._serialize(row)}


def _get_quiz_row(db, user_id: int, event_id: int):
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
    if row is None or row.type not in ("quiz", "exam"):
        raise HTTPException(status_code=404, detail="Quiz/exam not found")
    return row
