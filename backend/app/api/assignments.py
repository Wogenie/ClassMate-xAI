"""Assignments & deadlines: full list with lifecycle, status updates."""
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..agent import graph as agent
from ..database import get_db
from ..knowledge import documents
from ..models import AcademicEvent
from ..schemas import AssignmentAnswerRequest, AssignmentStatusUpdate, EventPatch
from ..services import academic, assignment_agent
from .deps import get_current_user

router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.get("")
def list_assignments(status: str | None = None,
                     user=Depends(get_current_user),
                     db: Session = Depends(get_db)):
    rows = academic.list_events(db, user.id, etype="assignment", status=status)
    # Light, deduped background kick: assignments with no summary yet get
    # analyzed off the request path (re-analysis of fallback summaries happens in
    # the periodic scheduler sweep, not on every page load).
    assignment_agent.kick_pending_analyses(user.id)
    return [academic._serialize(r) for r in rows]


@router.get("/deadlines")
def deadlines(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return academic.deadline_buckets(db, user.id)


@router.post("/{event_id}/solve")
def solve(event_id: int,
          user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Auto-solve a stored assignment (or regenerate its solution)."""
    result = agent.solve_assignment(db, user.id, event_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@router.patch("/{event_id}/status")
def set_status(event_id: int, body: AssignmentStatusUpdate,
               user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = academic.set_assignment_status(db, user.id, event_id, body.status)
    if row is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return academic._serialize(row)


@router.patch("/{event_id}")
def patch(event_id: int, body: EventPatch,
          user=Depends(get_current_user), db: Session = Depends(get_db)):
    row = academic.patch_event(
        db, user.id, event_id,
        status=body.status, title=body.title, deadline=body.deadline,
        course=body.course, topic=body.topic,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return academic._serialize(row)


# ------------------------------------------------ assignment understanding

def _get_assignment(db, user_id: int, event_id: int):
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id, type="assignment").first()
    if row is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return row


@router.post("/{event_id}/analyze")
def analyze(event_id: int,
            user=Depends(get_current_user), db: Session = Depends(get_db)):
    """(Re)run the Assignment Understanding Agent on this assignment."""
    row = _get_assignment(db, user.id, event_id)
    assignment_agent.analyze_assignment(db, user.id, row)
    return academic._serialize(row)


@router.post("/{event_id}/ask")
def ask_questions(event_id: int,
                  user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Generate dynamic clarification questions and broadcast them to the
    students' Telegram group. Their replies are matched, cleaned, and put into
    the assignment dashboard automatically."""
    row = _get_assignment(db, user.id, event_id)
    result = assignment_agent.ask_group_details(db, user.id, row)
    return {**result, "event": academic._serialize(row)}


@router.post("/{event_id}/answer")
def answer_question(event_id: int, body: AssignmentAnswerRequest,
                    user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Submit the student's answer to the clarification questions."""
    row = _get_assignment(db, user.id, event_id)
    result = assignment_agent.consume_answer(db, user.id, row, body.answer)
    return {
        "event": academic._serialize(row),
        **result,
    }


@router.post("/{event_id}/upload")
async def upload_assignment_doc(event_id: int, file: UploadFile = File(...),
                                user=Depends(get_current_user),
                                db: Session = Depends(get_db)):
    """Upload a PDF/DOCX/image to enrich the assignment's understanding."""
    row = _get_assignment(db, user.id, event_id)
    ext = Path(file.filename or "").suffix.lower()
    if not documents.file_handled_extension(ext):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    tmpdir = tempfile.mkdtemp(prefix="classmate_assignment_upload_")
    target = Path(tmpdir) / (file.filename or f"upload{ext}")
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    text = documents.read_file(str(target))
    if not text.strip():
        raise HTTPException(status_code=400,
                            detail="No readable text extracted from file. "
                                   "If this is an image, make sure OCR (Tesseract) is installed.")

    result = assignment_agent.feed_document(db, user.id, row, file.filename or "upload", text)
    return {"event": academic._serialize(row), **result}