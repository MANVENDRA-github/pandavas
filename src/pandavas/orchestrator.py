"""LangGraph orchestrator for the pandavas run loop.

Wires the agents and the real (injected) test executor into a state machine:

    START -> nakula_research -> (research_failed ? END : snapshot)
          -> snapshot -> arjuna_worker -> bhima_test -> sahadeva_judge
          -> yudhishthira -> (status == "running" ? retry snapshot : END)

Retries route back through snapshot so each worker pass gets a fresh
before-snapshot for diffing. The orchestrator is control flow plus state, not a
reasoning agent (see SPEC §3).
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from . import diffing
from .executor import LocalExecutor
from .llm import LLMClient
from .nodes import (
    make_arjuna_worker,
    make_bhima_test,
    make_nakula_research,
    make_sahadeva_judge,
    snapshot_node,
    yudhishthira,
)
from .state import RunState


def _route(state: RunState):
    """Conditional edge after Yudhishthira: retry while running, else stop."""
    return "snapshot" if state.get("status") == "running" else END


def _route_research(state: RunState):
    """Conditional edge after Nakula: stop on research failure, else proceed."""
    return END if state.get("status") == "research_failed" else "snapshot"


def build_graph(executor, worker=None, research=None, judge=None, llm_client=None):
    """Build and compile the orchestrator graph over RunState.

    Args:
        executor: An Executor implementation used by the Bhima node.
        worker: Optional worker node function; defaults to a real Arjuna node.
        research: Optional research node function; defaults to a real Nakula node.
        judge: Optional judge node function; defaults to the stub sahadeva_judge.
        llm_client: Optional LLMClient shared by the default research and worker
            nodes. A client is constructed only when research or worker is not
            injected, so fully-injected callers need no API key.

    Returns:
        A compiled LangGraph graph ready to invoke.
    """

    def _shared_client():
        # Build (or reuse) one LLMClient lazily, only if a default node needs it.
        if _shared_client.client is None:
            _shared_client.client = (
                llm_client if llm_client is not None else LLMClient()
            )
        return _shared_client.client

    _shared_client.client = None

    if research is None:
        research = make_nakula_research(_shared_client())
    if worker is None:
        worker = make_arjuna_worker(_shared_client())
    if judge is None:
        judge = make_sahadeva_judge(_shared_client())

    graph = StateGraph(RunState)
    graph.add_node("nakula_research", research)
    graph.add_node("snapshot", snapshot_node)
    graph.add_node("arjuna_worker", worker)
    graph.add_node("bhima_test", make_bhima_test(executor))
    graph.add_node("sahadeva_judge", judge)
    graph.add_node("yudhishthira", yudhishthira)

    graph.add_edge(START, "nakula_research")
    graph.add_conditional_edges(
        "nakula_research",
        _route_research,
        {"snapshot": "snapshot", END: END},
    )
    graph.add_edge("snapshot", "arjuna_worker")
    graph.add_edge("arjuna_worker", "bhima_test")
    graph.add_edge("bhima_test", "sahadeva_judge")
    graph.add_edge("sahadeva_judge", "yudhishthira")
    graph.add_conditional_edges(
        "yudhishthira",
        _route,
        {"snapshot": "snapshot", END: END},
    )

    return graph.compile()


def run(
    task: str,
    repo_path: str,
    test_command: Optional[str] = None,
    max_iterations: int = 6,
    executor=None,
    worker=None,
    research=None,
    judge=None,
    llm_client=None,
) -> RunState:
    """Run the orchestrator loop and return the final state.

    Args:
        task: Natural-language task description.
        repo_path: Path to the local repository.
        test_command: Optional explicit test command (overrides detection).
        max_iterations: Hard cap on retry iterations.
        executor: Optional Executor; defaults to LocalExecutor().
        worker: Optional worker node function; defaults to a real Arjuna node.
        research: Optional research node function; defaults to a real Nakula node.
        judge: Optional judge node function; defaults to the stub sahadeva_judge.
        llm_client: Optional LLMClient for the default research/worker nodes.

    Returns:
        The final RunState after the graph terminates.
    """
    if executor is None:
        executor = LocalExecutor()

    # Capture the true original repo state before any node (research/worker) runs.
    baseline_snapshot = diffing.snapshot(repo_path)
    # Baseline test run: pre-existing failures are tolerated; only NEW failures
    # (regressions / unmet repro tests) fail the gate. Not counted as an iteration.
    baseline_result = executor.run_tests(repo_path, test_command)

    initial: RunState = {
        "task": task,
        "repo_path": repo_path,
        "test_command": test_command,
        "research_brief": {},
        "iteration": 1,
        "max_iterations": max_iterations,
        "last_test_result": None,
        "test_passed": None,
        "baseline_test_results": baseline_result.per_test,
        "regressions": [],
        "new_failures": [],
        "newly_passing": [],
        "judge_approved": None,
        "judge_feedback": None,
        "status": "running",
        "research_error": None,
        "termination_reason": None,
        "iteration_signatures": [],
        "best_attempt": None,
        "baseline_snapshot": baseline_snapshot,
        "pre_worker_snapshot": None,
        "last_diff": None,
        "trace": [],
    }

    graph = build_graph(executor, worker, research, judge, llm_client)
    # Each iteration now runs 5 nodes (snapshot added); allow generous headroom
    # over the cap so the loop terminates via status, never the recursion limit.
    config = {"recursion_limit": max_iterations * 5 + 10}
    final = graph.invoke(initial, config=config)
    return final
