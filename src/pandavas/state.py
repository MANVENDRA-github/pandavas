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
    baseline_test_results: Optional[dict]  # per_test dict from the baseline run
    regressions: list  # tests that passed at baseline but fail now
    new_failures: list  # tests failing now that were not failing at baseline
    newly_passing: list  # tests green now that were not green at baseline (red->green)
    judge_approved: Optional[bool]
    judge_feedback: Optional[str]
    status: str  # "running" | "converged" | "did_not_converge" | "research_failed"
    research_error: Optional[str]  # set when research fails to produce a valid brief
    termination_reason: Optional[str]  # "cap" | "oscillation" | None
    iteration_signatures: list  # signatures of past iterations, for oscillation
    best_attempt: Optional[dict]  # {iteration, snapshot, new_failures, ...} best so far
    baseline_snapshot: Optional[dict]  # repo snapshot captured once before iteration 1
    pre_worker_snapshot: Optional[dict]  # {path: content} captured before the worker
    last_diff: Optional[str]  # unified diff of the most recent worker change
    trace: list  # list of per-iteration dicts
