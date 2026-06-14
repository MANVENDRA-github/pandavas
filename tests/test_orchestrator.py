"""Tests for the P0 orchestrator skeleton.

Every test injects a FakeExecutor so no real repo or subprocess is touched and
LocalExecutor is never used.
"""

from pandavas.executor import Executor, TestResult
from pandavas.nodes import arjuna_worker, nakula_research, sahadeva_judge
from pandavas.orchestrator import run


class FakeExecutor(Executor):
    """In-memory Executor that returns a fixed pass/fail without a subprocess."""

    def __init__(self, passed: bool):
        self.passed = passed
        self.calls = 0

    def run_tests(self, repo_path, test_command=None) -> TestResult:
        self.calls += 1
        return TestResult(
            passed=self.passed,
            exit_code=0 if self.passed else 1,
            stdout="",
            stderr="",
            command=test_command or "fake",
            duration_s=0.0,
        )


class CyclingFailExecutor(Executor):
    """Fails every call, but reports a DIFFERENT failing test id each time.

    The first call is the baseline (no failures); each later call introduces a
    distinct new failure so iteration signatures never repeat -> no oscillation.
    """

    def __init__(self):
        self.calls = 0

    def run_tests(self, repo_path, test_command=None) -> TestResult:
        self.calls += 1
        per_test = {} if self.calls == 1 else {f"t{self.calls}": "failed"}
        return TestResult(
            passed=False,
            exit_code=1,
            stdout="",
            stderr="",
            command="pytest",
            duration_s=0.0,
            per_test=per_test,
        )


def test_converges_when_tests_pass():
    fake = FakeExecutor(passed=True)
    final = run(
        "task",
        "/repo",
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )
    assert final["status"] == "converged"
    assert final["iteration"] == 1
    assert len(final["trace"]) == 1
    assert final["termination_reason"] is None


def test_oscillation_breaks_early_before_cap():
    # No-op worker + always-failing executor -> identical signature each pass
    # (empty diff, empty new_failures) -> oscillation on the 2nd occurrence.
    fake = FakeExecutor(passed=False)
    final = run(
        "task",
        "/repo",
        max_iterations=3,
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )
    assert final["status"] == "did_not_converge"
    assert final["termination_reason"] == "oscillation"
    assert final["iteration"] == 2  # broke before the cap
    assert len(final["trace"]) == 2


def test_cap_when_signatures_differ_each_iteration():
    # Distinct new_failures each iteration -> no oscillation -> runs to the cap.
    fake = CyclingFailExecutor()
    final = run(
        "task",
        "/repo",
        max_iterations=3,
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )
    assert final["status"] == "did_not_converge"
    assert final["termination_reason"] == "cap"
    assert final["iteration"] == 3
    assert len(final["trace"]) == 3


def test_research_brief_is_stub_placeholder_after_run():
    fake = FakeExecutor(passed=True)
    final = run(
        "task",
        "/repo",
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )
    assert final["research_brief"]  # not empty
    assert final["research_brief"].get("stub") is True


def test_local_executor_not_used_when_fake_injected():
    fake = FakeExecutor(passed=True)
    run(
        "task",
        "/repo",
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
        judge=sahadeva_judge,
    )
    # The fake was actually exercised (baseline run + one iteration), proving no
    # LocalExecutor/subprocess ran.
    assert fake.calls >= 1
