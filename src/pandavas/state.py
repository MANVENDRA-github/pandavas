"""Shared run state for the pandavas orchestrator (P0 skeleton).

The orchestrator (Yudhishthira) owns this state and passes it between nodes.
LangGraph merges each node's returned partial dict into this structure.
"""

from __future__ import annotations

from typing import Optional, TypedDict


class RunState(TypedDict):
    """State threaded through the LangGraph run.

    Fields marked Optional are unset until a node produces them.
    """

    task: str
    repo_path: str
    test_command: Optional[str]
    research_brief: dict  # stub placeholder for now (real research is P1)
    iteration: int
    max_iterations: int
    last_test_result: Optional[object]  # a TestResult from executor.py
    test_passed: Optional[bool]
    judge_approved: Optional[bool]
    judge_feedback: Optional[str]
    status: str  # "running" | "converged" | "did_not_converge"
    trace: list  # list of per-iteration dicts
