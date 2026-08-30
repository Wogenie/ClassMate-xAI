"""Thin shim — the AI/LLM code now lives in backend/classmate_agent.ipynb.

Public symbols are loaded from the notebook (which composes llm.py + agent
tools + agent graph + solvers) so the app keeps running while the real code is
edited in an easy-to-debug notebook.
"""
from .._nbload import load_namespace

_ns = load_namespace()

build_graph = _ns["build_graph"]
answer = _ns["answer"]
recent_history = _ns["recent_history"]
clear_history = _ns["clear_history"]
solve_assignment = _ns["solve_assignment"]
generate_study_guide = _ns["generate_study_guide"]
missed_summary_with_outline = _ns["missed_summary_with_outline"]
