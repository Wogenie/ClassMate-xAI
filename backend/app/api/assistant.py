"""AI Assistant: conversational endpoint grounded in the student's data."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import llm as llm_service
from ..agent import graph as agent
from ..database import get_db
from ..schemas import ChatRequest
from .deps import get_current_user

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("/models")
def models():
    """The Groq models the student can pick from in the Assistant chat."""
    from .. import config

    default = config.DEFAULT_LLM_MODEL
    if default not in config.LLM_MODEL_CHOICES:
        default = config.LLM_MODELS[0] if config.LLM_MODELS else ""
    return {
        "default": default,
        "models": [
            {"id": mid, "name": name, "default": mid == default}
            for mid, name in config.LLM_MODEL_CHOICES.items()
        ],
    }


@router.post("/chat")
def chat(body: ChatRequest, user=Depends(get_current_user),
         db: Session = Depends(get_db)):
    llm_service.get_or_create_settings(db, user.id)
    reply = agent.answer(db, user.id, body.message,
                         history=body.history or None, model=body.model or None)
    return {"reply": reply}


@router.get("/history")
def history(user=Depends(get_current_user), db: Session = Depends(get_db)):
    return agent.recent_history(db, user.id)


@router.delete("/history")
def clear_history(user=Depends(get_current_user), db: Session = Depends(get_db)):
    removed = agent.clear_history(db, user.id)
    return {"cleared": removed}
