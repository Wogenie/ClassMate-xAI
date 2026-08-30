"""Dynamic document-structure detection.

Implements the "Upload & Embed" pipeline from the Dynamic Quiz Coverage spec:
given raw document text, use the LLM to discover — with ZERO hardcoded course /
chapter / section / topic names — the document's structure, split it into
metadata-rich chunks, and return those chunks for embedding into ChromaDB.

Every label (course, chapter, section, topic, source_type, page) is discovered
from the content and the user's own LLM, never from fixed rules.
"""
import json
import logging

log = logging.getLogger("classmate.metadata")

_ANALYZE_PROMPT = """You are the document-structure analyst. Read the course
document text below and resolve its STRUCTURE — everything must be derived from
the content itself. There are NO predefined course names, chapter numbers,
topics, or section names.

Return STRICT JSON (no markdown, no prose) shaped exactly like this:

{
  "course": "<resolved course name, or '' if unknown>",
  "source_type": "<slide | notes | textbook | outline | worksheet | other>",
  "chunks": [
    {
      "text": "<a self-contained chunk of 300-900 characters, aligned to structure>",
      "chapter": "<chapter/title this chunk belongs to, or ''>",
      "section": "<section/subheading this chunk belongs to, or ''>",
      "topic": "<the specific topic this chunk explains, or ''>",
      "page": "<page/slide number if determinable, else ''>"
    }
  ]
}

Rules:
- Detect chapters/sections/topics from headings, numbering and content phrasing.
- Split the document into chunks that follow the detected structure (one topic
  per chunk where possible).
- Do not invent chapters/topics; leave fields empty when unsure.
- Translate the content faithfully; keep the key wording.

=== DOCUMENT TEXT (start) ===
{document_text}
=== DOCUMENT TEXT (end) ===
"""


def detect_structures(llm, raw_text: str, max_chars: int = 20000) -> dict:
    """Run the LLM structure detector over the document text.

    Returns {'course':..., 'source_type':..., 'chunks':[...]}. On any failure,
    returns an empty structure so the caller can fall back to plain chunking.
    """
    from langchain_core.messages import HumanMessage, SystemMessage

    text = (raw_text or "").strip()
    if len(text) < 30 or llm is None:
        return {"course": "", "source_type": "document", "chunks": []}
    truncated = text[:max_chars]

    sys = _ANALYZE_PROMPT.replace("{document_text}", truncated)
    try:
        res = llm.invoke([HumanMessage(content=sys)])
        raw = (res.content or "").strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        payload = json.loads(raw[raw.index("{"):])
        chunks = payload.get("chunks") or []
        chunks = [c for c in chunks if isinstance(c, dict) and (c.get("text") or "").strip()]
        return {
            "course": (payload.get("course") or "").strip(),
            "source_type": (payload.get("source_type") or "document").strip() or "document",
            "chunks": chunks,
        }
    except Exception as exc:  # noqa: BLE001
        log.warning("Structure detection failed: %s", exc)
        return {"course": "", "source_type": "document", "chunks": []}
