"""Schedule & schedule changes."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import academic
from .deps import get_current_user

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("")
def schedule(user=Depends(get_current_user), db: Session = Depends(get_db)):
    classes = academic.list_events(db, user.id, etype="class", limit=200)
    changes = academic.list_events(db, user.id, etype="schedule_change", limit=100)
    return {
        "classes": [academic._serialize(c) for c in classes],
        "changes": [academic._serialize(c) for c in changes],
    }