"""Tests for best-attempt tracking and on-disk restore in yudhishthira."""

import os

from pandavas.nodes import _better, yudhishthira


# --- _better unit --------------------------------------------------------------


def _attempt(new_failures_count, failing_count, iteration=1):
    return {
        "iteration": iteration,
        "snapshot": {},
        "new_failures": [],
        "new_failures_count": new_failures_count,
        "failing_count": failing_count,
        "diff": "",
    }


def test_better_none_best_is_always_better():
    assert _better(_attempt(5, 5), None) is True


def test_better_fewer_new_failures_wins():
    assert _better(_attempt(1, 9), _attempt(2, 0)) is True


def test_better_ties_on_new_failures_then_fewer_failing_wins():
    assert _better(_attempt(1, 1), _attempt(1, 2)) is True


def test_better_otherwise_false():
    assert _better(_attempt(2, 2), _attempt(1, 1)) is False
    assert _better(_attempt(1, 1), _attempt(1, 1)) is False  # equal -> keep best


# --- restore behavior ----------------------------------------------------------


def _base_state(repo, **overrides):
    state = {
        "repo_path": repo,
        "iteration": 3,
        "max_iterations": 3,
        "test_passed": False,
        "judge_approved": False,
        "judge_feedback": "nope",
        "last_test_result": None,
        "last_diff": "",
        "new_failures": ["x", "y"],  # current pass is WORSE than best (count 2 > 1)
        "trace": [],
        "iteration_signatures": [],
        "baseline_snapshot": {},
        "best_attempt": None,
    }
    state.update(overrides)
    return state


def test_cap_restores_disk_to_best_attempt(tmp_path):
    repo = str(tmp_path)
    (tmp_path / "calc.py").write_text("BAD", encoding="utf-8")

    best = {
        "iteration": 1,
        "snapshot": {"calc.py": "GOOD"},
        "new_failures": ["only-one"],
        "new_failures_count": 1,
        "failing_count": 1,
        "diff": "the good diff",
    }
    out = yudhishthira(_base_state(repo, best_attempt=best))

    assert out["status"] == "did_not_converge"
    assert out["termination_reason"] == "cap"
    # Disk restored to the best attempt's content.
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "GOOD"
    # Reported state reflects the restored best, not the worse last pass.
    assert out["best_attempt"]["iteration"] == 1
    assert out["last_diff"] == "the good diff"
    assert out["new_failures"] == ["only-one"]


def test_cap_restore_deletes_stray_files(tmp_path):
    # A file created in a worse iteration that the best snapshot never had must be
    # removed on restore, not left behind.
    repo = str(tmp_path)
    (tmp_path / "calc.py").write_text("BAD", encoding="utf-8")
    (tmp_path / "stray.py").write_text("created in a worse iteration", encoding="utf-8")

    best = {
        "iteration": 1,
        "snapshot": {"calc.py": "GOOD"},  # no stray.py
        "new_failures": ["only-one"],
        "new_failures_count": 1,
        "failing_count": 1,
        "diff": "the good diff",
    }
    out = yudhishthira(_base_state(repo, best_attempt=best))

    assert out["status"] == "did_not_converge"
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "GOOD"
    assert not (tmp_path / "stray.py").exists()  # stray file removed


def test_converged_does_not_restore_disk(tmp_path):
    repo = str(tmp_path)
    (tmp_path / "calc.py").write_text("CURRENT", encoding="utf-8")

    # A stale "best" from an earlier iteration must NOT overwrite a converged repo.
    best = {
        "iteration": 1,
        "snapshot": {"calc.py": "OLD"},
        "new_failures": [],
        "new_failures_count": 0,
        "failing_count": 0,
        "diff": "old diff",
    }
    out = yudhishthira(
        _base_state(
            repo,
            iteration=2,
            test_passed=True,
            judge_approved=True,
            new_failures=[],
            best_attempt=best,
        )
    )

    assert out["status"] == "converged"
    # Disk untouched: the converged content remains.
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "CURRENT"
