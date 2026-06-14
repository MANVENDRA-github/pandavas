"""LangGraph node functions for the pandavas orchestrator (P0 skeleton).

All agents are STUBS at P0: no LLM calls, no network, no file editing. The only
real node is Bhima (the test executor), which is injected via a factory so the
backend can be swapped without touching this module. Each node takes the full
RunState and returns a partial state dict, LangGraph-style.
"""

from __future__ import annotations

from .state import RunState


def nakula_research(state: RunState) -> dict:
    """Research stub (Nakula). Returns a placeholder brief — real research is P1."""
    return {
        "research_brief": {
            "stub": True,
            "note": "placeholder brief — real research is P1",
        }
    }


def arjuna_worker(state: RunState) -> dict:
    """Worker stub (Arjuna). NO-OP: edits no files; only advances the iteration."""
    i = state.get("iteration", 0) + 1
    return {"iteration": i}


def make_bhima_test(executor):
    """Build the real test node (Bhima), binding an injected executor.

    Args:
        executor: An Executor implementation (e.g. LocalExecutor or a fake).

    Returns:
        A LangGraph node function that runs the repo's tests and reports red/green.
    """

    def bhima_test(state: RunState) -> dict:
        result = executor.run_tests(state["repo_path"], state["test_command"])
        return {"last_test_result": result, "test_passed": result.passed}

    return bhima_test


def sahadeva_judge(state: RunState) -> dict:
    """Judge stub (Sahadeva). Deterministic: approve iff the tests passed."""
    passed = bool(state["test_passed"])
    return {
        "judge_approved": passed,
        "judge_feedback": "" if passed else "stub: tests failing",
    }


def yudhishthira(state: RunState) -> dict:
    """Orchestrator decision node (Yudhishthira).

    Sets the run status from the judge verdict and the iteration cap, and appends
    one record to the trace for this iteration.
    """
    approved = bool(state.get("judge_approved"))
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 0)

    if approved:
        status = "converged"
    elif iteration >= max_iterations:
        status = "did_not_converge"
    else:
        status = "running"

    record = {
        "iteration": iteration,
        "test_passed": state.get("test_passed"),
        "judge_approved": state.get("judge_approved"),
        "judge_feedback": state.get("judge_feedback"),
    }
    updated_trace = state.get("trace", []) + [record]

    return {"status": status, "trace": updated_trace}
