"""LangGraph node functions for the pandavas orchestrator.

The research (Nakula), worker (Arjuna), and judge (Sahadeva) agents are real LLM
nodes built by factories that bind an injected LLM client; the test runner
(Bhima) is a real deterministic node bound to an injected executor. Stub versions
(nakula_research / arjuna_worker / sahadeva_judge) remain for offline wiring
checks. Each node takes the full RunState and returns a partial state dict.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from pydantic import ValidationError

from . import diffing, edits, retrieval, testresults
from .brief import ResearchBrief, resolve_brief
from .state import RunState

RESEARCH_MODEL_ENV = "PANDAVAS_RESEARCH_MODEL"
WORKER_MODEL_ENV = "PANDAVAS_WORKER_MODEL"
JUDGE_MODEL_ENV = "PANDAVAS_JUDGE_MODEL"

_SAHADEVA_SYSTEM = (
    "You are an INDEPENDENT code reviewer; you did not write this code. Review "
    "the proposed change against the acceptance criteria. Also decide whether any "
    "added or modified test genuinely verifies the requirement or is vacuous "
    "(trivially passing / asserts nothing meaningful). "
    "Approve ONLY if the change satisfies the acceptance criteria AND no test "
    "relevant to the task remains failing. A still-failing test that the task was "
    "meant to fix means reject. Output ONLY JSON: "
    '{"approved": <bool>, "feedback": <specific, actionable string; when '
    'rejecting, name what is wrong and where>}.'
)

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
        baseline = state.get("baseline_test_results")

        if result.per_test is not None and baseline is not None:
            cur_fail = testresults.failures(result.per_test)
            base_fail = testresults.failures(baseline)
            # Pass iff no NEW failures: pre-existing failures are tolerated, but
            # any new/repro test must pass and nothing may regress.
            test_passed = cur_fail <= base_fail
            regressions = sorted(testresults.passed(baseline) & cur_fail)
            new_failures = sorted(cur_fail - base_fail)
            # red->green proof: tests green now that were not green at baseline
            # (a failing test now fixed, or a new repro test now passing).
            newly_passing = sorted(
                testresults.passed(result.per_test) - testresults.passed(baseline)
            )
        else:
            # Fallback: exit-code only (non-pytest, or no parseable results).
            test_passed = result.passed
            regressions = []
            new_failures = []
            newly_passing = []

        return {
            "last_test_result": result,
            "test_passed": test_passed,
            "regressions": regressions,
            "new_failures": new_failures,
            "newly_passing": newly_passing,
        }

    return bhima_test


def snapshot_node(state: RunState) -> dict:
    """Capture the repo's pre-worker file snapshot for later diffing."""
    return {"pre_worker_snapshot": diffing.snapshot(state["repo_path"])}


def change_diff(state: RunState, after: Optional[dict] = None) -> str:
    """Unified diff of the current repo state vs the pre-worker snapshot.

    Pass ``after`` (a precomputed snapshot) to avoid re-walking the repo when the
    caller already has the current snapshot.
    """
    if after is None:
        after = diffing.snapshot(state["repo_path"])
    return diffing.compute_diff(state.get("pre_worker_snapshot") or {}, after)


def cumulative_diff(state: RunState, after: Optional[dict] = None) -> str:
    """Unified diff of the current repo state vs the original baseline snapshot.

    Pass ``after`` (a precomputed snapshot) to avoid re-walking the repo.
    """
    if after is None:
        after = diffing.snapshot(state["repo_path"])
    return diffing.compute_diff(state.get("baseline_snapshot") or {}, after)


def sahadeva_judge(state: RunState) -> dict:
    """Judge stub (Sahadeva). Deterministic: approve iff the tests passed.

    Captures the worker's change diff into state so a real judge can review it
    without re-deriving it.
    """
    diff = change_diff(state)
    passed = bool(state["test_passed"])
    return {
        "judge_approved": passed,
        "judge_feedback": "" if passed else "stub: tests failing",
        "last_diff": diff,
    }


def _test_output_tail(state: RunState, limit: int = 2000) -> str:
    """Last `limit` chars of the test result's combined stdout/stderr."""
    result = state.get("last_test_result")
    stdout = getattr(result, "stdout", "") or ""
    stderr = getattr(result, "stderr", "") or ""
    combined = (stdout + stderr).strip()
    return combined[-limit:]


def make_sahadeva_judge(llm_client):
    """Build the real judge node (Sahadeva), binding an injected LLM client.

    Failing tests are rejected deterministically without spending tokens. When
    tests pass, an independent LLM reviews the cumulative diff against the
    acceptance criteria and checks any agent-written test for adequacy.

    Args:
        llm_client: An LLMClient (or compatible) with a complete(...) method.

    Returns:
        A LangGraph node function.
    """

    def sahadeva_judge_node(state: RunState) -> dict:
        after = diffing.snapshot(state["repo_path"])  # snapshot once, reuse
        per_iter = change_diff(state, after)

        # Don't spend tokens judging failing code.
        if not state["test_passed"]:
            feedback = "Tests are failing:\n" + _test_output_tail(state)
            new_failures = state.get("new_failures") or []
            regressions = state.get("regressions") or []
            if new_failures:
                feedback += "\nNew failures: " + ", ".join(new_failures)
            if regressions:
                feedback += "\nRegressions: " + ", ".join(regressions)
            return {
                "judge_approved": False,
                "judge_feedback": feedback,
                "last_diff": per_iter,
            }

        # No change at all cannot satisfy a fix task -> reject deterministically,
        # without an LLM call (and without needing the model env).
        cum = cumulative_diff(state, after)
        if cum.strip() == "":
            return {
                "judge_approved": False,
                "judge_feedback": (
                    "No change was made (empty diff); a fix task cannot be "
                    "satisfied without a change."
                ),
                "last_diff": per_iter,
            }

        model = os.getenv(JUDGE_MODEL_ENV)
        if not model:
            raise RuntimeError(
                f"Missing judge model: set the {JUDGE_MODEL_ENV} "
                "environment variable to a pinned model id."
            )

        brief = ResearchBrief.model_validate(state["research_brief"])
        criteria = "\n".join(f"- {c}" for c in brief.acceptance_criteria)

        # Tell the judge the TRUE test state: the regression gate tolerates
        # baseline failures, but a still-red task-relevant test means incomplete.
        result = state.get("last_test_result")
        per_test = getattr(result, "per_test", None) if result is not None else None
        current_failing = sorted(testresults.failures(per_test)) if per_test else []
        if not current_failing:
            test_status = "All tests currently pass."
        else:
            test_status = (
                "Tests still failing (pre-existing at baseline, tolerated by the "
                "regression gate): " + ", ".join(current_failing) + ". If any of "
                "these is relevant to the task or acceptance criteria, the change "
                "is INCOMPLETE."
            )

        messages = [
            {"role": "system", "content": _SAHADEVA_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"ACCEPTANCE CRITERIA:\n{criteria}\n\n"
                    f"Change under review (cumulative diff):\n{cum}\n\n"
                    f"{test_status}"
                ),
            },
        ]

        reply = llm_client.complete(
            messages, model=model, temperature=0.0, json_mode=True
        )

        try:
            parsed = json.loads(_strip_json_fences(reply))
            approved = bool(parsed["approved"])
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            return {
                "judge_approved": False,
                "judge_feedback": (
                    f"Review output was unparseable ({exc}); rejecting for safety."
                ),
                "last_diff": per_iter,
            }

        return {
            "judge_approved": approved,
            "judge_feedback": str(parsed.get("feedback", "")),
            "last_diff": per_iter,
        }

    return sahadeva_judge_node


def _failing_count(state: RunState) -> int:
    """Number of failing tests this pass (per-test when available, else 0/1)."""
    result = state.get("last_test_result")
    per_test = getattr(result, "per_test", None) if result is not None else None
    if per_test is not None:
        return len(testresults.failures(per_test))
    return 0 if state.get("test_passed") else 1


def _restore_snapshot(repo_path: str, snapshot: dict, current: dict) -> None:
    """Restore the repo on disk to ``snapshot``: rewrite its files and delete any
    file present now (in ``current``) that the snapshot does not contain.

    The deletion step handles files created in a worse iteration that the best
    attempt never had, so a restore leaves the repo exactly at the best state.
    """
    edits.apply_edits(
        repo_path,
        [{"path": p, "content": c} for p, c in snapshot.items()],
    )
    stray = [p for p in current if p not in snapshot]
    if stray:
        edits.delete_files(repo_path, stray)


def _better(candidate: dict, best: Optional[dict]) -> bool:
    """True if candidate is a strictly better attempt than best (lower is better).

    Compares new-failure count first, then total failing count; ties keep the
    best already held.
    """
    if best is None:
        return True
    if candidate["new_failures_count"] != best["new_failures_count"]:
        return candidate["new_failures_count"] < best["new_failures_count"]
    return candidate["failing_count"] < best["failing_count"]


def yudhishthira(state: RunState) -> dict:
    """Orchestrator decision node (Yudhishthira).

    Owns the iteration counter and the best-attempt record. Appends one trace
    record, updates the best attempt, then decides: converge on approval; else
    break early on oscillation (a repeated change+failure signature) or at the
    iteration cap; otherwise retry. On a non-converged exit it restores the repo
    on disk to the best attempt seen.
    """
    it = state["iteration"]
    max_iterations = state["max_iterations"]
    repo_path = state["repo_path"]

    # Snapshot the post-worker state once; reuse for the candidate and its diff.
    after = diffing.snapshot(repo_path)

    record = {
        "iteration": it,
        "test_passed": state["test_passed"],
        "judge_approved": state["judge_approved"],
        "judge_feedback": state.get("judge_feedback", ""),
        "diff": state.get("last_diff") or "",
        "regressions": list(state.get("regressions") or []),
        "new_failures": list(state.get("new_failures") or []),
        "newly_passing": list(state.get("newly_passing") or []),
    }
    updated_trace = state.get("trace", []) + [record]

    # Best-attempt tracking on every pass (lower failure counts are better).
    cand = {
        "iteration": it,
        "snapshot": after,
        "new_failures": list(state.get("new_failures") or []),
        "new_failures_count": len(state.get("new_failures") or []),
        "failing_count": _failing_count(state),
        "diff": cumulative_diff(state, after),
    }
    best = cand if _better(cand, state.get("best_attempt")) else state.get("best_attempt")

    if state["judge_approved"]:
        # Converged: the current on-disk state IS the result; do not restore.
        return {"status": "converged", "trace": updated_trace, "best_attempt": best}

    # Signature of this iteration: the change made + the set of new failures.
    # A repeated signature means we have been in this exact state before.
    sig = (
        state.get("last_diff") or "",
        tuple(sorted(state.get("new_failures") or [])),
    )
    seen = state.get("iteration_signatures") or []
    updated_signatures = seen + [sig]

    def _did_not_converge(reason: str) -> dict:
        result = {
            "status": "did_not_converge",
            "termination_reason": reason,
            "trace": updated_trace,
            "iteration_signatures": updated_signatures,
            "best_attempt": best,
        }
        # Restore the repo to the best attempt if it isn't the current one.
        if best is not None and best["iteration"] != it:
            _restore_snapshot(repo_path, best["snapshot"], after)
            result["last_diff"] = best["diff"]
            result["new_failures"] = best["new_failures"]
        return result

    if sig in seen:
        return _did_not_converge("oscillation")
    if it >= max_iterations:
        return _did_not_converge("cap")

    return {
        "status": "running",
        "iteration": it + 1,
        "trace": updated_trace,
        "iteration_signatures": updated_signatures,
        "best_attempt": best,
    }
