"""End-to-end skill-mode test: a scripted 'host model' drives the deterministic
verbs over the real fixture with real pytest -- and NO API key.

This is the verb-surface analogue of examples/demo.py and the --offline check: it
proves baseline -> resolve-brief -> (edit) -> run-tests -> diff -> judge-gate ->
decide wire together and gate correctly, with the host's LLM steps replaced by a
script. The positive case converges red->green and commits; the negative case
(a no-op worker) does not converge.
"""

import json
import os
import shutil
import subprocess

from pandavas.cli import main

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "sample_buggy_repo")


def _last(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


def _copy_fixture(tmp_path) -> str:
    repo = os.path.join(str(tmp_path), "repo")
    shutil.copytree(FIXTURE, repo)
    return repo


def _git_init(repo, *, initial_commit=True):
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    if initial_commit:
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)


def _read_loop(repo) -> dict:
    with open(os.path.join(repo, ".pandavas", "loop.json"), encoding="utf-8") as f:
        return json.load(f)


def test_skill_mode_converges_red_to_green_and_commits(tmp_path, capsys):
    repo = _copy_fixture(tmp_path)
    _git_init(repo)

    # 1. baseline -- the bug's test is failing at baseline (tolerated by the gate).
    assert main(["baseline", "--repo", repo, "--task", "fix add"]) == 0
    base = _last(capsys)
    assert base["baseline_passed"] is False
    assert "test_calc::test_add" in base["baseline_failures"]

    # 2. research (host model): an anchored brief -> the resolve gate passes.
    with open(os.path.join(repo, ".pandavas", "brief.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "task": "fix add",
                "acceptance_criteria": ["add(2, 3) == 5"],
                "relevant_code": [
                    {"path": "calc.py", "line_start": 1, "line_end": 2,
                     "snippet": "def add", "why": "the buggy function"}
                ],
                "conventions": [], "integration_points": [], "constraints": [],
                "open_questions": [], "confidence": {},
            },
            f,
        )
    assert main(["resolve-brief", "--repo", repo]) == 0
    capsys.readouterr()

    # 3. worker (host model): apply the fix at the anchor.
    calc = os.path.join(repo, "calc.py")
    with open(calc, encoding="utf-8") as f:
        src = f.read()
    with open(calc, "w", encoding="utf-8") as f:
        f.write(src.replace("a - b", "a + b"))

    # 4. test -- green now, and the fix surfaces as red->green.
    assert main(["run-tests", "--repo", repo]) == 0
    assert _last(capsys)["newly_passing"] == ["test_calc::test_add"]

    # 5. diff + 6. judge-gate (deterministic) -> review.
    assert main(["diff", "--repo", repo]) == 0
    capsys.readouterr()
    assert main(["judge-gate", "--repo", repo]) == 0
    assert _last(capsys)["gate"] == "review"

    # 7. judge (host model) approves -> decide converges.
    assert main(["decide", "--repo", repo, "--approved", "true"]) == 0
    assert _last(capsys)["status"] == "converged"
    assert _read_loop(repo)["status"] == "converged"

    # 8. deliver -- committed to a branch, and .pandavas/ is NOT in the commit.
    assert main(["commit", "--repo", repo, "--task", "fix add"]) == 0
    assert _last(capsys)["committed"] is True
    show = subprocess.run(
        ["git", "show", "HEAD", "--name-only", "--format="],
        cwd=repo, capture_output=True, text=True,
    )
    committed = [line for line in show.stdout.splitlines() if line.strip()]
    assert "calc.py" in committed
    assert not any(p.startswith(".pandavas") for p in committed)


def test_skill_mode_no_op_worker_does_not_converge(tmp_path, capsys):
    repo = _copy_fixture(tmp_path)

    assert main(["baseline", "--repo", repo, "--task", "fix add"]) == 0
    capsys.readouterr()

    # No-op "worker": nothing changes. The pre-existing failure is tolerated...
    assert main(["run-tests", "--repo", repo]) == 0
    capsys.readouterr()
    # ...but there is no change, so the deterministic gate rejects (skips the LLM).
    assert main(["judge-gate", "--repo", repo]) == 30
    capsys.readouterr()

    # First decide continues; a second identical pass is detected as oscillation.
    assert main(["decide", "--repo", repo, "--approved", "false"]) == 10
    capsys.readouterr()
    assert main(["decide", "--repo", repo, "--approved", "false"]) == 20
    assert _last(capsys)["termination_reason"] == "oscillation"
    assert _read_loop(repo)["status"] == "did_not_converge"
