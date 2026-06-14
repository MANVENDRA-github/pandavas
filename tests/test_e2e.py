"""End-to-end test: red -> green with the real LocalExecutor and a file-editing
worker. The worker here is a hardcoded demo (not a real agent — that is P1)."""

import os
import shutil

from pandavas.executor import LocalExecutor
from pandavas.nodes import nakula_research, sahadeva_judge
from pandavas.orchestrator import run

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_buggy_repo")


def scripted_worker(state):
    """Demo worker: fix the bug in calc.py by replacing 'a - b' with 'a + b'.

    Iteration bookkeeping lives in the orchestrator now, so the worker only edits.
    """
    calc_path = os.path.join(state["repo_path"], "calc.py")
    with open(calc_path, "r", encoding="utf-8") as f:
        source = f.read()
    source = source.replace("a - b", "a + b")
    with open(calc_path, "w", encoding="utf-8") as f:
        f.write(source)
    return {}


def test_red_to_green_end_to_end(tmp_path):
    # Copy the pristine fixture so the committed version is never mutated.
    tmp_repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, tmp_repo)

    # Step 1 (RED): the unfixed repo fails its test.
    red = LocalExecutor().run_tests(tmp_repo)
    assert red.passed is False

    # Step 2: run the loop with the scripted file-editing worker (real executor).
    final = run(
        task="fix add",
        repo_path=tmp_repo,
        worker=scripted_worker,
        research=nakula_research,
        judge=sahadeva_judge,
    )

    # Step 3 (GREEN): the fix converged on the first iteration.
    assert final["status"] == "converged"
    assert final["last_test_result"].passed is True
    assert final["iteration"] == 1
    # The change diff was captured.
    assert final["last_diff"]
    assert "calc.py" in final["last_diff"]
