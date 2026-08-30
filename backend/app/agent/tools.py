"""Thin shim — the AI/LLM code now lives in backend/classmate_agent.ipynb.

Public symbols are loaded from the notebook (which composes llm.py + agent
tools + agent graph) so the app keeps running while the real code is edited
in an easy-to-debug notebook.
"""
from .._nbload import load_namespace

build_tools = load_namespace()["build_tools"]
