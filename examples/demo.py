"""Standalone demo: a real red -> green fix on the sample fixture.

Run with `python examples/demo.py`. The worker here is a scripted demo (it
hardcodes the fix), NOT a real agent — the real worker arrives in P1.
"""

import shutil
import tempfile
from pathlib import Path

from pandavas.executor import LocalExecutor
from pandavas.orchestrator import run

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "sample_buggy_repo"


def scripted_worker(state):
    """Demo worker: fix calc.py by replacing 'a - b' with 'a + b'.

    Iteration bookkeeping lives in the orchestrator now, so the worker only edits.
    """
    calc_path = Path(state["repo_path"]) / "calc.py"
    source = calc_path.read_text(encoding="utf-8")
    source = source.replace("a - b", "a + b")
    calc_path.write_text(source, encoding="utf-8")
    return {}


def main() -> None:
    tmp_repo = Path(tempfile.mkdtemp()) / "repo"
    shutil.copytree(FIXTURE, tmp_repo)
    print(f"[demo] copied sample repo to {tmp_repo}")

    print("[demo] BEFORE: running tests...")
    red = LocalExecutor().run_tests(str(tmp_repo))
    print(f"        -> tests_passed={red.passed} (RED, bug present)")

    print("[demo] running pandavas loop with a scripted demo worker...")
    final = run(task="fix add", repo_path=str(tmp_repo), worker=scripted_worker)

    print(f"[demo] AFTER: status={final['status']}")
    print(
        f"        -> tests_passed={final['last_test_result'].passed} "
        "(GREEN, bug fixed)"
    )
    print(f"[demo] trace: {final['trace']}")


if __name__ == "__main__":
    main()
