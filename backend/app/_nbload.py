"""Lazy loader that treats backend/classmate_agent.ipynb as the source of
truth for the AI / agent layer.

The notebook composes what previously lived in app/llm.py, app/agent/tools.py
and app/agent/graph.py. Those files are now thin shims that pull their public
symbols from here, so the backend keeps running while the real AI code lives in
an easy-to-edit, easy-to-debug notebook.
"""
import json
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]          # backend/
_NB = _BACKEND_DIR / "classmate_agent.ipynb"

_namespace = None
_namespace_loaded = False


def _ensure_paths():
    if str(_BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(_BACKEND_DIR))


def load_namespace() -> dict:
    """Execute the notebook's code cells once and return the resulting global
    namespace. Cached so repeated imports are cheap."""
    global _namespace, _namespace_loaded
    if _namespace_loaded:
        return _namespace

    if not _NB.exists():
        raise ImportError(f"AI notebook not found: {_NB}")

    _ensure_paths()
    data = json.loads(_NB.read_text(encoding="utf-8"))
    code = [
        "".join(cell.get("source", []))
        for cell in data.get("cells", [])
        if cell.get("cell_type") == "code"
    ]
    ns: dict = {}
    exec("\n\n".join(code), ns)
    _namespace = ns
    _namespace_loaded = True
    return ns
