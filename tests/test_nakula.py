"""Tests for the real Nakula research node (offline; a fake LLM is injected)."""

import json
import os

from pandavas.brief import ResearchBrief, resolve_brief
from pandavas.executor import Executor, TestResult
from pandavas.nodes import arjuna_worker, make_nakula_research, sahadeva_judge
from pandavas.orchestrator import run

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_buggy_repo"
)


def _calc_line_count() -> int:
    with open(os.path.join(FIXTURE, "calc.py"), "r", encoding="utf-8") as f:
        return len(f.read().splitlines())


def _anchor(path: str, line_start: int, line_end: int) -> dict:
    return {
        "path": path,
        "line_start": line_start,
        "line_end": line_end,
        "snippet": "def add",
        "why": "the bug lives here",
    }


def _brief_json(anchor: dict) -> str:
    return json.dumps(
        {
            "task": "fix the add bug",
            "acceptance_criteria": ["add(2, 3) == 5"],
            "relevant_code": [anchor],
            "conventions": [],
            "integration_points": [],
            "constraints": [],
            "open_questions": [],
            "confidence": {},
        }
    )


class FakeLLM:
    """Returns scripted JSON replies; never touches the network."""

    def __init__(self, replies):
        self._replies = list(replies)
        self._last = self._replies[-1]
        self.calls = 0

    def complete(
        self, messages, model, temperature=0.0, max_tokens=None, json_mode=False
    ) -> str:
        self.calls += 1
        if self._replies:
            return self._replies.pop(0)
        return self._last


class FakeExecutor(Executor):
    """In-memory executor for the integration test."""

    def __init__(self, passed: bool):
        self.passed = passed

    def run_tests(self, repo_path, test_command=None) -> TestResult:
        return TestResult(
            passed=self.passed,
            exit_code=0 if self.passed else 1,
            stdout="",
            stderr="",
            command="fake",
            duration_s=0.0,
        )


def _state():
    return {"repo_path": FIXTURE, "task": "fix the add bug"}


def test_nakula_success_returns_resolvable_brief(monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-model")
    n = _calc_line_count()
    llm = FakeLLM([_brief_json(_anchor("calc.py", 1, n))])

    out = make_nakula_research(llm)(_state())

    assert "research_brief" in out
    assert out.get("status") != "research_failed"
    brief = ResearchBrief(**out["research_brief"])
    assert resolve_brief(brief, FIXTURE) == []


def test_nakula_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-model")
    n = _calc_line_count()
    llm = FakeLLM(
        [
            _brief_json(_anchor("nope.py", 1, 1)),  # dangling -> retry
            _brief_json(_anchor("calc.py", 1, n)),  # resolvable -> success
        ]
    )

    out = make_nakula_research(llm)(_state())

    assert "research_brief" in out
    assert out.get("status") != "research_failed"
    assert llm.calls == 2


def test_nakula_fails_after_exhausting_retries(monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-model")
    llm = FakeLLM([_brief_json(_anchor("nope.py", 1, 1))])  # always dangling

    # Default max_retries=2 -> 1 + 2 = 3 attempts.
    out = make_nakula_research(llm)(_state())

    assert out["status"] == "research_failed"
    assert out["research_error"]
    assert llm.calls == 3


def test_nakula_integration_converges_in_graph(monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-model")
    n = _calc_line_count()
    llm = FakeLLM([_brief_json(_anchor("calc.py", 1, n))])

    final = run(
        task="fix the add bug",
        repo_path=FIXTURE,
        executor=FakeExecutor(passed=True),
        research=make_nakula_research(llm),
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )

    assert final["status"] == "converged"
    assert final["research_brief"]
    brief = ResearchBrief(**final["research_brief"])
    assert resolve_brief(brief, FIXTURE) == []
