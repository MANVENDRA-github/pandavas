"""LangGraph node functions for the pandavas orchestrator.

Bhima (the test executor) and Nakula (research) are real and injected via
factories so their backends can be swapped without touching this module. Arjuna
(worker) and Sahadeva (judge) remain stubs at P1. Each node takes the full
RunState and returns a partial state dict, LangGraph-style.
"""

from __future__ import annotations

import json
import os

from pydantic import ValidationError

from . import edits, retrieval
from .brief import ResearchBrief, resolve_brief
from .state import RunState

RESEARCH_MODEL_ENV = "PANDAVAS_RESEARCH_MODEL"
WORKER_MODEL_ENV = "PANDAVAS_WORKER_MODEL"

_ARJUNA_SYSTEM = (
    "You are the implementation worker. Given the task, acceptance criteria, and "
    "the current contents of the relevant files, produce the changes that satisfy "
    "the acceptance criteria. If this is a bug fix and no test covers it, include "
    "a test that reproduces the bug (it should fail before your fix and pass "
    "after). Output ONLY a JSON object: "
    '{"files": [{"path": <repo-relative>, "content": <COMPLETE new file content, '
    'not a diff>}], "rationale": <short string>}. Provide the entire file content '
    "for every file you change or create. Use repo-relative paths."
)

_NAKULA_SYSTEM = (
    "You are Nakula, the research agent. Inspect the provided repository context "
    "and output ONLY a single JSON object describing where the task should be "
    "solved. No prose, no markdown, no code fences — JSON only.\n"
    "The object must have these keys:\n"
    "  task: string\n"
    "  acceptance_criteria: list of concrete, testable conditions (strings)\n"
    "  relevant_code: list of anchors (at least one required)\n"
    "  conventions: list of anchors (may be empty)\n"
    "  integration_points: list of anchors (may be empty)\n"
    "  constraints: list of strings (may be empty)\n"
    "  open_questions: list of strings (may be empty)\n"
    "  confidence: object mapping claim -> number (may be empty)\n"
    "Each anchor is {path, line_start, line_end, snippet, why}. Anchors MUST use "
    "real repo-relative paths and 1-indexed line ranges exactly as shown by the "
    '"N:" line-number prefixes in the provided context.'
)


def nakula_research(state: RunState) -> dict:
    """Research stub (Nakula). Returns a placeholder brief — real research is P1."""
    return {
        "research_brief": {
            "stub": True,
            "note": "placeholder brief — real research is P1",
        }
    }


def _strip_json_fences(text: str) -> str:
    """Defensively strip ```json ... ``` fences a model may add despite json_mode."""
    s = text.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
    return s.strip()


def make_nakula_research(llm_client, max_retries: int = 2):
    """Build the real research node (Nakula), binding an injected LLM client.

    The node retrieves a bounded repo context, asks the model for a ResearchBrief
    as JSON, and runs the deterministic resolve gate. On parse/validation errors
    or dangling anchors it feeds the failure back to the model and retries, up to
    (1 + max_retries) attempts. If still unresolved, it fails the run.

    Args:
        llm_client: An LLMClient (or compatible) with a complete(...) method.
        max_retries: Extra attempts beyond the first.

    Returns:
        A LangGraph node function.
    """

    def nakula_research_node(state: RunState) -> dict:
        model = os.getenv(RESEARCH_MODEL_ENV)
        if not model:
            raise RuntimeError(
                f"Missing research model: set the {RESEARCH_MODEL_ENV} "
                "environment variable to a pinned model id."
            )

        context = retrieval.build_context(state["repo_path"], state["task"])
        messages = [
            {"role": "system", "content": _NAKULA_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"TASK:\n{state['task']}\n\n"
                    f"REPOSITORY CONTEXT:\n{context}"
                ),
            },
        ]

        last_error = "no attempts ran"
        for _ in range(1 + max_retries):
            reply = llm_client.complete(
                messages, model=model, temperature=0.0, json_mode=True
            )

            try:
                parsed = ResearchBrief(**json.loads(_strip_json_fences(reply)))
            except (json.JSONDecodeError, ValidationError, TypeError) as exc:
                last_error = f"invalid ResearchBrief JSON: {exc}"
                messages.append({"role": "assistant", "content": reply})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Output was not a valid ResearchBrief JSON object: "
                            f"{exc}. Return only corrected JSON."
                        ),
                    }
                )
                continue

            failures = resolve_brief(parsed, state["repo_path"])
            if not failures:
                return {"research_brief": parsed.model_dump()}

            last_error = "; ".join(failures)
            messages.append({"role": "assistant", "content": reply})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "These anchors did not resolve: "
                        f"{last_error}. Every anchor must cite a real "
                        "repo-relative path and a 1-indexed line range present "
                        "in the provided context. Return corrected JSON only."
                    ),
                }
            )

        return {"status": "research_failed", "research_error": last_error}

    return nakula_research_node


def arjuna_worker(state: RunState) -> dict:
    """Worker stub (Arjuna). Pure NO-OP: edits no files, touches no counters.

    Iteration bookkeeping now lives in the orchestrator decision node, so the
    real worker (P1.2) will only do agent work.
    """
    return {}


def _brief_anchor_paths(brief: ResearchBrief) -> list[str]:
    """Unique repo-relative paths across relevant_code, integration_points, conventions."""
    seen: dict[str, None] = {}
    for anchor in (
        list(brief.relevant_code)
        + list(brief.integration_points)
        + list(brief.conventions)
    ):
        seen.setdefault(anchor.path, None)
    return list(seen)


def make_arjuna_worker(llm_client):
    """Build the real worker node (Arjuna), binding an injected LLM client.

    Re-reads the real current contents at the brief's anchors (anchors are truth,
    not the snippets), asks the model for complete-file replacements as JSON, and
    writes them through the path-safe edit applier. Bad output applies nothing and
    leaves retrying to the test/judge gate.

    Args:
        llm_client: An LLMClient (or compatible) with a complete(...) method.

    Returns:
        A LangGraph node function.
    """

    def arjuna_worker_node(state: RunState) -> dict:
        brief = ResearchBrief.model_validate(state["research_brief"])
        repo_path = state["repo_path"]

        # Re-read the real current code at the anchored files (skip missing).
        file_sections: list[str] = []
        for rel in _brief_anchor_paths(brief):
            abs_path = os.path.join(repo_path, rel)
            if not os.path.isfile(abs_path):
                continue
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            file_sections.append(f"=== {rel} ===\n{content}")

        model = os.getenv(WORKER_MODEL_ENV)
        if not model:
            raise RuntimeError(
                f"Missing worker model: set the {WORKER_MODEL_ENV} "
                "environment variable to a pinned model id."
            )

        criteria = "\n".join(f"- {c}" for c in brief.acceptance_criteria)
        user_parts = [
            f"TASK:\n{state['task']}",
            f"ACCEPTANCE CRITERIA:\n{criteria}",
            "CURRENT FILE CONTENTS:\n" + "\n\n".join(file_sections),
        ]
        feedback = state.get("judge_feedback")
        if feedback:
            user_parts.append(f"Previous review feedback to address:\n{feedback}")

        messages = [
            {"role": "system", "content": _ARJUNA_SYSTEM},
            {"role": "user", "content": "\n\n".join(user_parts)},
        ]

        reply = llm_client.complete(
            messages, model=model, temperature=0.0, json_mode=True
        )

        try:
            parsed = json.loads(_strip_json_fences(reply))
            files = parsed["files"]
        except (json.JSONDecodeError, KeyError, TypeError):
            # Bad output: apply nothing; the test/judge gate drives a retry.
            return {}
        if not isinstance(files, list):
            return {}

        edits.apply_edits(repo_path, files)
        return {}

    return arjuna_worker_node


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

    Owns the iteration counter. Appends one trace record for the current pass,
    then sets status from the judge verdict and the iteration cap; only advances
    the counter when the loop will retry.
    """
    it = state["iteration"]
    max_iterations = state["max_iterations"]

    record = {
        "iteration": it,
        "test_passed": state["test_passed"],
        "judge_approved": state["judge_approved"],
        "judge_feedback": state.get("judge_feedback", ""),
    }
    updated_trace = state.get("trace", []) + [record]

    if state["judge_approved"]:
        return {"status": "converged", "trace": updated_trace}
    if it >= max_iterations:
        return {"status": "did_not_converge", "trace": updated_trace}
    return {"status": "running", "iteration": it + 1, "trace": updated_trace}
