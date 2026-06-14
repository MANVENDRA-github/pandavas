"""Tests for the P0 orchestrator skeleton.

Every test injects a FakeExecutor so no real repo or subprocess is touched and
LocalExecutor is never used.
"""

from pandavas.executor import Executor, TestResult
from pandavas.nodes import arjuna_worker, nakula_research
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


def test_converges_when_tests_pass():
    fake = FakeExecutor(passed=True)
    final = run(
        "task", "/repo", executor=fake, research=nakula_research, worker=arjuna_worker
    )
    assert final["status"] == "converged"
    assert final["iteration"] == 1
    assert len(final["trace"]) == 1


def test_does_not_converge_when_tests_always_fail():
    fake = FakeExecutor(passed=False)
    final = run(
        "task",
        "/repo",
        max_iterations=3,
        executor=fake,
        research=nakula_research,
        worker=arjuna_worker,
    )
    assert final["status"] == "did_not_converge"
    assert final["iteration"] == 3
    assert len(final["trace"]) == 3


def test_research_brief_is_stub_placeholder_after_run():
    fake = FakeExecutor(passed=True)
    final = run(
        "task", "/repo", executor=fake, research=nakula_research, worker=arjuna_worker
    )
    assert final["research_brief"]  # not empty
    assert final["research_brief"].get("stub") is True


def test_local_executor_not_used_when_fake_injected():
    fake = FakeExecutor(passed=True)
    run("task", "/repo", executor=fake, research=nakula_research, worker=arjuna_worker)
    # The fake was actually exercised, proving no LocalExecutor/subprocess ran.
    assert fake.calls == 1
