"""Tests for the real Sahadeva judge node (offline; fake LLMs injected)."""

import json
import os
import shutil

from pandavas import diffing
from pandavas.executor import LocalExecutor, TestResult
from pandavas.nodes import (
    arjuna_worker,
    make_arjuna_worker,
    make_nakula_research,
    make_sahadeva_judge,
    nakula_research,
)
from pandavas.orchestrator import run

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_buggy_repo"
)

FIX_CONTENT = "def add(a, b):\n    return a + b\n"


def _calc_line_count(repo: str) -> int:
    with open(os.path.join(repo, "calc.py"), "r", encoding="utf-8") as f:
        return len(f.read().splitlines())


def _brief_dict(repo: str) -> dict:
    n = _calc_line_count(repo)
    return {
        "task": "fix the add bug",
        "acceptance_criteria": ["add(2, 3) == 5"],
        "relevant_code": [
            {
                "path": "calc.py",
                "line_start": 1,
                "line_end": n,
                "snippet": "def add",
                "why": "the bug lives here",
            }
        ],
        "conventions": [],
        "integration_points": [],
        "constraints": [],
        "open_questions": [],
        "confidence": {},
    }


class FakeLLM:
    """Returns scripted replies; counts calls; never touches the network."""

    def __init__(self, replies):
        self._replies = list(replies)
        self._last = self._replies[-1] if self._replies else ""
        self.calls = 0

    def complete(
        self, messages, model, temperature=0.0, max_tokens=None, json_mode=False
    ) -> str:
        self.calls += 1
        if self._replies:
            return self._replies.pop(0)
        return self._last


def _judge_json(approved: bool, feedback: str) -> str:
    return json.dumps({"approved": approved, "feedback": feedback})


def _failing_state():
    return {
        "repo_path": FIXTURE,
        "research_brief": _brief_dict(FIXTURE),
        "test_passed": False,
        "last_test_result": TestResult(
            passed=False,
            exit_code=1,
            stdout="boom: assertion error",
            stderr="",
            command="pytest",
            duration_s=0.0,
        ),
        "baseline_snapshot": {},
        "pre_worker_snapshot": {},
    }


def _passing_state():
    # Baseline differs from the current repo, so the cumulative diff is non-empty
    # and the judge reaches the LLM review (not the empty-diff short-circuit).
    return {
        "repo_path": FIXTURE,
        "research_brief": _brief_dict(FIXTURE),
        "test_passed": True,
        "last_test_result": TestResult(
            passed=True, exit_code=0, stdout="ok", stderr="", command="pytest",
            duration_s=0.0,
        ),
        "baseline_snapshot": {"calc.py": "stale baseline content\n"},
        "pre_worker_snapshot": {},
    }


def test_failing_tests_short_circuit_without_llm(monkeypatch):
    monkeypatch.setenv("PANDAVAS_JUDGE_MODEL", "dummy-model")
    llm = FakeLLM([_judge_json(True, "")])

    out = make_sahadeva_judge(llm)(_failing_state())

    assert out["judge_approved"] is False
    assert "failing" in out["judge_feedback"].lower()
    assert llm.calls == 0  # the LLM was never consulted


def test_passing_tests_llm_approves(monkeypatch):
    monkeypatch.setenv("PANDAVAS_JUDGE_MODEL", "dummy-model")
    llm = FakeLLM([_judge_json(True, "")])

    out = make_sahadeva_judge(llm)(_passing_state())

    assert out["judge_approved"] is True
    assert llm.calls == 1


def test_passing_tests_llm_rejects_propagates_feedback(monkeypatch):
    monkeypatch.setenv("PANDAVAS_JUDGE_MODEL", "dummy-model")
    llm = FakeLLM([_judge_json(False, "vacuous test")])

    out = make_sahadeva_judge(llm)(_passing_state())

    assert out["judge_approved"] is False
    assert out["judge_feedback"] == "vacuous test"


def test_unparseable_llm_output_rejects_without_crash(monkeypatch):
    monkeypatch.setenv("PANDAVAS_JUDGE_MODEL", "dummy-model")
    llm = FakeLLM(["not json at all"])

    out = make_sahadeva_judge(llm)(_passing_state())

    assert out["judge_approved"] is False
    assert out["judge_feedback"]  # non-empty explanation


def test_integration_judge_veto_blocks_convergence(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-research-model")
    monkeypatch.setenv("PANDAVAS_WORKER_MODEL", "dummy-worker-model")
    monkeypatch.setenv("PANDAVAS_JUDGE_MODEL", "dummy-judge-model")

    repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, repo)

    research_llm = FakeLLM([json.dumps(_brief_dict(repo))])
    worker_llm = FakeLLM(
        [json.dumps({"files": [{"path": "calc.py", "content": FIX_CONTENT}],
                     "rationale": "fix"})]
    )
    # Judge always rejects, even though the worker makes the tests pass.
    judge_llm = FakeLLM([_judge_json(False, "not convinced")])

    final = run(
        task="fix the add bug",
        repo_path=repo,
        max_iterations=2,
        executor=LocalExecutor(),
        research=make_nakula_research(research_llm),
        worker=make_arjuna_worker(worker_llm),
        judge=make_sahadeva_judge(judge_llm),
    )

    # Tests pass but the judge vetoes -> tests-pass is necessary, not sufficient.
    assert final["status"] == "did_not_converge"
    assert final["last_test_result"].passed is True


def test_empty_diff_rejects_without_llm():
    # No change made (baseline equals current) -> deterministic reject, no LLM,
    # no model env required.
    state = {
        "repo_path": FIXTURE,
        "research_brief": _brief_dict(FIXTURE),
        "test_passed": True,
        "last_test_result": TestResult(
            passed=True, exit_code=0, stdout="ok", stderr="", command="pytest",
            duration_s=0.0,
        ),
        "baseline_snapshot": diffing.snapshot(FIXTURE),  # equals current
        "pre_worker_snapshot": {},
    }
    llm = FakeLLM([_judge_json(True, "approve")])

    out = make_sahadeva_judge(llm)(state)

    assert out["judge_approved"] is False
    assert llm.calls == 0  # LLM never consulted
    assert "no change" in out["judge_feedback"].lower()


def test_no_op_worker_does_not_converge_via_empty_diff(tmp_path):
    # Headline fix: a repo whose bug test fails at baseline. The no-op worker
    # makes no change -> empty diff -> the judge rejects every iteration, so the
    # run does NOT converge despite the regression gate tolerating the baseline
    # failure. (No LLM call: empty-diff reject is deterministic.)
    repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, repo)

    judge_llm = FakeLLM([_judge_json(True, "should never be used")])

    final = run(
        task="fix the add bug",
        repo_path=repo,
        max_iterations=3,
        executor=LocalExecutor(),
        research=nakula_research,
        worker=arjuna_worker,
        judge=make_sahadeva_judge(judge_llm),
    )

    assert final["status"] == "did_not_converge"
    assert judge_llm.calls == 0
