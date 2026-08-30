"""Thin shim — the AI/LLM code now lives in backend/classmate_agent.ipynb.

Public symbols are loaded from the notebook (which composes llm.py + agent
tools + agent graph) so the app keeps running while the real code is edited
in an easy-to-debug notebook.
"""
from ._nbload import load_namespace

_ns = load_namespace()

get_or_create_settings = _ns["get_or_create_settings"]
get_decrypted_settings = _ns["get_decrypted_settings"]
save_settings = _ns["save_settings"]
get_groq_api_key = _ns["get_groq_api_key"]
get_llm = _ns["get_llm"]
