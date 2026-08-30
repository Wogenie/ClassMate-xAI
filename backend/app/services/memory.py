"""Scoped adaptive memory: what the master agent has learned about the user.

Rules are stored per-user and injected into the master agent's system prompt.
They NEVER modify the global prompt file (as required by the spec).
"""
from sqlalchemy.orm import Session

from ..models import UserPreference


def add_rule(db: Session, user_id: int, kind: str, value: str) -> UserPreference:
    rule = UserPreference(user_id=user_id, kind=kind, value=value)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def list_rules(db: Session, user_id: int) -> list[UserPreference]:
    return (
        db.query(UserPreference)
        .filter_by(user_id=user_id)
        .order_by(UserPreference.created_at.desc())
        .all()
    )


def rules_text(db: Session, user_id: int) -> str:
    """Formatted bullet list for the system prompt."""
    rules = list_rules(db, user_id)
    if not rules:
        return "- Nothing learned yet. The classmate is still getting to know this student."
    lines = [f"- [{r.kind}] {r.value}" for r in rules]
    return "\n".join(lines)


def remember_from_statement(db: Session, user_id: int, statement: str) -> str:
    """Route a free-form teaching statement into a structured rule.

    Examples:
      "Alice is the lecturer"          -> trust
      "Don't trust Bob"                -> not_trust
      "When I say ML I mean Machine Learning" -> alias
      "Always show me deadlines first" -> priority
      "I don't want telegram notifications"    -> notif
    """
    s = statement.strip().lower()
    kind = "note"
    if "don't trust" in s or "do not trust" in s or "not the lecturer" in s or "not a teacher" in s:
        kind = "not_trust"
    elif "is the lecturer" in s or " is a teacher" in s or "is the ta" in s or "teaching assistant" in s or "is the rep" in s:
        kind = "trust"
    elif "i mean" in s or "means" in s:
        kind = "alias"
    elif "priorit" in s or "always show" in s or "first" in s and len(s.split()) < 20:
        kind = "priority"
    elif "notification" in s or "notify me" in s or "don't want" in s:
        kind = "notif"
    add_rule(db, user_id, kind, statement.strip())
    return kind