"""LangGraph orchestrator for the pandavas run loop (P0 skeleton).

Wires the stub agents and the real (injected) test executor into a state machine:

    START -> nakula_research -> arjuna_worker -> bhima_test
          -> sahadeva_judge -> yudhishthira
          -> (status == "running") ? retry arjuna_worker : END

The orchestrator is control flow plus state, not a reasoning agent (see SPEC §3).
"""

from __future__ import annotations

from typing import Optional

from langgraph.graph import END, START, StateGraph

from .executor import LocalExecutor
from .nodes import (
    arjuna_worker,
    make_bhima_test,
    nakula_research,
    sahadeva_judge,
    yudhishthira,
)
from .state import RunState


def _route(state: RunState):
    """Conditional edge after Yudhishthira: retry while running, else stop."""
    return "arjuna_worker" if state.get("status") == "running" else END


def build_graph(executor, worker=None):
    """Build and compile the orchestrator graph over RunState.

    Args:
        executor: An Executor implementation used by the Bhima node.
        worker: Optional worker node function; defaults to arjuna_worker.

    Returns:
        A compiled LangGraph graph ready to invoke.
    """
    if worker is None:
        worker = arjuna_worker

    graph = StateGraph(RunState)
    graph.add_node("nakula_research", nakula_research)
    graph.add_node("arjuna_worker", worker)
    graph.add_node("bhima_test", make_bhima_test(executor))
    graph.add_node("sahadeva_judge", sahadeva_judge)
    graph.add_node("yudhishthira", yudhishthira)

    graph.add_edge(START, "nakula_research")
    graph.add_edge("nakula_research", "arjuna_worker")
    graph.add_edge("arjuna_worker", "bhima_test")
    graph.add_edge("bhima_test", "sahadeva_judge")
    graph.add_edge("sahadeva_judge", "yudhishthira")
    graph.add_conditional_edges(
        "yudhishthira",
        _route,
        {"arjuna_worker": "arjuna_worker", END: END},
    )

    return graph.compile()


def run(
    task: str,
    repo_path: str,
    test_command: Optional[str] = None,
    max_iterations: int = 6,
    executor=None,
    worker=None,
) -> RunState:
    """Run the orchestrator loop and return the final state.

    Args:
        task: Natural-language task description.
        repo_path: Path to the local repository.
        test_command: Optional explicit test command (overrides detection).
        max_iterations: Hard cap on retry iterations.
        executor: Optional Executor; defaults to LocalExecutor().
        worker: Optional worker node function; defaults to arjuna_worker.

    Returns:
        The final RunState after the graph terminates.
    """
    if executor is None:
        executor = LocalExecutor()

    initial: RunState = {
        "task": task,
        "repo_path": repo_path,
        "test_command": test_command,
        "research_brief": {},
        "iteration": 0,
        "max_iterations": max_iterations,
        "last_test_result": None,
        "test_passed": None,
        "judge_approved": None,
        "judge_feedback": None,
        "status": "running",
        "trace": [],
    }

    graph = build_graph(executor, worker)
    # Each iteration runs 4 nodes; allow generous headroom over the cap so the
    # loop terminates via status, never via LangGraph's recursion limit.
    config = {"recursion_limit": max_iterations * 4 + 10}
    final = graph.invoke(initial, config=config)
    return final
