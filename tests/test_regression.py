"""Tests for per-test results in the executor and the regression-aware gate."""

import os
import shutil
import sys

from pandavas.executor import Executor, LocalExecutor, TestResult
from pandavas.nodes import make_bhima_test, nakula_research, sahadeva_judge
from pandavas.orchestrator import run
from pandavas.testresults import failures, passed

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_buggy_repo"
)


# --- Executor: per-test parsing ------------------------------------------------


def test_executor_per_test_parses_pass_and_fail(tmp_path):
    (tmp_path / "test_sample.py").write_text(
        "def test_pass():\n    assert True\n\n\ndef test_fail():\n    assert False\n",
        encoding="utf-8",
    )
    result = LocalExecutor().run_tests(str(tmp_path), test_command="pytest")

    assert result.per_test is not None
    assert len(passed(result.per_test)) == 1
    assert len(failures(result.per_test)) == 1


def test_executor_non_pytest_command_has_no_per_test(tmp_path):
    cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    result = LocalExecutor().run_tests(str(tmp_path), test_command=cmd)

    assert result.per_test is None


def test_executor_explicit_junit_xml_enables_per_test_for_any_command(tmp_path):
    # Simulate a non-pytest framework that emits its own JUnit XML.
    (tmp_path / "results.xml").write_text(
        '<testsuite name="s">'
        '<testcase classname="x" name="t1"/>'
        '<testcase classname="x" name="t2"><failure/></testcase>'
        "</testsuite>",
        encoding="utf-8",
    )
    cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'  # not pytest
    result = LocalExecutor(junit_xml="results.xml").run_tests(
        str(tmp_path), test_command=cmd
    )

    assert result.per_test is not None
    assert len(passed(result.per_test)) == 1
    assert len(failures(result.per_test)) == 1
    # The user's JUnit file is not deleted (only our temp file would be).
    assert (tmp_path / "results.xml").exists()


# --- Bhima gate (unit) ---------------------------------------------------------


class FakePerTestExecutor(Executor):
    """Returns a fixed per_test dict without running anything."""

    def __init__(self, per_test, passed_flag=True):
        self._per_test = per_test
        self._passed = passed_flag

    def run_tests(self, repo_path, test_command=None) -> TestResult:
        return TestResult(
            passed=self._passed,
            exit_code=0 if self._passed else 1,
            stdout="",
            stderr="",
            command="pytest",
            duration_s=0.0,
            per_test=self._per_test,
        )


def _bhima_state(baseline):
    return {
        "repo_path": "/repo",
        "test_command": "pytest",
        "baseline_test_results": baseline,
    }


def test_gate_tolerates_preexisting_failure():
    baseline = {"t1": "passed", "t2": "failed"}
    executor = FakePerTestExecutor({"t1": "passed", "t2": "failed"})

    out = make_bhima_test(executor)(_bhima_state(baseline))

    assert out["test_passed"] is True
    assert out["new_failures"] == []
    assert out["regressions"] == []


def test_gate_detects_regression():
    baseline = {"t1": "passed", "t2": "failed"}
    executor = FakePerTestExecutor({"t1": "failed", "t2": "failed"}, passed_flag=False)

    out = make_bhima_test(executor)(_bhima_state(baseline))

    assert out["test_passed"] is False
    assert out["regressions"] == ["t1"]


def test_gate_reports_newly_passing_red_to_green():
    # t2 was failing at baseline and is green now -> red->green proof.
    baseline = {"t1": "passed", "t2": "failed"}
    executor = FakePerTestExecutor({"t1": "passed", "t2": "passed"})

    out = make_bhima_test(executor)(_bhima_state(baseline))

    assert out["test_passed"] is True
    assert out["newly_passing"] == ["t2"]


# --- Headline integration ------------------------------------------------------


def _scripted_worker(state):
    """Fix only calc.py; leave the pre-existing failing test alone."""
    calc_path = os.path.join(state["repo_path"], "calc.py")
    with open(calc_path, "r", encoding="utf-8") as f:
        source = f.read()
    source = source.replace("a - b", "a + b")
    with open(calc_path, "w", encoding="utf-8") as f:
        f.write(source)
    return {}


def test_converges_despite_preexisting_failure(tmp_path):
    repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, repo)
    # Add a SEPARATE pre-existing always-failing test (failing at baseline too).
    with open(os.path.join(repo, "test_preexisting.py"), "w", encoding="utf-8") as f:
        f.write("def test_always_fails():\n    assert False\n")

    final = run(
        task="fix add",
        repo_path=repo,
        executor=LocalExecutor(),
        research=nakula_research,
        worker=_scripted_worker,
        judge=sahadeva_judge,
    )

    # The repro/bug test passes; the pre-existing failure is tolerated.
    assert final["status"] == "converged"
    assert final["new_failures"] == []
