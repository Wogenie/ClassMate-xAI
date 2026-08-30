"""Ingestion helpers: simulate a Telegram message & upload course documents."""
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import llm as llm_service
from ..database import get_db
from ..knowledge import documents, metadata, rag
from ..models import DocumentChunkRef
from ..schemas import SimulateRequest
from ..telegram.ingestion import simulate_message
from .deps import get_current_user

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/simulate")
def simulate(body: SimulateRequest, user=Depends(get_current_user),
             db: Session = Depends(get_db)):
    llm_service.get_or_create_settings(db, user.id)
    result = simulate_message(
        db, user.id, body.text, body.sender_name,
        thread_id=body.thread_id, group_id=body.group_id,
    )
    return result


@router.post("/document")
async def upload_document(
    file: UploadFile = File(...),
    course: str = Form(""),
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ext = Path(file.filename or "").suffix.lower()
    if not documents.file_handled_extension(ext):
        raise HTTPException(status_code=400, detail=f"Unsupported format: {ext}")

    tmpdir = tempfile.mkdtemp(prefix="classmate_upload_")
    target = Path(tmpdir) / (file.filename or f"upload{ext}")
    with target.open("wb") as out:
        shutil.copyfileobj(file.file, out)

    text = documents.read_file(str(target))
    if not text.strip():
        raise HTTPException(status_code=400, detail="No readable text extracted from file")

    # Dynamic structure detection: discover course/chapter/section/topic from the
    # content itself (section 1 of the coverage spec) and chunk with rich metadata.
    llm = llm_service.get_llm(db, user.id)
    detected = metadata.detect_structures(llm, text)
    chunks = detected.get("chunks") or []
    if chunks:
        resolved_course = course or detected.get("course") or "general"
        chunk_count = rag.ingest_structured_chunks(
            user.id, resolved_course, chunks,
            filename=file.filename or "", source="upload",
        )
        if chunk_count == 0:
            chunk_count = rag.ingest_document_text(
                user.id, resolved_course, text, filename=file.filename, source="upload"
            )
    else:
        # graceful fallback to plain chunking when the LLM can't structure it
        resolved_course = course or "general"
        chunk_count = rag.ingest_document_text(
            user.id, resolved_course, text, filename=file.filename, source="upload"
        )
    if chunk_count == 0:
        raise HTTPException(status_code=400, detail="No readable text extracted from file")
    db.add(DocumentChunkRef(
        user_id=user.id, course=resolved_course, filename=file.filename or "",
        source="upload", chunk_count=chunk_count,
    ))
    db.commit()
    return {
        "ok": True,
        "course": resolved_course,
        "chunks": chunk_count,
        "structured": bool(chunks),
        "detected_type": detected.get("source_type") or "document",
    }