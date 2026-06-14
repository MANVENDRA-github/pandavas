"""Tests for the real Arjuna worker node (offline; fake LLMs injected)."""

import json
import os
import shutil

from pandavas.executor import LocalExecutor
from pandavas.nodes import make_arjuna_worker, make_nakula_research
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


def _research_json(repo: str) -> str:
    return json.dumps(_brief_dict(repo))


def _worker_json(path: str, content: str) -> str:
    return json.dumps(
        {"files": [{"path": path, "content": content}], "rationale": "fix add"}
    )


class FakeLLM:
    """Returns scripted replies; never touches the network."""

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


def _copy_fixture(tmp_path) -> str:
    repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, repo)
    return repo


def _state(repo: str) -> dict:
    return {
        "repo_path": repo,
        "task": "fix the add bug",
        "research_brief": _brief_dict(repo),
        "judge_feedback": "",
    }


def test_arjuna_applies_fix_to_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAVAS_WORKER_MODEL", "dummy-model")
    repo = _copy_fixture(tmp_path)
    llm = FakeLLM([_worker_json("calc.py", FIX_CONTENT)])

    out = make_arjuna_worker(llm)(_state(repo))

    assert out == {}
    on_disk = (tmp_path / "repo" / "calc.py").read_text(encoding="utf-8")
    assert "a + b" in on_disk
    assert "a - b" not in on_disk


def test_arjuna_path_safety_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAVAS_WORKER_MODEL", "dummy-model")
    repo = _copy_fixture(tmp_path)
    llm = FakeLLM([_worker_json("../evil.py", "pwn\n")])

    out = make_arjuna_worker(llm)(_state(repo))

    assert out == {}
    # Nothing written outside the repo.
    assert not (tmp_path / "evil.py").exists()


def test_arjuna_bad_output_applies_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAVAS_WORKER_MODEL", "dummy-model")
    repo = _copy_fixture(tmp_path)
    llm = FakeLLM(["this is not json"])

    out = make_arjuna_worker(llm)(_state(repo))

    assert out == {}
    # calc.py left untouched (still buggy).
    on_disk = (tmp_path / "repo" / "calc.py").read_text(encoding="utf-8")
    assert "a - b" in on_disk


def test_capstone_real_nakula_arjuna_executor_flip_red_to_green(tmp_path, monkeypatch):
    monkeypatch.setenv("PANDAVAS_RESEARCH_MODEL", "dummy-research-model")
    monkeypatch.setenv("PANDAVAS_WORKER_MODEL", "dummy-worker-model")
    repo = _copy_fixture(tmp_path)

    research_llm = FakeLLM([_research_json(repo)])
    worker_llm = FakeLLM([_worker_json("calc.py", FIX_CONTENT)])

    final = run(
        task="fix the add bug",
        repo_path=repo,
        executor=LocalExecutor(),
        research=make_nakula_research(research_llm),
        worker=make_arjuna_worker(worker_llm),
    )

    assert final["status"] == "converged"
    assert final["last_test_result"].passed is True
    assert final["iteration"] == 1
