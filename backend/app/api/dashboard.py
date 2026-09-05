"""Dashboard & overview endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import academic
from .deps import get_current_user

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/overview")
def overview(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return academic.overview(db, user.id)


@router.get("/dashboard/progress")
def progress(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return academic.progress_summary(db, user.id)


@router.get("/dashboard/inbox")
def inbox(user=Depends(get_current_user), db: Session = Depends(get_db)):
    """Unified message inbox grouped into assignment / exam / other."""
    return academic.list_inbox(db, user.id)