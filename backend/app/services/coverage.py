"""Dynamic Quiz Coverage Detection pipeline.

Implements the "../../txt 3.txt" concept:
  - classify whether a quiz/exam coverage is EXPLICIT, INFERRED, or AMBIGUOUS
  - when ambiguous, generate DYNAMIC clarification options from the indexed
    course materials (never hardcoded)
  - extract structured coverage + topics via LLM, grounded in source-aware RAG
  - resolve student responses into a consensus (never auto-promoting student
    consensus to official confirmation)

Everything (course, chapter, section, topic, portion) is discovered from the
message + conversation + vector retrieval — there are ZERO hardcoded academic
facts in this module.
"""
import json
import logging
from datetime import date, datetime, timezone

log = logging.getLogger("classmate.coverage")

ALLOWED_STATUS = {"EXPLICIT", "INFERRED", "AMBIGUOUS"}


# ------------------------------------------------------------------ storage

def _details(row) -> dict:
    return row.details or {}


def get_coverage(row) -> dict:
    d = _details(row)
    cov = d.get("coverage") or {}
    cov.setdefault("status", d.get("coverage_status", ""))
    cov.setdefault("confidence", d.get("coverage_confidence", ""))
    cov.setdefault("requires_clarification", d.get("requires_clarification", False))
    cov.setdefault("evidence", d.get("coverage_evidence", ""))
    cov.setdefault("clarification", d.get("clarification") or {"asked": False, "options": [], "question": ""})
    cov.setdefault("student_responses", d.get("student_responses") or [])
    cov.setdefault("topics", d.get("topics") or [])
    cov.setdefault("course", row.course)
    cov.setdefault("chapter", d.get("coverage_chapter", ""))
    return cov


def save_coverage(db, row, payload: dict) -> dict:
    """Merge a coverage payload into the event's details JSON."""
    d = row.details or {}
    for key in ("coverage_status", "coverage_confidence", "coverage_evidence",
                "requires_clarification", "coverage_chapter", "topics",
                "clarification", "student_responses", "coverage"):
        if key in payload and payload[key] is not None:
            d[key] = payload[key]
    row.details = d
    db.commit()
    db.refresh(row)
    return d


def is_quiz_or_exam(row) -> bool:
    return row.type in ("quiz", "exam")


# ------------------------------------------------------------- classification

def classify_coverage(state: dict) -> str:
    """Map a resolution state onto one of EXPLICIT / INFERRED / AMBIGUOUS.

    state contains optional booleans: message_clear, has_official, has_consensus,
    has_retrieved_evidence, conflicts.
    """
    if state.get("message_clear") or state.get("has_official"):
        return "EXPLICIT"
    if state.get("conflicts"):
        return "AMBIGUOUS"
    if state.get("has_consensus") or state.get("has_retrieved_evidence"):
        return "INFERRED"
    return "AMBIGUOUS"


def confidence_label(row, status: str) -> str:
    """Evidence-aware confidence label (sec 9)."""
    if status == "EXPLICIT":
        return "HIGH"
    d = row.details or {}
    responses = d.get("student_responses") or []
    conflicts = len({r.get("text", "").strip() for r in responses if r.get("text")}) > 1
    if conflicts:
        return "AMBIGUOUS"
    if responses:
        return "MEDIUM"
    if d.get("topics"):
        return "MEDIUM"
    return "LOW"


# ------------------------------------------------------------------ the LLM

def _llm(db, user_id):
    from .. import llm as llm_service

    return llm_service.get_llm(db, user_id)


_COVERAGE_PROMPT = """You resolve the COVERAGE (portion) of a quiz/exam for a
university student. Everything (course, chapter, coverage, topics) must be
derived from the message + conversation + retrieved course materials. There are
NO predefined courses or chapters.

=== ORIGINAL MESSAGE ===
{message}

=== CONVERSATION CONTEXT (recent) ===
{context}

=== RETRIEVED COURSE MATERIALS (source-aware) ===
{sources}

Determine:
1. course: the best-resolved course name (empty if unknown).
2. Whether the coverage/portion is EXPLICIT (clearly stated), INFERRED (must be
   reconstructed from evidence), or AMBIGUOUS (multiple plausible portions, can't
   safely choose).
3. coverage bounds {{start, end, sections[]}} when determinable.
4. topics[] the quiz likely covers, each with a SHORT plain-English description
   grounded in the retrieved material, and source_references (the chapter/section
   /filename of the chunk it came from).

Return STRICT JSON only (no markdown):
{{
  "course": "",
  "coverage_status": "EXPLICIT|INFERRED|AMBIGUOUS",
  "coverage": {{"start": "", "end": "", "sections": []}},
  "topics": [{{"name": "", "description": "", "source_references": []}}],
  "evidence": "announcement|outline|chapter_materials|student_consensus",
  "requires_clarification": true|false,
  "reason": "short why this status"
}}

Rules:
- NEVER fabricate coverage. If unsure, use AMBIGUOUS + requires_clarification true.
- If only a topic name is known and no portion, AMBIGUOUS is appropriate ONLY when
  multiple distinct portions are plausible; otherwise INFERRED is fine.
- Keep topic descriptions short (1-2 sentences).
"""

_CLARIFY_PROMPT = """Given the context and retrieved course materials below, ask
the group a short clarifying question about which PORTION a quiz/exam will cover,
and provide 3-5 CONCRETE options generated from the retrieved material structure
(chapters / sections / topics that actually exist in the materials).

=== ORIGINAL MESSAGE ===
{message}

=== RETRIEVED MATERIALS ===
{sources}

Return STRICT JSON:
{{
  "question": "<short question>",
  "options": ["", "", ""]
}}
Options must be real, distinct pieces of the course material (e.g. "Chapter 2:
Semiconductor Diodes", "Rectifiers & Filters"), never generic filler.
"""

_RESPONSE_PROMPT = """You analyze student responses about what a quiz/exam will
cover. Determine whether there is a CONSISTENT CONSENSUS.

=== QUESTION ===
{question}

=== RESPONSES (sender: text) ===
{responses}

Return STRICT JSON:
{{
  "consensus": true|false,
  "coverage": {{"start": "", "end": "", "sections": []}},
  "topics": [{{"name": "", "description": "", "source_references": []}}],
  "evidence_authority": "official|instructor|documentation|student_consensus|none",
  "reason": "short explanation"
}}

Rules:
- Consensus only when responses AGREE on the coverage.
- evidence_authority reflects the SOURCE of the answers (student replies are
  "student_consensus"; only an instructor/official message can be "official").
- If contradictory, consensus=false and coverage empty.
"""


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
        log.warning("Coverage LLM call failed: %s", exc)
        return None


def detect_coverage(db, user_id: int, row, message_text: str, context: list[str]) -> dict:
    """Run coverage extraction for a quiz/exam event. Best-effort; never raises."""
    from ..knowledge import rag as rag_mod

    llm = _llm(db, user_id)
    if llm is None:
        return _empty_state()

    # source-aware retrieval on the quiz's own course (dynamic, no hardcoding)
    sources = rag_mod.search_all_courses_with_meta(user_id, message_text, k_per_course=4)
    sources_text = _format_sources(sources)
    ctx = "\n".join(context[-8:]) if context else "(none)"

    prompt = _COVERAGE_PROMPT.format(message=message_text, context=ctx, sources=sources_text)
    out = _invoke_json(llm, prompt) or {}

    status = out.get("coverage_status", "AMBIGUOUS")
    if status not in ALLOWED_STATUS:
        status = classify_coverage({
            "message_clear": out.get("coverage_status") == "EXPLICIT",
            "conflicts": False,
            "has_retrieved_evidence": bool(sources),
        })
    cov = out.get("coverage") or {}
    cov.setdefault("start", "")
    cov.setdefault("end", "")
    cov.setdefault("sections", [])
    topics = [t for t in (out.get("topics") or []) if isinstance(t, dict) and t.get("name")]

    state = {
        "course": out.get("course", ""),
        "coverage_status": status,
        "coverage": cov,
        "topics": topics,
        "evidence": out.get("evidence", "chapter_materials"),
        "requires_clarification": bool(out.get("requires_clarification", status == "AMBIGUOUS")),
        "reason": out.get("reason", ""),
        "sources": sources,
    }
    return state


# ------------------------------------------------------------------ clarify

def build_clarification(db, user_id: int, row, message_text: str) -> dict:
    """Generate DYNAMIC clarification options from the retrieved materials."""
    from ..knowledge import rag as rag_mod

    llm = _llm(db, user_id)
    cover = get_coverage(row)
    existing = cover.get("clarification") or {}
    if existing.get("options"):
        return existing

    sources = rag_mod.search_all_courses_with_meta(user_id, message_text, k_per_course=4)
    sources_text = _format_sources(sources)
    prompt = _CLARIFY_PROMPT.format(message=message_text, sources=sources_text)
    out = _invoke_json(llm, prompt) or {}
    options = [o for o in (out.get("options") or []) if isinstance(o, str) and o.strip()]
    question = out.get("question") or (
        "Which portion will the quiz/exam cover? The announcement didn't specify it clearly."
    )
    clarification = {
        "question": question,
        "options": options,
        "asked": True,
    }
    save_coverage(db, row, {"clarification": clarification})
    return clarification


def add_student_response(db, row, text: str, sender: str = "") -> dict:
    """Record a student's clarification answer (sec 4)."""
    d = row.details or {}
    responses = d.get("student_responses") or []
    entry = {
        "text": (text or "").strip(),
        "sender": sender or "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    responses.append(entry)
    d["student_responses"] = responses
    row.details = d
    db.commit()
    db.refresh(row)
    return entry


def resolve_from_responses(db, user_id: int, row) -> dict:
    """Emit a coverage resolution once responses exist (sec 4 consensus)."""
    llm = _llm(db, user_id)
    d = row.details or {}
    responses = d.get("student_responses") or []
    if not responses:
        return {"consensus": False, "reason": "no responses yet"}

    if llm is None:
        return {"consensus": False, "reason": "no LLM"}

    question = (d.get("clarification") or {}).get("question", "")
    resp_lines = "\n".join(f"{r.get('sender') or 'student'}: {r.get('text')}" for r in responses)
    prompt = _RESPONSE_PROMPT.format(question=question, responses=resp_lines)
    out = _invoke_json(llm, prompt) or {}

    consensus = bool(out.get("consensus"))
    if consensus:
        authority = out.get("evidence_authority", "student_consensus")
        # Never promote student consensus to official confirmation.
        evidence = "student_consensus" if authority in ("student_consensus", "none", "") else authority
        status = "EXPLICIT" if authority in ("official", "instructor", "documentation") else "INFERRED"
        cov = out.get("coverage") or {k: [] if k == "sections" else "" for k in ("start", "end", "sections")}
        topics = [t for t in (out.get("topics") or []) if isinstance(t, dict) and t.get("name")]
        save_coverage(db, row, {
            "coverage_status": status,
            "coverage": cov,
            "topics": topics,
            "coverage_evidence": evidence,
            "requires_clarification": False,
        })
    return {
        "consensus": consensus,
        "coverage_status": get_coverage(row).get("status"),
        "reason": out.get("reason", ""),
    }


# -------------------------------------------------- ask the group (poll)

def ask_group_in_background(db, user_id: int, event_id: int, message_text: str = "") -> bool:
    """If a quiz/exam has AMBIGUOUS coverage and no clarifying poll was sent yet,
    schedule a native Telegram poll to the school group with the dynamic options
    (generated from the course materials). No-op when the bot/group is offline —
    the dashboard's manual options remain the fallback."""
    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
    if row is None or row.type not in ("quiz", "exam"):
        return False
    text = message_text or row.description or row.title or ""
    clar = build_clarification(db, user_id, row, text)
    if not clar or not (clar.get("options") or []) or clar.get("poll_id"):
        return False
    from .. import looputil

    looputil.call_coro(_ask_group_poll(user_id, event_id))
    return True


async def _ask_group_poll(user_id: int, event_id: int) -> None:
    """Post the pending clarification as a poll on the bot loop (own DB session)."""
    from ..database import SessionLocal
    from ..telegram import polling as polling_mod

    db = SessionLocal()
    try:
        row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
        if row is None or row.type not in ("quiz", "exam"):
            return
        clar = get_coverage(row).get("clarification") or {}
        opts = clar.get("options") or []
        if not opts or clar.get("poll_id"):
            return
        question = clar.get("question") or (
            "Which portion will the quiz/exam cover? The announcement didn't specify it clearly."
        )
        poll_id = await polling_mod.deploy_coverage_poll(db, user_id, row, question, opts)
        if poll_id:
            clar["poll_id"] = poll_id
            save_coverage(db, row, {"clarification": clar})
    finally:
        db.close()


# ------------------------------------------------------------- portion summary

def _outline_lines(db, user_id: int, course: str) -> list[str]:
    """The scheduled outline topics for a course (from ingestion, never hardcoded)."""
    from . import academic

    lines = []
    for e in academic.list_events(db, user_id, etype="course", limit=20) \
             + academic.list_events(db, user_id, etype="lecture_topic", limit=40):
        if not e.course or (course and e.course.lower() != course.lower()):
            continue
        name = (e.topic or e.title or "").strip()
        if name:
            lines.append(name)
    return lines


def finalize_from_poll(db, user_id: int, row, winning_portion: str, total_votes: int) -> str:
    """Resolve an AMBIGUOUS coverage from a poll's majority vote.

    The chosen portion is labeled INFERRED with evidence = student_consensus
    (never promoted to 'official'). Records the response, then builds and stores
    the PORTION SUMMARY. Returns the summary text."""
    d = row.details or {}
    d["winning_portion"] = winning_portion
    d["coverage_status"] = "INFERRED"
    d["coverage_evidence"] = "student_consensus"
    d["requires_clarification"] = False
    responses = d.get("student_responses") or []
    responses.append({
        "text": f"[poll majority] {winning_portion}",
        "sender": f"poll · {total_votes} vote(s)",
        "ts": datetime.now(timezone.utc).isoformat(),
    })
    d["student_responses"] = responses
    cov = d.get("coverage") or {}
    if not cov.get("sections") and winning_portion:
        cov["sections"] = [winning_portion]
    cov.setdefault("start", "")
    cov.setdefault("end", "")
    d["coverage"] = cov
    row.details = d
    db.commit()
    db.refresh(row)
    d = row.details or {}
    d["coverage_confidence"] = confidence_label(row, "INFERRED")
    row.details = d
    db.commit()
    db.refresh(row)
    return generate_portion_summary(db, user_id, row)


def _portion_knowable(row) -> bool:
    """Whether the quiz/exam PORTION is actually stated anywhere — in the
    announced message, pinned to the course outline, or via poll consensus.
    If not, the summary must say NOTHING (stay empty) instead of guessing."""
    d = _details(row)
    cover = d.get("coverage") or {}
    bounds = cover.get("coverage") or {}
    start = (bounds.get("start") or "").strip()
    end = (bounds.get("end") or "").strip()
    sections = [s for s in (bounds.get("sections") or []) if str(s).strip()]
    topics = [
        t for t in (cover.get("topics") or [])
        if isinstance(t, dict) and (t.get("name") or "").strip()
    ]
    return bool(
        (d.get("winning_portion") or "").strip()
        or (d.get("coverage_chapter") or "").strip()
        or start or end or sections or topics
    )


def generate_portion_summary(db, user_id: int, row) -> str:
    """Describe + summarize the quiz/exam PORTION using the course outline and
    retrieved course docs. Stores details['portion_summary'] (+ basis) and
    returns the summary text.

    If the portion is not mentioned anywhere (no bounds, sections, topics,
    chapter or voted portion), NOTHING is stored — the summary stays empty."""
    from langchain_core.prompts import ChatPromptTemplate
    from ..knowledge import rag as rag_mod

    llm = _llm(db, user_id)
    cover = get_coverage(row)
    d = row.details or {}

    # If the portion is not stated anywhere (no bounds/sections/topics/chapter/
    # voted portion), say NOTHING: no summary text, no placeholder, no guess.
    if not _portion_knowable(row):
        return ""

    portion = d.get("winning_portion") or ""
    topics = [t for t in (cover.get("topics") or []) if isinstance(t, dict) and t.get("name")]
    bounds = cover.get("coverage") or {}
    outline = _outline_lines(db, user_id, row.course)

    query = " ".join(filter(None, [
        row.course or "", portion,
        bounds.get("start", ""), bounds.get("end", ""),
        " ".join(t.get("name", "") for t in topics),
    ]))
    docs = rag_mod.search_with_meta(user_id, row.course, query or row.course, k=4)

    if llm is None:
        msg = ("No Groq key configured — cannot build the portion summary. "
               f"(portion: {portion or 'unspecified'})")
        d["portion_summary"] = msg
        d["portion_summary_basis"] = ""
        row.details = d
        db.commit()
        return msg

    def _topic_line(t):
        refs = t.get("source_references") or []
        line = f"- {t.get('name', '')}: {t.get('description', '')}"
        if refs:
            line += f"  [{', '.join(refs)}]"
        return line

    topics_text = "\n".join(_topic_line(t) for t in topics) or "(no specific topics stored)"
    doc_text = "\n\n".join(
        f"[{s.get('filename') or s.get('chapter') or s.get('section') or 'docs'}] {s['content'][:380]}"
        for s in docs
    ) if docs else "(no course documents retrieved)"
    outline_text = "\n".join(outline) if outline else "(no course outline ingested yet)"

    prompt = ChatPromptTemplate.from_template(
        "You summarize the exam/quiz COVERAGE (the 'portion') for a university "
        "student. Ground EVERYTHING in the provided outline and doc excerpts; "
        "never invent topics, chapters or facts that are not present in them.\n\n"
        "=== QUIZ/EXAM ===\n{title} — course: {course} ({date})\n\n"
        "=== COVERAGE STATUS ===\n{status} · basis: {basis}\n"
        "Bounds: {start} → {end}\n"
        "Winning portion (student-voted, if any): {portion}\n\n"
        "=== COURSE OUTLINE (topics scheduled) ===\n{outline}\n\n"
        "=== EXTRACTED TOPICS ===\n{topics}\n\n"
        "=== COURSE DOCUMENT EXCERPTS ===\n{docs}\n\n"
        "Produce a concise, study-ready PORTION SUMMARY:\n"
        "1. What the exam covers (chapters/sections/topics) — say clearly whether "
        "this is (CONFIRMED) announced, student-voted INFERRED, or still unclear.\n"
        "2. A bullet list of what to study; for each item a one-line plain-English "
        "explanation plus the key terms/equations found in the excerpts.\n"
        "3. What is NOT in scope if inferable.\n"
        "Keep it under ~12 bullets. If the sources cannot tell what the portion is, "
        "say exactly that instead of guessing."
    )
    chain = prompt | llm
    try:
        res = chain.invoke({
            "title": row.title or "Quiz/Exam",
            "course": row.course or "General",
            "date": row.event_date or "?",
            "status": cover.get("status") or "",
            "basis": str(cover.get("confidence") or cover.get("coverage_evidence") or ""),
            "start": bounds.get("start", ""),
            "end": bounds.get("end", ""),
            "portion": portion or "(none voted yet)",
            "outline": outline_text,
            "topics": topics_text,
            "docs": doc_text,
        })
        summary = (res.content or "").strip()
    except Exception as exc:  # noqa: BLE001
        log.warning("portion summary failed user=%s: %s", user_id, exc)
        # Transient failure (rate limit / API): do NOT persist error text so the
        # background sweep can retry later; nothing is stored.
        return ""
    if not summary:
        return ""

    basis = "course outline + RAG docs" + (" + poll majority" if portion else "")
    d["portion_summary"] = summary
    d["portion_summary_basis"] = basis
    row.details = d
    db.commit()
    return summary


def ensure_quiz_summary(db, user_id: int, event_id: int) -> bool:
    """Idempotently build coverage + the outline-grounded PORTION SUMMARY for a
    quiz/exam. Returns True once a portion summary is stored."""
    from ..models import AcademicEvent

    row = db.query(AcademicEvent).filter_by(id=event_id, user_id=user_id).first()
    if row is None or row.type not in ("quiz", "exam"):
        return False
    if (row.details or {}).get("portion_summary"):
        return True
    text = row.description or row.title or ""
    if not (row.details or {}).get("coverage_status"):
        state = detect_coverage(db, user_id, row, text, [])
        if state["coverage_status"]:
            save_coverage(db, row, {
                "coverage_status": state["coverage_status"],
                "coverage": state["coverage"],
                "topics": state["topics"],
                "coverage_evidence": state["evidence"],
                "requires_clarification": state["requires_clarification"],
                "coverage_chapter": (state["course"] or ""),
            })
    if (row.details or {}).get("coverage_status"):
        if not _portion_knowable(row):
            # portion never mentioned anywhere → nothing to say; considered done
            # so the sweep doesn't keep retrying it.
            return True
        generate_portion_summary(db, user_id, row)
    db.refresh(row)
    return bool((row.details or {}).get("portion_summary"))


def sweep_pending_quiz_summaries(limit: int = 2) -> int:
    """Backfill coverage + outline-grounded summaries for quizzes/exams that
    still lack a 'portion summary' (off the request path)."""
    from ..database import SessionLocal
    from ..models import AcademicEvent

    db = SessionLocal()
    done = 0
    try:
        pending = []
        for r in (
            db.query(AcademicEvent)
            .filter(AcademicEvent.type.in_(["quiz", "exam"]))
            .order_by(AcademicEvent.created_at.asc())
            .all()
        ):
            if (r.details or {}).get("portion_summary"):
                continue
            pending.append(r)
            if len(pending) >= limit:
                break
        for r in pending:
            try:
                if ensure_quiz_summary(db, r.user_id, r.id):
                    done += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("quiz summary sweep failed user=%s event=%s: %s", r.user_id, r.id, exc)
    finally:
        db.close()
    return done


# ----------------------------------------------------- outline cross-check

_CROSSCHECK_PROMPT = """You cross-check what a class reportedly covered (from a
student poll reply) against the course's OFFICIAL outline (an attached document).

=== CLASS REPORTED TOPIC (student poll reply) ===
{topic}

=== COURSE OUTLINE DOCUMENT (retrieved from the attached outline) ===
{outline_docs}

=== SCHEDULED OUTLINE TOPICS (ingested course / lecture-topic events) ===
{outline_topics}

Decide whether the reported topic exists in the outline:
- "matched": true ONLY if it clearly corresponds to an outline item/section.
- "item": the exact outline entry (chapter/section/topic name) it maps to,
  or the closest existing one.
- "closest_item": the nearest outline entry even when not matched.
- "covered_subtopics": concrete subtopics/concepts the outline lists under it.
- "confidence": HIGH (exact wording), MEDIUM (paraphrase), LOW (guess).
- "note": one short line explaining the verdict.

Return STRICT JSON only (no markdown):
{{
  "matched": true|false,
  "item": "",
  "closest_item": "",
  "covered_subtopics": [],
  "confidence": "HIGH|MEDIUM|LOW",
  "note": ""
}}
"""


def cross_check_outline(db, user_id: int, course: str, topic: str) -> dict:
    """Cross-check a student-reported topic against the course outline.

    The outline comes from exactly two places (per the user-flow):
    1) the attached outline document(s) ingested into the course RAG collection
       (source='upload', with the structured chunks carrying chapter/section),
    2) the scheduled outline recorded as 'course' / 'lecture_topic' events.
    Both are searched for the reported topic; an LLM (or a fallback heuristic)
    returns {matched, item, confidence, covered_subtopics, note}."""
    from ..knowledge import rag as rag_mod

    llm = _llm(db, user_id)
    outline_lines = _outline_lines(db, user_id, course)
    query = f"{course} {topic}".strip() or course

    # Exact outline search: attach-only chunks first (that's the outline doc),
    # then any course chunk as a fallback so the verdict is still grounded.
    outline_docs = rag_mod.search_with_meta(
        user_id, course, query, k=6, where={"source": "upload"}
    )
    if not outline_docs:
        outline_docs = rag_mod.search_with_meta(user_id, course, query, k=6)

    doc_text = "\n\n".join(
        f"[{s.get('filename') or s.get('course') or 'outline'}"
        + (f" — {s.get('chapter') or s.get('section')}" if (s.get('chapter') or s.get('section')) else "")
        + f"] {s['content'][:380]}"
        for s in outline_docs
    ) or "(no outline document retrieved)"

    if llm is None:
        return _heuristic_cross_check(topic, outline_lines, outline_docs)

    prompt = _CROSSCHECK_PROMPT.format(
        topic=topic or "(unspecified)",
        outline_docs=doc_text,
        outline_topics="\n".join(o[:120] for o in outline_lines[:25]) or "(no scheduled topics)",
    )
    out = _invoke_json(llm, prompt) or {}
    confidence = out.get("confidence", "LOW")
    if confidence not in ("HIGH", "MEDIUM", "LOW"):
        confidence = "LOW"
    return {
        "matched": bool(out.get("matched")),
        "item": (out.get("item") or out.get("closest_item") or "").strip(),
        "closest_item": (out.get("closest_item") or "").strip(),
        "covered_subtopics": [
            s for s in (out.get("covered_subtopics") or [])
            if isinstance(s, str) and s.strip()
        ],
        "confidence": confidence,
        "note": (out.get("note") or "").strip(),
    }


def _heuristic_cross_check(topic: str, outline_lines: list[str],
                           outline_docs: list[dict]) -> dict:
    """No-LLM fallback: loose textual match against scheduled outline topics
    (and, failing that, against the attached outline file names)."""
    t = (topic or "").lower().strip()
    if not t:
        return {
            "matched": False, "item": "", "closest_item": "",
            "covered_subtopics": [], "confidence": "LOW",
            "note": "No topic provided to cross-check.",
        }
    for name in outline_lines:
        n = name.lower()
        if t in n or n in t:
            return {
                "matched": True, "item": name, "closest_item": name,
                "covered_subtopics": [], "confidence": "MEDIUM",
                "note": "Loose textual match on the scheduled outline (no LLM).",
            }
    for s in outline_docs:
        fn = (s.get("filename") or "").lower()
        if fn and (t in fn or fn in t):
            return {
                "matched": True, "item": s.get("filename") or "",
                "closest_item": s.get("filename") or "",
                "covered_subtopics": [], "confidence": "LOW",
                "note": "Matched an attached outline file name only (no LLM).",
            }
    return {
        "matched": False, "item": "", "closest_item": "",
        "covered_subtopics": [], "confidence": "LOW",
        "note": "No LLM and nothing in the outline matched.",
    }


# ------------------------------------------------- missed-class summarizer

def _recent_missed(db, user_id: int, course: str, topic: str):
    """An existing missed-class entry for the same course+topic (dedupe)."""
    from . import academic

    t = (topic or "").strip().lower()
    c = (course or "").strip().lower()
    for m in academic.list_missed(db, user_id):
        if m.topic.strip().lower() == t and m.course.strip().lower() == c:
            # skipping placeholder rows (no key / no materials) lets a real
            # summary overwrite them later
            if (m.summary or "").startswith("No Groq key") or "cannot build the missed-class" in (m.summary or ""):
                continue
            return m
    return None


def guess_missed_course(db, user_id: int, topic: str) -> str:
    """Pick the most plausible course for a reported topic from the user's
    academic events + RAG collections (never hardcoded)."""
    from . import academic

    scores: dict[str, int] = {}
    t = (topic or "").lower()
    events = (academic.list_events(db, user_id, etype="course", limit=50)
              + academic.list_events(db, user_id, etype="lecture_topic", limit=150))
    for e in events:
        c = (e.course or "").strip()
        if not c:
            continue
        scores.setdefault(c, 0)
        name = (((e.topic or "") + " " + (e.title or "")).lower()).strip()
        if name and (t in name or name in t):
            scores[c] += 2
        if c.lower() in t or t in c.lower():
            scores[c] += 1
    from ..knowledge import rag as rag_mod

    try:
        for name in rag_mod.client_for(user_id).list_collections():
            c = str(name).replace("course_", "")
            if c and c != "general":
                scores.setdefault(c, 0)
    except Exception:  # noqa: BLE001
        pass
    if not scores:
        return ""
    return max(scores, key=lambda c: (scores[c], c))


def last_class_date(db, user_id: int, course: str) -> str:
    """The most recent past class date for a course (for 'the last class')."""
    from . import academic

    today = date.today().isoformat()
    dates = []
    for e in (academic.list_events(db, user_id, etype="class", limit=30)
              + academic.list_events(db, user_id, etype="lecture_topic", limit=40)):
        if course and (e.course or "").lower() != course.lower():
            continue
        d = str(e.event_date or "")[:10]
        if d and d <= today:
            dates.append(d)
    return max(dates) if dates else ""


def build_missed_summary(db, user_id: int, course: str, topic: str,
                         date_str: str, basis: str, context: str = "",
                         save: bool = True) -> tuple[str, dict]:
    """Core missed-class summarizer: cross-check the reported topic against the
    attached course outline, then write a detailed study-ready summary and store
    it in the missed-class dashboard. Returns (summary, cross_check)."""
    from langchain_core.prompts import ChatPromptTemplate
    from ..knowledge import rag as rag_mod

    existing = _recent_missed(db, user_id, course, topic)
    if existing is not None:
        return existing.summary, (existing.cross_check or {})

    llm = _llm(db, user_id)
    cross = cross_check_outline(db, user_id, course, topic)
    if llm is None:
        msg = (f"No Groq key configured — cannot build the missed-class summary. "
               f"(topic: {topic}; basis: {basis})")
        if save:
            from . import academic

            academic.save_missed_summary(db, user_id, course, date_str, topic,
                                         msg, basis, cross_check=cross)
        return msg, cross

    outline_lines = _outline_lines(db, user_id, course)
    docs = rag_mod.search(user_id, course, f"{course} {topic}"[:200], k=4)
    outline_bits = (outline_lines or ([cross["item"]] if cross.get("item") else []))[:24]
    outline_text = "\n".join(o[:120] for o in outline_bits) or "(none)"
    materials = "\n\n".join((d[:700] if len(d) > 700 else d) for d in docs) or "(none)"
    subtopics = "; ".join(
        s[:120] for s in (cross.get("covered_subtopics") or [])[:10]
    ) or "(not listed)"

    if not docs and not outline_bits:
        msg = (f"No course material or outline found for '{topic}' — nothing to base "
               "the class summary on. Upload the course outline/materials first, then retry.")
        if save:
            from . import academic

            academic.save_missed_summary(db, user_id, course, date_str, topic,
                                         msg, basis, cross_check=cross)
        return msg, cross

    verdict = ("matches the course outline" if cross.get("matched")
               else "NOT found in the course outline")
    extra = f"\nStudent's extra context: {context}" if context.strip() else ""
    prompt = ChatPromptTemplate.from_template(
        "You are an elite academic assistant reconstructing a class the student missed.\n\n"
        "Course: {course} · Date: {date}\n"
        "Reported topic: {topic}{extra}\n\n"
        "=== COURSE OUTLINE CROSS-CHECK ===\n{verdict}\nOutline item: {item}\n"
        "Outline subtopics: {subtopics}\n\n"
        "=== SCHEDULED OUTLINE TOPICS ===\n{outline}\n\n"
        "=== COURSE MATERIAL ===\n{materials}\n\n"
        "Write a detailed, study-ready summary of that class based ONLY on the material above.\n"
        "First line: a confidence label — (CONFIRMED) if the topic is in the course outline, "
        "(COMMUNITY) if classmates reported it, (INFERRED) otherwise.\n"
        "Then cover: what was covered, key concepts / definitions / formulas, exercises or "
        "references, and a short 'to catch up' checklist. If the materials cannot support "
        "the topic, say exactly that instead of guessing."
    )
    chain = prompt | llm
    try:
        res = chain.invoke({
            "course": course or "General",
            "date": date_str or "?",
            "topic": topic,
            "extra": extra,
            "verdict": verdict,
            "item": cross.get("item") or "(none)",
            "subtopics": subtopics,
            "outline": outline_text,
            "materials": materials,
        })
        summary = (res.content or "").strip()[:2500]
    except Exception as exc:  # noqa: BLE001
        summary = f"⚠️ Could not build the missed-class summary: {exc}"

    if save and summary:
        from . import academic

        # drop any earlier placeholder row (no-key / no-materials) for this
        # course+topic so the real summary replaces it.
        for m in academic.list_missed(db, user_id):
            if (m.topic.strip().lower() == (topic or "").strip().lower()
                    and m.course.strip().lower() == (course or "").strip().lower()
                    and ((m.summary or "").startswith("No Groq key")
                         or "cannot build the missed-class" in (m.summary or ""))):
                db.delete(m)
        academic.save_missed_summary(db, user_id, course, date_str, topic,
                                     summary, basis, cross_check=cross)
        db.commit()
    return summary, cross


# ------------------------------------------------------------------ helpers

def _format_sources(sources: list[dict]) -> str:
    if not sources:
        return "(no course materials retrieved)"
    lines = []
    for s in sources[:10]:
        parts = [s.get("filename") or s.get("course") or ""]
        for label in ("chapter", "section", "topic"):
            if s.get(label):
                parts.append(f"{label}={s[label]}")
        lines.append(f"[{' | '.join(p for p in parts if p)}] {s['content'][:400]}")
    return "\n\n".join(lines)


def _empty_state() -> dict:
    return {
        "course": "",
        "coverage_status": "",
        "coverage": {"start": "", "end": "", "sections": []},
        "topics": [],
        "evidence": "",
        "requires_clarification": False,
        "reason": "",
        "sources": [],
    }
