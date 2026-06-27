"""Tests for the deterministic verb spine (skill mode). All keyless, no network.

Each verb is invoked through the real CLI entrypoint (`main([...])`) so argument
parsing + dispatch are exercised too. The executor is faked where deterministic
per-test results matter; git verbs use a real local repo.
"""

import json
import os
import subprocess
import sys

import pytest

from pandavas import spine
from pandavas.cli import main
from pandavas.executor import Executor, TestResult

STATE = ".pandavas"


# --- helpers -------------------------------------------------------------------


def _out(capsys) -> dict:
    """Parse the last stdout line as JSON (and assert it is pure ASCII)."""
    captured = capsys.readouterr()
    text = captured.out.strip()
    assert text, f"no stdout (stderr={captured.err!r})"
    text.encode("ascii")  # stdout must be ASCII-only (Windows-first)
    return json.loads(text.splitlines()[-1])


def _err(capsys) -> str:
    return capsys.readouterr().err


def _read(repo, *parts):
    with open(os.path.join(repo, STATE, *parts), "r", encoding="utf-8") as f:
        return json.load(f)


class _FakeExec(Executor):
    """Returns a controllable TestResult without running anything."""

    def __init__(self):
        self.per_test = None
        self.passed = True
        self.exit_code = 0

    def run_tests(self, repo_path, test_command=None) -> TestResult:
        return TestResult(
            passed=self.passed,
            exit_code=self.exit_code,
            stdout="",
            stderr="",
            command="pytest",
            duration_s=0.0,
            per_test=self.per_test,
        )


def _use_fake(monkeypatch) -> _FakeExec:
    fake = _FakeExec()
    monkeypatch.setattr(spine, "LocalExecutor", lambda junit_xml=None: fake)
    return fake


def _git_init(repo):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)


def _seed(repo, *, iteration=1, max_iterations=6, signatures=None, best=None,
          test_passed=True, new_failures=None, failing_count=0,
          baseline=None, pre_iter=None):
    """Write a minimal, consistent .pandavas/ state for decide/judge-gate tests."""
    repo = str(repo)
    sd = os.path.join(repo, STATE)
    os.makedirs(os.path.join(sd, "snapshots"), exist_ok=True)
    os.makedirs(os.path.join(sd, "diffs"), exist_ok=True)

    def w(rel, data):
        with open(os.path.join(sd, rel), "w", encoding="utf-8") as f:
            json.dump(data, f)

    w("loop.json", {
        "version": 1, "task": "t", "repo_path": repo, "iteration": iteration,
        "max_iterations": max_iterations, "status": "running",
        "termination_reason": None, "iteration_signatures": signatures or [],
        "best_attempt": best, "trace": [], "updated_at": "x",
    })
    w("last_test.json", {
        "version": 1, "test_passed": test_passed,
        "exit_code": 0 if test_passed else 1, "command": "pytest",
        "duration_s": 0.0, "regressions": [], "new_failures": new_failures or [],
        "newly_passing": [], "failing_count": failing_count, "per_test": None,
    })
    base = baseline if baseline is not None else {}
    w(os.path.join("snapshots", "baseline.json"), base)
    w(os.path.join("snapshots", "pre_iter.json"),
      pre_iter if pre_iter is not None else base)


# --- detect-test ---------------------------------------------------------------


def test_detect_test_finds_pytest(tmp_path, capsys):
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    code = main(["detect-test", "--repo", str(tmp_path)])
    assert code == 0
    assert _out(capsys)["test_command"] == "pytest"


def test_detect_test_none_exits_1(tmp_path, capsys):
    code = main(["detect-test", "--repo", str(tmp_path)])
    assert code == 1
    assert _out(capsys)["test_command"] is None


# --- baseline ------------------------------------------------------------------


def test_baseline_writes_state_and_git_exclude(tmp_path, capsys, monkeypatch):
    repo = tmp_path
    (repo / "a.txt").write_text("hello\n", encoding="utf-8")
    _git_init(str(repo))
    fake = _use_fake(monkeypatch)
    fake.per_test = {"t1": "failed"}
    fake.passed = False

    code = main(["baseline", "--repo", str(repo), "--task", "fix it",
                 "--test-command", "pytest"])
    data = _out(capsys)

    assert code == 0
    assert data["baseline_passed"] is False
    assert data["baseline_failures"] == ["t1"]
    assert data["git_excluded"] is True
    loop = _read(str(repo), "loop.json")
    assert loop["iteration"] == 1 and loop["status"] == "running"
    # .pandavas/ is locally excluded so a later commit never stages it.
    exclude = (repo / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert ".pandavas/" in exclude.splitlines()


def test_baseline_refuses_to_clobber_without_force(tmp_path, capsys, monkeypatch):
    repo = tmp_path
    _use_fake(monkeypatch)
    main(["baseline", "--repo", str(repo), "--task", "t", "--test-command", "pytest"])
    capsys.readouterr()
    code = main(["baseline", "--repo", str(repo), "--task", "t",
                 "--test-command", "pytest"])
    assert code == 1
    assert "force" in _err(capsys).lower()


def test_baseline_no_test_command_clean_error(tmp_path, capsys):
    # Empty repo, no override -> clean JSON error to stderr, no traceback, exit 1.
    code = main(["baseline", "--repo", str(tmp_path), "--task", "t"])
    err = _err(capsys)
    assert code == 1
    assert "error" in err and "Traceback" not in err


# --- resolve-brief -------------------------------------------------------------


def _write_brief(repo, anchors):
    brief = {
        "task": "t", "acceptance_criteria": ["c"], "relevant_code": anchors,
        "conventions": [], "integration_points": [], "constraints": [],
        "open_questions": [], "confidence": {},
    }
    os.makedirs(os.path.join(repo, STATE), exist_ok=True)
    with open(os.path.join(repo, STATE, "brief.json"), "w", encoding="utf-8") as f:
        json.dump(brief, f)


def test_resolve_brief_ok(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    _write_brief(str(tmp_path), [
        {"path": "calc.py", "line_start": 1, "line_end": 2, "snippet": "x", "why": "y"}
    ])
    code = main(["resolve-brief", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 0 and data["resolved"] is True and data["failures"] == []


def test_resolve_brief_dangling_anchor(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    _write_brief(str(tmp_path), [
        {"path": "calc.py", "line_start": 1, "line_end": 999, "snippet": "x", "why": "y"}
    ])
    code = main(["resolve-brief", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 1 and data["resolved"] is False and data["failures"]


def test_resolve_brief_path_escape_rejected(tmp_path, capsys):
    _write_brief(str(tmp_path), [
        {"path": "../secret.py", "line_start": 1, "line_end": 1, "snippet": "x", "why": "y"}
    ])
    code = main(["resolve-brief", "--repo", str(tmp_path)])
    assert code == 1 and _out(capsys)["resolved"] is False


# --- apply-edits ---------------------------------------------------------------


def test_apply_edits_writes_and_rejects_escape(tmp_path, capsys):
    edits = [
        {"path": "src/new.py", "content": "x = 1\n"},
        {"path": "../escape.py", "content": "bad"},
    ]
    p = tmp_path / "edits.json"
    p.write_text(json.dumps(edits), encoding="utf-8")
    code = main(["apply-edits", "--repo", str(tmp_path), "--edits", str(p)])
    data = _out(capsys)
    assert code == 1  # a rejection occurred
    assert data["written"] == ["src/new.py"]
    assert data["rejected"] == ["../escape.py"]
    assert (tmp_path / "src" / "new.py").read_text(encoding="utf-8") == "x = 1\n"


# --- run-tests (regression-aware verdict) --------------------------------------


def _baseline_with(repo, fake, per_test, *, passed, capsys):
    fake.per_test = per_test
    fake.passed = passed
    fake.exit_code = 0 if passed else 1
    main(["baseline", "--repo", str(repo), "--task", "t", "--test-command", "pytest"])
    capsys.readouterr()


def test_run_tests_tolerates_preexisting_failure(tmp_path, capsys, monkeypatch):
    fake = _use_fake(monkeypatch)
    _baseline_with(tmp_path, fake, {"t1": "passed", "t2": "failed"},
                   passed=False, capsys=capsys)
    # Same failures as baseline -> no NEW failures -> tolerated.
    fake.per_test = {"t1": "passed", "t2": "failed"}
    code = main(["run-tests", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 0 and data["test_passed"] is True and data["new_failures"] == []


def test_run_tests_detects_regression(tmp_path, capsys, monkeypatch):
    fake = _use_fake(monkeypatch)
    _baseline_with(tmp_path, fake, {"t1": "passed", "t2": "failed"},
                   passed=False, capsys=capsys)
    fake.per_test = {"t1": "failed", "t2": "failed"}  # t1 regressed
    code = main(["run-tests", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 1 and data["test_passed"] is False
    assert data["regressions"] == ["t1"]


def test_run_tests_reports_newly_passing_red_to_green(tmp_path, capsys, monkeypatch):
    fake = _use_fake(monkeypatch)
    _baseline_with(tmp_path, fake, {"t1": "passed", "t2": "failed"},
                   passed=False, capsys=capsys)
    fake.per_test = {"t1": "passed", "t2": "passed"}  # t2 fixed
    code = main(["run-tests", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 0 and data["newly_passing"] == ["t2"]
    assert _read(str(tmp_path), "last_test.json")["failing_count"] == 0


# --- diff ----------------------------------------------------------------------


def test_diff_cumulative_lists_changed_file(tmp_path, capsys, monkeypatch):
    repo = tmp_path
    (repo / "calc.py").write_text("a\n", encoding="utf-8")
    _use_fake(monkeypatch)
    main(["baseline", "--repo", str(repo), "--task", "t", "--test-command", "pytest"])
    capsys.readouterr()
    (repo / "calc.py").write_text("b\n", encoding="utf-8")

    code = main(["diff", "--repo", str(repo)])
    data = _out(capsys)
    assert code == 0 and data["changed_files"] == ["calc.py"] and data["n_changed"] == 1
    assert os.path.isfile(os.path.join(str(repo), STATE, "diffs", "cumulative.diff"))


# --- judge-gate ----------------------------------------------------------------


def test_judge_gate_rejects_failing_tests(tmp_path, capsys):
    _seed(tmp_path, test_passed=False, new_failures=["t1"])
    os.makedirs(os.path.join(str(tmp_path), STATE), exist_ok=True)
    code = main(["judge-gate", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 30 and data["gate"] == "reject" and data["reason"] == "failing_tests"


def test_judge_gate_rejects_empty_diff(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("same\n", encoding="utf-8")
    _seed(tmp_path, test_passed=True, baseline={"calc.py": "same\n"})
    code = main(["judge-gate", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 30 and data["reason"] == "empty_diff"


def test_judge_gate_review_when_passing_and_changed(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("new\n", encoding="utf-8")
    _seed(tmp_path, test_passed=True, baseline={"calc.py": "old\n"})
    code = main(["judge-gate", "--repo", str(tmp_path)])
    data = _out(capsys)
    assert code == 0 and data["gate"] == "review"


# --- decide (loop control) -----------------------------------------------------


def test_decide_converges_on_approval(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("new\n", encoding="utf-8")
    _seed(tmp_path, baseline={"calc.py": "old\n"})
    code = main(["decide", "--repo", str(tmp_path), "--approved", "true"])
    data = _out(capsys)
    assert code == 0 and data["status"] == "converged"
    assert _read(str(tmp_path), "loop.json")["status"] == "converged"


def test_decide_continues_below_cap(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("new\n", encoding="utf-8")
    _seed(tmp_path, iteration=1, max_iterations=6, baseline={"calc.py": "old\n"})
    code = main(["decide", "--repo", str(tmp_path), "--approved", "false",
                 "--feedback", "try again"])
    data = _out(capsys)
    assert code == 10 and data["status"] == "running" and data["iteration"] == 2
    assert _read(str(tmp_path), "loop.json")["iteration"] == 2


def test_decide_stops_at_cap(tmp_path, capsys):
    (tmp_path / "calc.py").write_text("changed\n", encoding="utf-8")
    _seed(tmp_path, iteration=2, max_iterations=2, baseline={"calc.py": "old\n"})
    code = main(["decide", "--repo", str(tmp_path), "--approved", "false"])
    data = _out(capsys)
    assert code == 20 and data["termination_reason"] == "cap"


def test_decide_detects_oscillation(tmp_path, capsys):
    # No change -> identical (empty diff, no new failures) signature twice.
    (tmp_path / "a.txt").write_text("x\n", encoding="utf-8")
    _seed(tmp_path, iteration=1, max_iterations=9, baseline={"a.txt": "x\n"})
    assert main(["decide", "--repo", str(tmp_path), "--approved", "false"]) == 10
    capsys.readouterr()
    code = main(["decide", "--repo", str(tmp_path), "--approved", "false"])
    data = _out(capsys)
    assert code == 20 and data["termination_reason"] == "oscillation"


def test_decide_restores_best_attempt_at_cap(tmp_path, capsys):
    repo = str(tmp_path)
    # Best (iteration 1) had zero new failures; current (iteration 2) is worse.
    _seed(repo, iteration=2, max_iterations=2, baseline={"calc.py": "orig\n"},
          best={"iteration": 1, "new_failures": [], "new_failures_count": 0,
                "failing_count": 0, "diff": "d"},
          test_passed=False, new_failures=["x"], failing_count=1)
    # The recorded best snapshot, and a worse working tree with a stray file.
    with open(os.path.join(repo, STATE, "snapshots", "best.json"), "w",
              encoding="utf-8") as f:
        json.dump({"calc.py": "GOOD\n"}, f)
    (tmp_path / "calc.py").write_text("WORSE\n", encoding="utf-8")
    (tmp_path / "stray.txt").write_text("junk\n", encoding="utf-8")

    code = main(["decide", "--repo", repo, "--approved", "false"])
    data = _out(capsys)

    assert code == 20 and data["restored_best"] is True
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "GOOD\n"
    assert not (tmp_path / "stray.txt").exists()  # stray removed on restore


# --- restore -------------------------------------------------------------------


def test_restore_to_baseline(tmp_path, capsys):
    repo = str(tmp_path)
    os.makedirs(os.path.join(repo, STATE, "snapshots"), exist_ok=True)
    with open(os.path.join(repo, STATE, "snapshots", "baseline.json"), "w",
              encoding="utf-8") as f:
        json.dump({"calc.py": "orig\n"}, f)
    (tmp_path / "calc.py").write_text("messed up\n", encoding="utf-8")

    code = main(["restore", "--repo", repo, "--to", "baseline"])
    assert code == 0 and _out(capsys)["restored"] == "baseline"
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "orig\n"


def test_restore_missing_snapshot_errors(tmp_path, capsys):
    code = main(["restore", "--repo", str(tmp_path), "--to", "best"])
    assert code == 1 and "error" in _err(capsys)


# --- commit --------------------------------------------------------------------


def test_commit_creates_branch(tmp_path, capsys):
    repo = tmp_path
    (repo / "calc.py").write_text("x = 1\n", encoding="utf-8")
    _git_init(str(repo))
    subprocess.run(["git", "add", "-A"], cwd=str(repo), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(repo), check=True)
    (repo / "calc.py").write_text("x = 2\n", encoding="utf-8")

    code = main(["commit", "--repo", str(repo), "--task", "tweak x"])
    data = _out(capsys)
    assert code == 0 and data["committed"] is True
    assert data["branch"] == "pandavas/tweak-x"


def test_commit_non_git_repo_reports_error(tmp_path, capsys):
    code = main(["commit", "--repo", str(tmp_path), "--task", "x"])
    data = _out(capsys)
    assert code == 1 and data["committed"] is False


# --- constraints ---------------------------------------------------------------


def test_repo_snapshot_excludes_state_dir(tmp_path):
    (tmp_path / "real.py").write_text("code\n", encoding="utf-8")
    os.makedirs(os.path.join(str(tmp_path), STATE), exist_ok=True)
    (tmp_path / STATE / "loop.json").write_text("{}", encoding="utf-8")

    snap = spine._repo_snapshot(str(tmp_path))
    assert "real.py" in snap
    assert not any(k == STATE or k.startswith(STATE + "/") for k in snap)
