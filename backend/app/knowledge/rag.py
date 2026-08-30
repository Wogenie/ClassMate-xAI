"""Per-user, per-course vector memory (RAG) with a fully local embedding model
(all-MiniLM via ONNX) so users do not need an extra key.

Vectors are stored as plain numpy matrices on disk (one .npz per user/course)
and searched with numpy dot-products. This deliberately avoids ChromaDB/hnswlib,
whose native index crashes on CPUs without AVX2 (e.g. Ivy Bridge / i5-3360M).
"""
import os
import re
import threading
from pathlib import Path

import numpy as np
from chromadb.utils import embedding_functions

from .. import config, prompt_loader

_NAMESPACE = "rag"
_LOCK = threading.Lock()
_default_ef = None
_DIM = 384


def _ef():
    global _default_ef
    if _default_ef is None:
        _default_ef = embedding_functions.DefaultEmbeddingFunction()
    return _default_ef


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed a BATCH of texts into flat vectors.

    IMPORTANT: the embedder must be called with a LIST, never a bare string —
    passing a str makes chroma's default function iterate per character.
    """
    return [list(map(float, v)) for v in _ef()(list(texts))]


def _slug(course: str) -> str:
    return prompt_loader.slugify(course or "general") or "general"


def _store_path(user_id: int, course: str) -> Path:
    return config.DATA_DIR / _NAMESPACE / f"user_{user_id}" / f"course_{_slug(course)}.npz"


def _load(user_id: int, course: str):
    """Return (texts, metas, emb) for a user/course store, or empties."""
    p = _store_path(user_id, course)
    if not p.exists():
        return [], [], np.zeros((0, _DIM), dtype=np.float32)
    z = np.load(p, allow_pickle=True)
    texts = list(z["text"])
    metas = list(z["meta"])
    emb = np.asarray(z["emb"], dtype=np.float32)
    return texts, metas, emb


def _save(user_id: int, course: str, texts, metas, emb) -> None:
    p = _store_path(user_id, course)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp.npz")
    np.savez(tmp, emb=emb.astype(np.float32), text=np.asarray(texts, dtype=object),
             meta=np.asarray(metas, dtype=object))
    os.replace(tmp, p)


def client_for(user_id: int):
    """Compatibility shim: exposes list_collections() over the numpy store."""

    class _Client:
        @staticmethod
        def list_collections():
            return ["course_" + c for c in _course_names(user_id)]

    return _Client()


def collection_for(user_id: int, course: str):
    """Kept for API compatibility: just makes sure the store dir exists."""
    _store_path(user_id, course).parent.mkdir(parents=True, exist_ok=True)
    return None


def add_texts(user_id: int, course: str, texts: list[str], metadatas: list[dict] | None = None):
    if not texts:
        return 0
    with _LOCK:
        old_texts, old_metas, emb = _load(user_id, course)
        vecs = np.asarray(_embed(texts), dtype=np.float32)
        emb = np.vstack([emb, vecs]) if emb.shape[0] else vecs
        _save(user_id, course, old_texts + list(texts), old_metas + list(metadatas or [{}] * len(texts)), emb)
    return len(texts)


def _clean_meta(m: dict | None) -> dict:
    """Delete empty/None values so downstream metas stay tidy."""
    if not m:
        return {}
    return {k: v for k, v in m.items() if v not in (None, "", [])}


def _match_meta(meta: dict, where: dict) -> bool:
    if not where:
        return True
    for k, v in where.items():
        if meta.get(k) != v:
            return False
    return True


def _search_vectors(user_id: int, course: str, query_emb, k: int, where: dict | None):
    """Top-k docs for a vectorized query. Returns list of (text, meta, sim)."""
    texts, metas, emb = _load(user_id, course)
    if emb.shape[0] == 0:
        return []
    q = np.asarray(query_emb, dtype=np.float32)
    idxs = [i for i in range(emb.shape[0]) if _match_meta(metas[i], where or {})]
    if not idxs:
        return []
    idxs = np.asarray(idxs)
    sims = emb[idxs] @ q
    order = np.argsort(-sims)[: max(0, min(k, len(idxs)))]
    out = []
    for o in order:
        i = int(idxs[o])
        out.append((texts[i], metas[i], round(float(sims[o]), 4)))
    return out


def search(user_id: int, course: str, query: str, k: int = 5,
           where: dict | None = None) -> list[str]:
    try:
        q = _embed([query])[0]
        res = _search_vectors(user_id, course, q, k, where)
    except Exception:
        return []
    return [r[0] for r in res]


def search_with_meta(user_id: int, course: str, query: str, k: int = 5,
                     where: dict | None = None) -> list[dict]:
    """Source-aware retrieval: returns content PLUS dynamic metadata
    (chapter, section, topic, source_type, filename, similarity)."""
    try:
        q = _embed([query])[0]
        res = _search_vectors(user_id, course, q, k, where)
    except Exception:
        return []
    out = []
    for text, m, sim in res:
        out.append({
            "content": text,
            "course": course,
            "chapter": m.get("chapter", ""),
            "section": m.get("section", ""),
            "topic": m.get("topic", ""),
            "source_type": m.get("source_type", ""),
            "filename": m.get("filename", ""),
            "page": m.get("page", ""),
            "similarity": sim,
        })
    return out


def _course_names(user_id: int) -> list[str]:
    d = config.DATA_DIR / _NAMESPACE / f"user_{user_id}"
    if not d.exists():
        return []
    names = []
    for f in sorted(d.glob("course_*.npz")):
        course = re.sub(r"^course_", "", f.stem)
        # undo slugify so search queries use the original-ish course label
        names.append(course)
    return names


def search_all_courses(user_id: int, query: str, k_per_course: int = 3) -> list[str]:
    merged: list[str] = []
    for course in _course_names(user_id):
        try:
            merged.extend(search(user_id, course, query, k_per_course))
        except Exception:
            continue
    seen, out = set(), []
    for d in merged:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def search_all_courses_with_meta(user_id: int, query: str, k_per_course: int = 3,
                                 where: dict | None = None) -> list[dict]:
    merged: list[dict] = []
    for course in _course_names(user_id):
        try:
            merged.extend(search_with_meta(user_id, course, query, k_per_course, where))
        except Exception:
            continue
    seen, out = set(), []
    for r in merged:
        key = r["content"][:120]
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def ingest_document_text(user_id: int, course: str, raw: str, filename: str = "", source: str = "telegram"):
    """Chunk raw text and embed it into the course's vector store."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    raw = (raw or "").strip()
    if len(raw) < 30:
        return 0
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200, chunk_overlap=180, separators=["\n\n", "\n", ". ", " "]
    )
    chunks = splitter.split_text(raw)
    metas = [
        {"course": course, "filename": filename, "source": source}
        for _ in chunks
    ]
    added = add_texts(user_id, course, chunks, metas)
    from .. import database

    db = database.SessionLocal()
    try:
        from ..models import DocumentChunkRef

        db.add(
            DocumentChunkRef(
                user_id=user_id, course=course, filename=filename,
                source=source, chunk_count=added,
            )
        )
        db.commit()
    finally:
        db.close()
    return added


def ingest_structured_chunks(user_id: int, course: str, chunks: list[dict],
                             filename: str = "", source: str = "upload") -> int:
    """Ingest pre-detected, metadata-rich chunks from the doc-structure detector.

    Each chunk: {text, chapter, section, topic, source_type, page}
    """
    if not chunks:
        return 0
    texts, metas = [], []
    for c in chunks:
        text = (c.get("text") or "").strip()
        if len(text) < 30:
            continue
        texts.append(text)
        metas.append(_clean_meta({
            "course": course,
            "filename": filename,
            "source": source,
            "source_type": c.get("source_type", "document"),
            "chapter": c.get("chapter", ""),
            "section": c.get("section", ""),
            "topic": c.get("topic", ""),
            "page": c.get("page", ""),
        }))
    added = add_texts(user_id, course, texts, metas)
    from .. import database

    db = database.SessionLocal()
    try:
        from ..models import DocumentChunkRef

        db.add(
            DocumentChunkRef(
                user_id=user_id, course=course, filename=filename,
                source=source, chunk_count=added,
            )
        )
        db.commit()
    finally:
        db.close()
    return added