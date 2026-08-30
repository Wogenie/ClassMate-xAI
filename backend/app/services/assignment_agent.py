"""Assignment Understanding Agent.

Implements "assignment prompt.txt":
  - structured analysis of an assignment from whatever sources exist
    (Telegram announcement, surrounding messages, uploaded documents,
    student answers, course outline, course RAG)
  - dynamic clarification: generate ONLY the questions that materially reduce
    uncertainty — never a fixed list, never repeats what a document already says
  - student answer processing that updates the understanding and REGENERATES the
    AI summary (the original announcement is preserved untouched)
  - uploaded documents enrich the EXISTING assignment (no duplicate records)
  - feasibility analysis that GATES automatic solving until enough is known

Nothing here is hardcoded: course, topics, requirements and deadlines all come
from the available sources. The LLM only states what the sources support.
"""
import json
import logging
import re
from datetime import datetime, timezone

log = logging.getLogger("classmate.assignment_agent")

UNDERSTANDING_STATUS = {"sufficient", "partially_understood", "insufficient_information"}
FEASIBILITY = {"ready", "partially_ready", "needs_information",
               "requires_external_tool", "requires_student_action"}

UNDERSTANDING_TEXT = {
    "sufficient": "Understood",
    "partially_understood": "Partially understood",
    "insufficient_information": "Missing information",
}


# ------------------------------------------------------------------ the LLM

def _llm(db, user_id):
    from .. import llm as llm_service

    return llm_service.get_llm(db, user_id)


def _invoke_json(llm, prompt: str) -> dict | None:
    from langchain_core.messages import HumanMessage

    try:
        res = llm.invoke([HumanMessage(content=prompt)])
        raw = (res.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw[raw.index("{"):])
    except Exception as exc:  # noqa: BLE001
        log.warning("Assignment LLM call failed: %s", exc)
        return None


# ------------------------------------------------------------- source build

def _source_bundle(db, user_id: int, row, document_text: str = "") -> dict:
    """Assemble every available source for an assignment."""
    from ..services import academic
    from ..knowledge import rag as rag_mod
    from ..models import SourcePool

    # 1) the original announcement (kept as-is, never overwritten)
    message = (row.description or "").strip() or (row.title or "").strip()

    # 2) recent Telegram messages (the conversation around the announcement)
    rows = (
        db.query(SourcePool)
        .filter_by(user_id=user_id)
        .order_by(SourcePool.id.desc())
        .limit(30)
        .all()
    )
    msgs = [f"[{s.sender_name or 'student'}] {s.text}" for s in reversed(rows) if (s.text or "").strip()]

    # 3) course outline (ingested courses + lecture topics)
    outline = []
    for e in academic.list_events(db, user_id, etype="course", limit=20) \
        + academic.list_events(db, user_id, etype="lecture_topic", limit=40):
        name = (e.topic or e.title or "").strip()
        if name and (not row.course or e.course.lower() == row.course.lower()):
            outline.append(name)

    # 4) course RAG on the assignment's own topics
    query = " ".join(filter(None, [row.course, row.title, message]))
    docs = rag_mod.search_with_meta(user_id, row.course, query or row.course, k=4)

    # 5) student answers from prior clarification rounds
    d = row.details or {}
    clar = d.get("clarification") or {}
    answers = clar.get("responses") or []

    # 6) previously uploaded documents (persisted text)
    stored_docs = [doc for doc in (d.get("documents") or []) if (doc.get("text") or "").strip()]

    if document_text.strip():
        stored_docs.append({"filename": "(just uploaded)", "text": document_text, "at": ""})

    return {
        "message": message,
        "messages": msgs,
        "outline": outline,
        "docs": [
            {"filename": s.get("filename") or s.get("chapter") or s.get("section") or "(course doc)",
             "text": s["content"]}
            for s in docs
        ],
        "answers": answers,
        "uploaded_docs": stored_docs,
    }


def _bundle_text(bundle: dict, budget: int = 8000) -> str:
    """Render the source bundle as prompt text, HARD-CAPPED so the LLM call
    stays small and never trips the token/rate limit (429). Sections are
    truncated to a few items, and the whole thing is clipped to `budget`
    characters with a note saying so."""
    lines = []
    if bundle["message"]:
        lines.append(f"=== ORIGINAL MESSAGE (from Telegram) ===\n{bundle['message']}")
    if bundle["messages"]:
        msgs = [m[:240] for m in bundle["messages"][-12:]]
        lines.append("=== RECENT TELEGRAM MESSAGES ===\n" + "\n".join(msgs))
    if bundle["outline"]:
        outline = [t[:120] for t in bundle["outline"]][:16]
        lines.append("=== COURSE OUTLINE ===\n" + "\n".join(outline))
    if bundle["answers"]:
        ans = "\n".join(
            f"[student] {(a.get('text') or '')[:300]}"
            for a in bundle["answers"] if a.get("text")
        )
        lines.append(f"=== STUDENT ANSWERS (given earlier) ===\n{ans}")
    if bundle["uploaded_docs"]:
        parts = []
        for doc in bundle["uploaded_docs"]:
            body = (doc.get("text") or "").strip()[:2500]
            if body:
                parts.append(f"--- {doc.get('filename')} ---\n{body}")
        if parts:
            lines.append("=== UPLOADED ASSIGNMENT DOCUMENTS ===\n" + "\n\n".join(parts[:3]))
    if bundle["docs"]:
        parts = [f"[{d['filename']}] {d['text'][:300]}" for d in bundle["docs"]]
        lines.append("=== COURSE MATERIALS (retrieved) ===\n" + "\n\n".join(parts))
    if not lines:
        return "(no sources available)"
    text = "\n\n".join(lines)
    if len(text) > budget:
        text = text[:budget] + "\n…(sources truncated to fit the token budget)"
    return text


# -------------------------------------------------------------- analysis

_ANALYZE_PROMPT = """You are the Assignment Understanding Agent for a university
student assistant. Your FIRST job is to UNDERSTAND the assignment — you do NOT
solve it yet.

Analyze ONLY what the available sources support. Never invent requirements,
deadlines, submission formats, software, objectives, or lecturer intent. When a
source establishes something, say so; otherwise mark it clearly.

=== ASSIGNMENT ===
Course: {course}
Title: {title}
Deadline: {deadline}

{SOURCES}

Reason about source priority: the assignment document/instructions outrank the
lecturer's announcement, which outranks supporting material, student guesses,
and course outline. If sources conflict, do NOT silently pick one — say so and
flag it in missing_information.

Return STRICT JSON only (no markdown):
{{
  "summary": "describe WHAT the project is and its technical content — the subject, the underlying concepts, and the design/analysis work involved. MUST be short: at most 3 short sentences (~2-3 lines). NEVER mention deadlines, due dates, submission format, or admin details.",
  "objective": "plain-language objective, or Not specified",
  "tasks": ["list", "of", "identified", "tasks"],
  "requirements": ["known", "requirements", "or", "constraints"],
  "required_topics": ["concepts", "/", "topics", "needed"],
  "required_tools": ["software", "/", "tools", "needed"],
  "expected_outputs": ["deliverables", "known"],
  "submission_requirements": ["submission", "files", "/", "formats"],
  "known_information": ["what the sources DO establish"],
  "missing_information": ["what is still unknown and matters"],
  "clarification_questions": ["only questions whose answers would materially improve understanding"],
  "understanding_status": "sufficient|partially_understood|insufficient_information",
  "feasibility_status": "ready|partially_ready|needs_information|requires_external_tool|requires_student_action",
  "sources_used": ["which sources informed which claims"]
}}

Rules:
- summary must DESCRIBE the project and its technical content. It must NOT
  mention deadlines, due dates, submission format, names of submission files, or
  any admin detail.
- summary must say CLEARLY when information is incomplete. Never overstate.
- understanding_status: judge whether the evidence is actually enough to
  understand the project — do not use a fixed rule (e.g. presence of a field).
- feasibility_status: "ready" if you could complete the intellectual work now;
  "needs_information" if critical info is missing; "requires_external_tool" if a
  tool you don't have is required; "requires_student_action" if the student must
  do something physical/offline first.
- Use empty arrays for lists with no known values; use "Not specified" for
  unknown scalar values. Do NOT fabricate any value.
"""


def _shorten_summary(text: str, max_sentences: int = 3, limit: int = 280) -> str:
    """Hard-cap a summary to ~2-3 lines: at most `max_sentences`, never more
    than `limit` characters."""
    t = (text or "").strip()
    if not t:
        return t
    out = ""
    for s in re.split(r"(?<=[.!?])\s+", t)[:max_sentences]:
        if out and (len(out) + len(s) + 1 > limit):
            break
        out = (out + " " + s).strip()
    return out or t[:limit]


def _short_blurb(message: str, limit: int = 160) -> str:
    """Short FIRST description of the project. Admin clauses (deadlines,
    submission notes) are dropped so the blurb is pure project/technical
    content, never 'Due Friday' wording."""
    t = message.strip()
    if not t:
        return "Assignment received."
    # keep only the descriptive sentences; drop ones that are pure admin
    sentences = re.split(r"(?<=[.!?])\s+", t)
    kept = [
        s for s in sentences
        if not re.match(
            r"(?i)^\s*(?:due|deadline|submission|submit|hand\sin|handed?\sin|by\s+\w+day(?:\s|,|$))\b[^.]*\.?",
            s.strip(),
        )
    ]
    t = " ".join(kept).strip()
    if not t:
        t = sentences[0].strip()
    for sep in (".", "!", "?"):
        idx = t.find(sep)
        if 0 < idx <= limit:
            return t[: idx + 1].strip()
    return (t[:limit] + "…").strip() if len(t) > limit else t


def instant_summary(db, user_id: int, row) -> dict:
    """Synchronous, zero-LLM first summary: the injected Telegram message is
    boiled down to a SHORT project description so the dashboard shows the point
    immediately. The understanding agent overwrites this with the full summary
    shortly after (analysis_source.status flips 'instant' -> 'full')."""
    d = row.details or {}
    if d.get("summary"):
        return d.get("understanding") or {}
    message = (row.description or "").strip()
    d["summary"] = _short_blurb(message) if message else ""
    d["understanding"] = {
        "summary": d["summary"],
        "objective": "Not specified",
        "tasks": [], "requirements": [], "required_topics": [],
        "required_tools": [], "expected_outputs": [],
        "submission_requirements": [],
        "known_information": [message[:200]] if message else [],
        "missing_information": [],
        "clarification_questions": [],
        "understanding_status": "insufficient_information",
        "feasibility_status": "needs_information",
        "sources_used": [],
        "instant": True,
    }
    d["analysis_source"] = {
        "status": "instant",
        "understanding_status": "insufficient_information",
        "feasibility_status": "needs_information",
        "at": datetime.now(timezone.utc).isoformat(),
    }
    row.details = d
    db.commit()
    db.refresh(row)
    return d["understanding"]


def analyze_assignment(db, user_id: int, row, document_text: str = "",
                       student_answer: str = "") -> dict:
    """Run one structured analysis pass and persist the updated understanding.

    Stores into row.details['understanding'] and REPLACES the AI summary
    (details['summary']). The original announcement (row.description) is never
    changed. Best-effort, never raises. Returns the understanding dict."""
    bundle = _source_bundle(db, user_id, row, document_text)
    if student_answer.strip():
        bundle["answers"] = bundle["answers"] + [{"text": student_answer, "at": ""}]

    llm = _llm(db, user_id)
    d = row.details or {}
    if llm is None:
        understanding = {
            "summary": (d.get("summary") or "").strip()
                       or (_short_blurb(row.description or "") if (row.description or "").strip() else ""),
            "objective": "Additional information required",
            "tasks": [], "requirements": [], "required_topics": [],
            "required_tools": [], "expected_outputs": [],
            "submission_requirements": [],
            "known_information": [], "missing_information": [],
            "clarification_questions": [],
            "understanding_status": "insufficient_information",
            "feasibility_status": "requires_student_action",
            "sources_used": [], "llm_unavailable": True,
        }
    else:
        prompt = _ANALYZE_PROMPT.format(
            course=row.course or "(unknown)",
            title=row.title or "Assignment",
            deadline=row.deadline or "Not specified",
            SOURCES=_bundle_text(bundle),
        )
        raw = _invoke_json(llm, prompt) or {}
        understanding = _normalize_understanding(raw, row)
        understanding["summary"] = _shorten_summary(understanding.get("summary", ""))
        if not (understanding.get("summary") or "").strip():
            # The LLM returned unusable output — never blank the summary.
            # Fall back to the previous summary, else to the announcement.
            understanding["summary"] = (
                (d.get("summary") or "").strip()
                or (_short_blurb(row.description or "") if (row.description or "").strip() else "")
            ) or "Assignment received."
            understanding["understanding_status"] = "insufficient_information"
            understanding["note"] = ("The model returned an unreadable response; "
                                     "showing the original announcement. Re-run analysis to retry.")

    # replace the mutable AI summary with the fresh one
    d["understanding"] = understanding
    d["summary"] = understanding.get("summary", "")
    d["analysis_source"] = {
        "status": "full",
        "understanding_status": understanding["understanding_status"],
        "feasibility_status": understanding["feasibility_status"],
        "sources_used": understanding.get("sources_used", []),
        "at": datetime.now(timezone.utc).isoformat(),
    }
    row.details = d
    db.commit()
    db.refresh(row)
    return understanding


def _normalize_understanding(raw: dict, row) -> dict:
    status = raw.get("understanding_status", "insufficient_information")
    if status not in UNDERSTANDING_STATUS:
        status = "insufficient_information"
    feas = raw.get("feasibility_status", "needs_information")
    if feas not in FEASIBILITY:
        feas = "needs_information"

    def _list(key):
        v = raw.get(key) or []
        return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else \
            ([str(v).strip()] if str(v).strip() and str(v).lower() not in ("not specified", "n/a") else [])

    return {
        "title": raw.get("title") or row.title or "Assignment",
        "course": raw.get("course") or row.course or "General",
        "description": raw.get("description") or row.description or "",
        "summary": (raw.get("summary") or "").strip(),
        "objective": (raw.get("objective") or "Not specified").strip(),
        "tasks": _list("tasks"),
        "requirements": _list("requirements"),
        "required_topics": _list("required_topics"),
        "required_tools": _list("required_tools"),
        "expected_outputs": _list("expected_outputs"),
        "submission_requirements": _list("submission_requirements"),
        "known_information": _list("known_information"),
        "missing_information": _list("missing_information"),
        "clarification_questions": _list("clarification_questions"),
        "understanding_status": status,
        "feasibility_status": feas,
        "sources_used": _list("sources_used"),
    }


# --------------------------------------------------------- clarify (dynamic)

_ASk_PROMPT = """You dynamically decide which questions to ask a student to
understand their assignment better. Inspect what is ALREADY known and what is
missing, then ask ONLY the questions that would materially reduce uncertainty.

=== KNOWN SO FAR ===
{understanding}

=== MISSING INFORMATION ===
{missing}

=== PREVIOUS QUESTIONS ALREADY ASKED (don't repeat) ===
{asked}

Return STRICT JSON:
{{
  "introduction": "one short friendly sentence acknowledging what you know",
  "questions": ["question1", "question2", "..."],
  "reason": "why these specific questions matter"
}}

Rules:
- Ask at most 5 questions.
- If a document already answers something, do NOT ask about it.
- If only one or two gaps exist, ask only those.
- If nothing critical is missing, questions may be an empty array — say so.
"""


def generate_questions(db, user_id: int, row) -> list[str]:
    """Generate the 'Ask Student About This Project' questions (dynamic)."""
    d = row.details or {}
    understanding = (d.get("understanding") or {})
    clar = d.get("clarification") or {}
    asked = []
    for q in clar.get("questions", []):
        if isinstance(q, dict):
            asked.append(q.get("text", ""))
        elif isinstance(q, str):
            asked.append(q)

    llm = _llm(db, user_id)
    if llm is None:
        return _fallback_questions(understanding)

    prompt = _ASk_PROMPT.format(
        understanding=_fmt_understanding(understanding),
        missing="\n".join(understanding.get("missing_information", [])) or "(none listed)",
        asked="\n".join(asked) or "(none)",
    )
    out = _invoke_json(llm, prompt) or {}
    questions = [str(q).strip() for q in out.get("questions", []) if str(q).strip()]

    # remember the asked questions so we don't repeat them next round
    clar = dict(clar)
    clar["asked_ats"] = clar.get("asked_ats", [])
    clar["asked_ats"].append({"questions": questions,
                              "at": datetime.now(timezone.utc).isoformat()})
    d["clarification"] = clar
    row.details = d
    db.commit()

    return questions if questions else _fallback_questions(understanding)


def _fallback_questions(understanding: dict) -> list[str]:
    """Non-LLM fallback when the key is missing: derived strictly from gaps."""
    missing = understanding.get("missing_information") or []
    if missing:
        return missing[:5]
    return ["Do you have an assignment PDF, Word document, image, or other project instructions?"]


# ----------------------------------------------------------- student answers

_ANSWER_PROMPT = """You process what a student told you about an assignment and
update the current understanding.

=== CURRENT UNDERSTANDING ===
{current}

=== STUDENT'S ANSWER ===
{answer}

Return STRICT JSON:
{{
  "new_information": ["facts the answer adds that were not known"],
  "interpretation_note": "anything in the answer that is a student guess rather than confirmed fact",
  "updated_summary": "regenerated student-friendly summary of what the assignment asks",
  "still_missing": ["remaining unknown items that still matter"]
}}

Rules:
- Distinguish confirmed information from student interpretation.
- Do not blindly trust ambiguous statements.
- Do not invent requirements the student did not state.
"""


def consume_answer(db, user_id: int, row, answer: str, group: bool = False) -> dict:
    """Process a student's answer, update the understanding, regenerate the
    summary, and report whether another clarification round is needed.

    When `group` is True the answer came from a Telegram group reply — the open
    round's state is left for the caller to record (who actually replied, etc.)."""
    d = row.details or {}
    clar = dict(d.get("clarification") or {})
    responses = list(clar.get("responses") or [])
    responses.append({
        "text": answer.strip(),
        "at": datetime.now(timezone.utc).isoformat(),
        "sender": "student" if not group else None,
    })
    if group:
        responses[-1].pop("sender", None)
    clar["responses"] = responses

    # a manual answer closes the open Telegram round (group replies are recorded
    # by the caller so we don't fabricate a 'web' sender here)
    if not group:
        go = clar.get("group_open") or {}
        if go and go.get("status") == "waiting":
            go["status"] = "answered"
            go["answers"] = list(go.get("answers") or [])
            go["answers"].append({
                "text": answer.strip()[:600],
                "sender": "web",
                "at": datetime.now(timezone.utc).isoformat(),
            })
            go["updated_at"] = datetime.now(timezone.utc).isoformat()
            clar["group_open"] = go

    d["clarification"] = clar
    row.details = d
    db.commit()

    understanding = (d.get("understanding") or {})
    llm = _llm(db, user_id)
    if llm is not None:
        out = _invoke_json(llm, _ANSWER_PROMPT.format(
            current=_fmt_understanding(understanding),
            answer=answer,
        )) or {}
        updated_summary = (out.get("updated_summary") or "").strip()
    else:
        out = {}
        updated_summary = understanding.get("summary", "")

    # full re-analysis now includes the new answer as a source
    new_understanding = analyze_assignment(db, user_id, row, student_answer=answer)

    more_needed = new_understanding.get("understanding_status") == "insufficient_information"
    more_questions = generate_questions(db, user_id, row) if more_needed else []

    return {
        "summary": new_understanding.get("summary") or updated_summary,
        "understanding": new_understanding,
        "more_information_needed": more_needed,
        "clarification_questions": more_questions,
        "new_information": out.get("new_information", []),
        "interpretation_note": out.get("interpretation_note", ""),
    }


# ------------------------------------------------------------- documents

def feed_document(db, user_id: int, row, filename: str, text: str) -> dict:
    """Enrich the EXISTING assignment with an uploaded document."""
    from ..knowledge import rag as rag_mod
    from ..models import DocumentChunkRef

    d = row.details or {}
    docs = list(d.get("documents") or [])
    docs.append({
        "filename": filename,
        "text": text[:20000],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    d["documents"] = docs
    row.details = d
    db.commit()

    # make the document retrievable for course RAG (best-effort)
    try:
        course = row.course or "General"
        chunk_count = rag_mod.ingest_document_text(
            user_id, course, text, filename=filename, source="assignment_upload"
        )
        db.add(DocumentChunkRef(
            user_id=user_id, course=course, filename=filename,
            source="assignment_upload", chunk_count=chunk_count,
        ))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("assignment doc RAG ingest failed user=%s: %s", user_id, exc)

    understanding = analyze_assignment(db, user_id, row, document_text=text)
    return {"understanding": understanding, "summary": understanding.get("summary", "")}


# --------------------------------------------------- ask the group + answers

_GROUP_ASK_TEXT = (
    "Hi everyone — I'm trying to describe the project **{title}** "
    "for **{course}** accurately. "
    "Please reply to this message with what you know about the questions below.\n\n{questions}\n"
    "_(Only answers relevant to this project are recorded.)_"
)

_JUDGE_PROMPT = """You watch a university group chat. One of these assignments is
currently WAITING for the class to answer the numbered questions that were posted:

{assignments}

The NEW group message is:

[sender: {sender}]
{message}

Your job: decide whether this message is a GENUINE answer to one of the waiting
questions — NOT just other group chatter, NOT just naming a subject, NOT an
unrelated announcement.

A genuine answer gives real details about what the project actually asks
(requirements, deliverables, constraints, objective). A message that merely
mentions the course, says a subject name, talks about a lecture, agrees without
details, or is about anything unrelated is NOT an answer.

When the message IS an answer, extract ONLY the factual part that answers the
questions — strip out the subject name, greetings, back-and-forth, and any
unrelated details. The student's reply may contain other subjects and noise; you
must figure out what is actually the reply.

Return STRICT JSON:
{{
  "is_answer": true or false,
  "assignment_index": 0-based index of the assignment being answered (omit when false),
  "answered_questions": [indices of the questions it answers],
  "extracted_answer": "only the answer content, cleaned of subject/noise (omit when false)",
  "confidence": "high|medium|low",
  "reason": "one short sentence"
}}"""


def _broadcast_questions(db, user_id: int, row, questions: list[str]) -> tuple[bool, str, int | None]:
    """Send the clarification questions to the school group via the user's bot.
    Returns (sent, chat, telegram_message_id)."""
    from .. import looputil, llm as llm_service
    from ..services import academic
    from ..telegram.bot_manager import send_message

    settings = llm_service.get_decrypted_settings(db, user_id)
    chat = academic.resolve_group(db, user_id, fallback=settings.get("target_chat", ""))
    if not chat:
        return False, "", None
    numbered = "\n".join(f"{i + 1}) {q}" for i, q in enumerate(questions))
    text = _GROUP_ASK_TEXT.format(
        title=row.title or row.course or "this project",
        course=row.course or "your course",
        questions=numbered,
    )
    try:
        msg_id = looputil.run_coro(send_message(user_id, chat, text), timeout=20.0)
        return bool(msg_id), chat, msg_id
    except Exception as exc:  # noqa: BLE001
        log.warning("assignment group broadcast failed user=%s: %s", user_id, exc)
        return False, "", None


def ask_group_details(db, user_id: int, row) -> dict:
    """POST /assignments/{id}/ask: generate the dynamic clarification questions
    AND broadcast them to the students' Telegram group so their replies can be
    picked up. Returns {'sent', 'chat', 'questions'}."""
    questions = generate_questions(db, user_id, row)
    d = row.details or {}
    clar = dict(d.get("clarification") or {})
    previous = clar.get("group_open") or {}
    clar["group_open"] = {
        "questions": questions,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "status": "waiting",
        "answers": list(previous.get("answers") or []),
    }
    d["clarification"] = clar
    row.details = d
    db.commit()

    sent, chat, msg_id = False, "", None
    if questions:
        sent, chat, msg_id = _broadcast_questions(db, user_id, row, questions)
        d = row.details or {}
        go = d["clarification"].get("group_open") or {}
        go["sent"] = bool(sent)
        go["chat"] = chat
        if msg_id is not None:
            go["telegram_message_id"] = msg_id
        d["clarification"]["group_open"] = go
        row.details = d
        db.commit()

    db.refresh(row)
    return {"sent": sent, "chat": chat, "questions": questions}


def _notify_group_answered(db, user_id: int, row, sender_name: str) -> None:
    from ..services import notifier

    try:
        notifier.push(
            db, user_id, "assignment",
            f"💬 Group answered: {row.title or row.course or 'assignment'}",
            f"An answer from “{sender_name}” was added to the assignment — "
            "the project summary has been updated on the dashboard.",
            related_id=row.id, tg_send=False,
        )
    except Exception:  # noqa: BLE001
        pass


def handle_group_message(db, user_id: int, sender_name: str, text: str,
                         thread_id: str = "") -> bool:
    """Incoming group message: judge whether it is a genuine answer to a
    currently-open 'Ask details' round, then consume it into the dashboard.
    Returns True when an assignment's understanding/summary was updated.

    Acceptance is sender-agnostic — ANY group member's reply is eligible. A
    reply that Telegram marks as a reply to our broadcast matches by message id
    (thread_id). If the judge LLM is unavailable (rate limit / API down) the
    reply is NOT dropped: it is recorded on the matched/likeliest round as
    pending so it shows in the dashboard box and is resolved by later analysis."""
    from ..models import AcademicEvent

    text = (text or "").strip()
    if not text:
        return False

    waiting = []
    for row in db.query(AcademicEvent).filter_by(user_id=user_id, type="assignment").all():
        clar = (row.details or {}).get("clarification") or {}
        go = clar.get("group_open") or {}
        if go.get("status") == "waiting" and go.get("questions"):
            waiting.append((row, go))
    if not waiting:
        return False

    # Does Telegram say this message is a reply to one of our broadcasts?
    own_thread = ""
    if thread_id:
        tid = str(thread_id)
        for row, go in waiting:
            if str(go.get("telegram_message_id") or "") == tid:
                own_thread = tid
                break

    llm = _llm(db, user_id)
    if llm is None:
        return _heuristic_group_hit(db, user_id, waiting, sender_name, text)

    blocks = []
    for idx, (row, go) in enumerate(waiting):
        qs = "\n".join(f"{j + 1}) {q}" for j, q in enumerate(go["questions"]))
        blocks.append(
            f"[{idx}] {row.course or 'course'} · {row.title or 'project'}\n"
            f"    current project summary: {(row.details or {}).get('summary', '')[:200]}\n"
            f"    waiting questions:\n{qs}"
        )
    prompt = _JUDGE_PROMPT.format(
        assignments="\n\n".join(blocks),
        sender=sender_name or "student",
        message=text[:2500],
    )
    out = _invoke_json(llm, prompt)

    row = go = None
    extracted = ""
    verified = False
    answers_done: list[int] = []
    confidence = ""

    idx = out.get("assignment_index") if out else None
    if out and out.get("is_answer") is True and isinstance(idx, int) and 0 <= idx < len(waiting):
        row, go = waiting[idx]
        extracted = (out.get("extracted_answer") or text)[:600].strip() or text[:600]
        answers_done = [q for q in (out.get("answered_questions") or []) if isinstance(q, int)]
        confidence = out.get("confidence", "")
        verified = True
    elif not out and len(text) >= 8:
        # judge failed (rate limit / API down): never drop a possible reply.
        if own_thread:
            for r, g in waiting:
                if str(g.get("telegram_message_id") or "") == own_thread:
                    row, go = r, g
                    break
        if row is None:
            if len(waiting) == 1:
                row, go = waiting[0]
            else:
                import re as _re
                words = set(_re.findall(r"[a-z0-9]{3,}", text.lower()))
                best_row, best_go, best_score = None, None, 0.0
                for r, g in waiting:
                    terms = " ".join(g["questions"] + [r.title or "", r.course or ""])
                    ti = set(_re.findall(r"[a-z0-9]{3,}", terms.lower()))
                    score = len(words & ti) / max(1, len(ti))
                    if score > best_score:
                        best_score, best_row, best_go = score, r, g
                if best_row is not None and best_score > 0.0:
                    row, go = best_row, best_go
                else:
                    # nothing overlaps: accept onto the round asked most recently —
                    # generous capture during an outage; the judge verifies properly
                    # once the API recovers.
                    row, go = max(waiting, key=lambda rg: (rg[1].get("sent_at") or ""))
        if row is not None:
            extracted = text[:600]
            verified = False

    if row is None:
        return False

    # consume into the understanding/summary (best-effort: falls back to the
    # previous summary when the LLM is rate-limited) and record the reply on the
    # assignment so it is visible in the dashboard box either way.
    try:
        consume_answer(db, user_id, row, extracted, group=True)
    except Exception as exc:  # noqa: BLE001
        log.warning("assignment answer consume failed user=%s: %s", user_id, exc)

    d = row.details or {}
    clar = d.get("clarification") or {}
    go2 = clar.get("group_open") or {}
    go2 = dict(go2)
    go2["pending_answers"] = list(go2.get("pending_answers") or [])
    go2["pending_answers"].append({
        "text": text[:600],
        "sender": sender_name or "student",
        "verified": bool(verified),
        "at": datetime.now(timezone.utc).isoformat(),
    })
    go2["answers"] = list(go2.get("answers") or [])
    go2["answers"].append({
        "text": extracted or text[:600],
        "original": text[:600],
        "sender": sender_name or "student",
        "answered_questions": answers_done,
        "confidence": confidence,
        "verified": bool(verified),
        "at": datetime.now(timezone.utc).isoformat(),
    })
    go2["updated_at"] = datetime.now(timezone.utc).isoformat()
    if verified:
        go2["status"] = "answered"
    clar = dict(clar)
    clar["group_open"] = go2
    d["clarification"] = clar
    row.details = d
    db.commit()
    db.refresh(row)

    _notify_group_answered(db, user_id, row, sender_name)
    return True


def _heuristic_group_hit(db, user_id: int, waiting: list, sender_name: str, text: str) -> bool:
    """No-LLM fallback: crude word-overlap gate against the waiting questions.
    Only accepts a hit when the message clearly shares the question's terms."""
    import re

    words = set(re.findall(r"[a-z0-9]{3,}", text.lower()))
    best, best_row, best_score = None, None, 0.0
    for row, go in waiting:
        terms = " ".join(go["questions"] + [row.title or "", row.course or ""])
        ti = set(re.findall(r"[a-z0-9]{3,}", terms.lower()))
        overlap = len(words & ti) / max(1, len(ti))
        if overlap > 0.35 and overlap > best_score:
            best_score, best_row, best = overlap, row, go
    if best_row is None or len(text) < 5:
        return False
    consume_answer(db, user_id, best_row, text[:600], group=True)
    d = best_row.details or {}
    go = (d.get("clarification") or {}).get("group_open") or {}
    go["status"] = "answered"
    go["answers"] = list(go.get("answers") or [])
    go["answers"].append({"text": text[:600], "sender": sender_name or "student",
                          "at": datetime.now(timezone.utc).isoformat()})
    d["clarification"]["group_open"] = go
    best_row.details = d
    db.commit()
    _notify_group_answered(db, user_id, best_row, sender_name)
    return True


# ------------------------------------------------------- solving gate

def should_solve(understanding: dict) -> tuple[bool, str]:
    """Whether automatic solving may start, per the spec's 'only proceed when
    sufficiently understood' rule. Manual solving is always allowed."""
    status = understanding.get("understanding_status", "insufficient_information")
    feas = understanding.get("feasibility_status", "needs_information")
    if status == "insufficient_information" or feas == "needs_information":
        return False, (
            "Not solving yet — critical assignment details are missing. "
            "Upload the assignment document or answer the clarification questions first."
        )
    if feas == "requires_student_action":
        return False, "This assignment requires an offline/physical step by you before it can be solved."
    return True, ""


# ------------------------------------------------------------- helpers

def _fmt_understanding(u: dict) -> str:
    parts = [f"Summary: {u.get('summary', '')}"]
    if u.get("objective"):
        parts.append(f"Objective: {u['objective']}")
    for key, label in (
        ("tasks", "Tasks"),
        ("requirements", "Requirements"),
        ("required_tools", "Required tools"),
        ("expected_outputs", "Expected outputs"),
        ("submission_requirements", "Submission"),
        ("required_topics", "Required topics"),
    ):
        items = u.get(key) or []
        if items:
            parts.append(f"{label}: " + "; ".join(items))
    if u.get("missing_information"):
        parts.append("Missing: " + "; ".join(u["missing_information"]))
    return "\n".join(parts)


# ------------------------------------------------- background analyses

# In-flight analyses so repeated API hits / scheduler sweeps never queue up
# duplicate (CPU-heavy, on-device embedding) jobs for the same assignment.
_ANALYSIS_INFLIGHT: set[int] = set()


def _needs_analysis(row, allow_fallback: bool) -> bool:
    """Whether this assignment should be (re)analyzed.

    allow_fallback=False  → only when there is NO summary at all (cheap GET path).
    allow_fallback=True   → also re-analyze rows whose summary is still just the
                            raw announcement/title (LLM 'full' status), but never
                            more often than config.ANALYSIS_COOLDOWN_SECONDS.
    """
    d = row.details or {}
    s = (d.get("summary") or "").strip()
    if not s:
        return True
    if not allow_fallback:
        return False
    raw = (row.description or "").strip() or (row.title or "").strip()
    is_fallback = bool(s) and s in (raw, (row.title or "").strip())
    is_full = (d.get("analysis_source") or {}).get("status") == "full"
    if not (is_fallback and is_full):
        return False
    at = (d.get("analysis_source") or {}).get("at")
    if at:
        from .. import config

        try:
            last = datetime.fromisoformat(at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - last).total_seconds() < config.ANALYSIS_COOLDOWN_SECONDS:
                return False
        except Exception:  # noqa: BLE001
            pass
    return True


def _analyze_one(user_id: int, event_id: int, allow_fallback: bool) -> None:
    if event_id in _ANALYSIS_INFLIGHT:
        return
    _ANALYSIS_INFLIGHT.add(event_id)
    from ..database import SessionLocal
    from ..models import AcademicEvent

    s = SessionLocal()
    try:
        row = (
            s.query(AcademicEvent)
            .filter_by(id=event_id, user_id=user_id, type="assignment")
            .first()
        )
        if row is None or not _needs_analysis(row, allow_fallback):
            return
        analyze_assignment(s, user_id, row)
    except Exception:  # noqa: BLE001
        log.debug("analysis failed event=%s", event_id, exc_info=True)
    finally:
        s.close()
        _ANALYSIS_INFLIGHT.discard(event_id)


def kick_pending_analyses(user_id: int) -> None:
    """Very cheap hook for the request layer: analyze only assignments that have
    NO summary at all, deduped so repeated GETs / 6s polling never pile up work."""
    from ..database import SessionLocal
    from ..models import AcademicEvent

    db = SessionLocal()
    pending = []
    try:
        rows = db.query(AcademicEvent).filter_by(user_id=user_id, type="assignment").all()
        for r in rows:
            if _needs_analysis(r, allow_fallback=False) and r.id not in _ANALYSIS_INFLIGHT:
                pending.append(r.id)
    finally:
        db.close()
    if not pending:
        return
    import threading

    def _run():
        for rid in pending:
            _analyze_one(user_id, rid, False)

    threading.Thread(target=_run, daemon=True).start()


def sweep_pending_analyses() -> int:
    """Periodic scheduler job: catch any assignment still missing a summary plus
    fallback rows (respecting the cooldown). Returns how many were analyzed."""
    from ..database import SessionLocal
    from ..models import AcademicEvent

    db = SessionLocal()
    runs: list[tuple[int, int]] = []
    try:
        users = [
            uid for (uid,) in
            db.query(AcademicEvent.user_id).filter(AcademicEvent.type == "assignment").distinct().all()
        ]
        for uid in users:
            rows = db.query(AcademicEvent).filter_by(user_id=uid, type="assignment").all()
            for r in rows:
                if _needs_analysis(r, allow_fallback=True) and r.id not in _ANALYSIS_INFLIGHT:
                    runs.append((uid, r.id))
    finally:
        db.close()
    for uid, rid in runs:
        _analyze_one(uid, rid, True)
    return len(runs)