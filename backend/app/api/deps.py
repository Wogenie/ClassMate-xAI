"""Shared FastAPI dependencies."""
from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from .. import security


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Not authenticated")
    token = authorization.split(" ", 1)[1].strip()
    user_id = security.decode_access_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = db.query(User).filter_by(id=user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_settings(db: Session, user_id: int) -> None:
    from ..llm import get_groq_api_key, get_or_create_settings

    settings = get_or_create_settings(db, user_id)
    if not get_groq_api_key(db, user_id):
        raise HTTPException(
            status_code=400,
            detail="No Groq API key configured. Add it in Settings first.",
        )