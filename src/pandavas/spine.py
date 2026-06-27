"""Deterministic verb spine for pandavas "skill mode" (keyless).

This module exposes the project's LLM-free machinery as a set of small,
stateless CLI subcommands. A coding harness (Claude Code, Cursor, ...) plays the
LLM agents (Nakula research, Arjuna worker, Sahadeva judge) with its own model
and calls these verbs via the shell; the verbs are the *rules* the host model
must obey. There is no LLM and no API key here -- everything is a thin wrapper
over executor / testresults / edits / diffing / gitutils / brief plus three pure
helpers from nodes (make_bhima_test, _better, _restore_snapshot), so skill mode
shares the EXACT determinism that `python -m pandavas run` is CI-tested against.

Design rules:
  * State persists between stateless verb calls in a ``.pandavas/`` working
    directory under the target repo (excluded from the user's git).
  * ``decide`` is the single writer of ``loop.json`` and the single authority for
    diffs / signatures / best-attempt: it recomputes them from snapshots and
    never trusts a model-supplied diff, so the loop cannot be gamed.
  * All stdout is a single ASCII JSON object (``ensure_ascii=True``); large
    payloads (diffs, test logs) are written to files and only their paths +
    ASCII summaries are printed. True errors print ``{"error": ...}`` to stderr
    and exit 1.
  * Exit codes are distinct so the host model can branch on ``$?``:
      0  ok / converged / review
      1  error / no-test-command / dangling-anchor / not-committed
      10 decide: continue (retry)
      20 decide: stop (did_not_converge)
      30 judge-gate: auto-reject (skip the LLM judge)
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import subprocess
import sys
from typing import Optional

from . import diffing, edits, gitutils
from .brief import ResearchBrief, resolve_brief
from .executor import LocalExecutor, detect_test_command
from .nodes import _better, _restore_snapshot, make_bhima_test
from .testresults import failures

STATE_DIR_NAME = ".pandavas"
SCHEMA_VERSION = 1
_TAIL_LIMIT = 2000


# --- state-dir plumbing --------------------------------------------------------


def _state_dir(repo: str) -> str:
    return os.path.join(repo, STATE_DIR_NAME)


def _ensure_state(repo: str) -> str:
    state = _state_dir(repo)
    os.makedirs(os.path.join(state, "snapshots"), exist_ok=True)
    os.makedirs(os.path.join(state, "diffs"), exist_ok=True)
    return state


def _sp(repo: str, *parts: str) -> str:
    """Path inside the repo's .pandavas/ state dir."""
    return os.path.join(_state_dir(repo), *parts)


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        # utf-8 file; readability over ASCII (ASCII only constrains stdout).
        json.dump(data, f, indent=2, ensure_ascii=False)


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def _emit(payload: dict) -> int:
    """Print one ASCII JSON object to stdout. Returns 0 (caller may override)."""
    print(json.dumps(payload, ensure_ascii=True))
    return 0


def _err(message: str) -> int:
    """Print an error as JSON to stderr and return exit code 1."""
    print(json.dumps({"error": message}, ensure_ascii=True), file=sys.stderr)
    return 1


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _repo_snapshot(repo: str) -> dict:
    """Snapshot the repo, defensively dropping any ``.pandavas/`` keys so the
    state dir never pollutes diffs, signatures, best-attempt, or restore."""
    snap = diffing.snapshot(repo)
    prefix = STATE_DIR_NAME + "/"
    return {
        k: v
        for k, v in snap.items()
        if k != STATE_DIR_NAME and not k.startswith(prefix)
    }


def _git_dir(repo: str) -> Optional[str]:
    """Resolve the repo's git dir (handles worktrees/submodules), or None."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=repo,
            capture_output=True,
            text=True,
        )
    except (OSError, FileNotFoundError):
        return None
    if out.returncode != 0:
        return None
    gitdir = out.stdout.strip()
    if not gitdir:
        return None
    return gitdir if os.path.isabs(gitdir) else os.path.join(repo, gitdir)


def _exclude_pandavas(repo: str) -> bool:
    """Append ``.pandavas/`` to <gitdir>/info/exclude (local, non-invasive) so the
    state dir is never staged and the user's tracked .gitignore is untouched."""
    gitdir = _git_dir(repo)
    if gitdir is None:
        return False
    info = os.path.join(gitdir, "info")
    exclude = os.path.join(info, "exclude")
    line = STATE_DIR_NAME + "/"
    existing = _read_text(exclude)
    if line in existing.splitlines():
        return True
    try:
        os.makedirs(info, exist_ok=True)
        with open(exclude, "a", encoding="utf-8") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write(line + "\n")
        return True
    except OSError:
        return False


def _failing_count(per_test: Optional[dict], test_passed: bool) -> int:
    if per_test is not None:
        return len(failures(per_test))
    return 0 if test_passed else 1


# --- verbs ---------------------------------------------------------------------


def cmd_baseline(args) -> int:
    """Run the suite once, capture baseline + snapshots, init loop.json."""
    repo = args.repo
    if not os.path.isdir(repo):
        return _err(f"repo path is not a directory: {repo!r}")

    loop_path = _sp(repo, "loop.json")
    if os.path.isfile(loop_path) and not args.force:
        return _err(
            "an existing .pandavas/loop.json was found; pass --force to "
            "re-baseline and discard the current run state."
        )

    command = args.test_command or detect_test_command(repo)
    if command is None:
        return _err(
            f"could not detect a test command for {repo!r}; pass --test-command."
        )

    _ensure_state(repo)
    executor = LocalExecutor(junit_xml=args.junit_xml)
    result = executor.run_tests(repo, command)

    snap = _repo_snapshot(repo)
    _write_json(_sp(repo, "snapshots", "baseline.json"), snap)
    _write_json(_sp(repo, "snapshots", "pre_iter.json"), snap)

    _write_json(
        _sp(repo, "baseline.json"),
        {
            "version": SCHEMA_VERSION,
            "task": args.task,
            "repo_path": os.path.abspath(repo),
            "test_command": result.command,
            "junit_xml": args.junit_xml,
            "baseline_per_test": result.per_test,
            "baseline_passed": result.passed,
            "baseline_exit_code": result.exit_code,
        },
    )
    _write_json(
        loop_path,
        {
            "version": SCHEMA_VERSION,
            "task": args.task,
            "repo_path": os.path.abspath(repo),
            "iteration": 1,
            "max_iterations": args.max_iterations,
            "status": "running",
            "termination_reason": None,
            "iteration_signatures": [],
            "best_attempt": None,
            "trace": [],
            "updated_at": _now(),
        },
    )
    excluded = _exclude_pandavas(repo)

    base_fail = sorted(failures(result.per_test)) if result.per_test else []
    return _emit(
        {
            "test_command": result.command,
            "baseline_passed": result.passed,
            "baseline_failures": base_fail,
            "per_test_available": result.per_test is not None,
            "max_iterations": args.max_iterations,
            "git_excluded": excluded,
            "state_dir": STATE_DIR_NAME,
        }
    )


def cmd_detect_test(args) -> int:
    command = detect_test_command(args.repo)
    _emit({"test_command": command})
    return 0 if command is not None else 1


def cmd_resolve_brief(args) -> int:
    """Resolve gate: every anchor must point at real files/lines in the repo."""
    repo = args.repo
    brief_path = args.brief
    if not os.path.isabs(brief_path):
        brief_path = os.path.join(repo, brief_path)

    data = _read_json(brief_path)
    if data is None:
        return _err(f"could not read brief JSON at {brief_path!r}")

    try:
        brief = ResearchBrief(**data)
    except Exception as exc:  # pydantic ValidationError / TypeError
        return _emit_fail_resolve([f"invalid ResearchBrief JSON: {exc}"])

    fails = resolve_brief(brief, repo)
    if fails:
        return _emit_fail_resolve(fails)

    # Cache the validated brief at the canonical path (research-once).
    _ensure_state(repo)
    _write_json(_sp(repo, "brief.json"), brief.model_dump())
    _emit({"resolved": True, "failures": [], "anchors": len(brief.relevant_code)})
    return 0


def _emit_fail_resolve(fails: list) -> int:
    _emit({"resolved": False, "failures": fails})
    return 1


def cmd_apply_edits(args) -> int:
    """Optional path-safe full-file writer (Arjuna may edit files directly)."""
    repo = args.repo
    edits_path = args.edits
    if not os.path.isabs(edits_path):
        edits_path = os.path.join(repo, edits_path)
    data = _read_json(edits_path)
    if data is None or not isinstance(data, list):
        return _err(f"edits JSON at {edits_path!r} must be a list of {{path, content}}")

    written, rejected = edits.apply_edits(repo, data)
    _emit({"written": written, "rejected": rejected})
    return 0 if not rejected else 1


def cmd_run_tests(args) -> int:
    """Regression-aware verdict vs the baseline. Exit 0 iff no new failures."""
    repo = args.repo
    base = _read_json(_sp(repo, "baseline.json"))
    if base is None:
        return _err("no .pandavas/baseline.json; run `pandavas baseline` first.")

    executor = LocalExecutor(junit_xml=base.get("junit_xml"))
    state = {
        "repo_path": repo,
        "test_command": base.get("test_command"),
        "baseline_test_results": base.get("baseline_per_test"),
    }
    out = make_bhima_test(executor)(state)
    result = out["last_test_result"]
    test_passed = bool(out["test_passed"])
    failing_count = _failing_count(result.per_test, test_passed)

    _write_text(
        _sp(repo, "last_test_output.txt"),
        (result.stdout or "") + (result.stderr or ""),
    )
    _write_json(
        _sp(repo, "last_test.json"),
        {
            "version": SCHEMA_VERSION,
            "test_passed": test_passed,
            "exit_code": result.exit_code,
            "command": result.command,
            "duration_s": result.duration_s,
            "regressions": out["regressions"],
            "new_failures": out["new_failures"],
            "newly_passing": out["newly_passing"],
            "failing_count": failing_count,
            "per_test": result.per_test,
        },
    )
    _emit(
        {
            "test_passed": test_passed,
            "exit_code": result.exit_code,
            "regressions": out["regressions"],
            "new_failures": out["new_failures"],
            "newly_passing": out["newly_passing"],
            "failing_count": failing_count,
            "output_path": STATE_DIR_NAME + "/last_test_output.txt",
        }
    )
    return 0 if test_passed else 1


def cmd_diff(args) -> int:
    """Render a cumulative (vs baseline) or per-iteration (vs pre_iter) diff."""
    repo = args.repo
    base_name = "baseline.json" if args.mode == "cumulative" else "pre_iter.json"
    before = _read_json(_sp(repo, "snapshots", base_name))
    if before is None:
        return _err(f"missing snapshot {base_name}; run `pandavas baseline` first.")
    after = _repo_snapshot(repo)
    d = diffing.compute_diff(before, after)
    changed = sorted(diffing.changed_files(before, after))
    out_path = _sp(repo, "diffs", f"{args.mode}.diff")
    _write_text(out_path, d)
    _emit(
        {
            "mode": args.mode,
            "diff_path": STATE_DIR_NAME + f"/diffs/{args.mode}.diff",
            "changed_files": changed,
            "n_changed": len(changed),
        }
    )
    return 0


def cmd_judge_gate(args) -> int:
    """Deterministic pre-LLM judge gate: reject failing/empty-diff without tokens.

    Exit 0  -> proceed to the LLM judge (tests pass and a real change exists).
    Exit 30 -> auto-reject; feed the printed feedback to `decide --approved false`.
    """
    repo = args.repo
    last = _read_json(_sp(repo, "last_test.json"))
    if last is None:
        return _err("no .pandavas/last_test.json; run `pandavas run-tests` first.")

    if not last["test_passed"]:
        tail = _read_text(_sp(repo, "last_test_output.txt")).strip()[-_TAIL_LIMIT:]
        feedback = "Tests are failing:\n" + tail
        if last.get("new_failures"):
            feedback += "\nNew failures: " + ", ".join(last["new_failures"])
        if last.get("regressions"):
            feedback += "\nRegressions: " + ", ".join(last["regressions"])
        _emit({"gate": "reject", "reason": "failing_tests", "feedback": feedback})
        return 30

    before = _read_json(_sp(repo, "snapshots", "baseline.json")) or {}
    cum = diffing.compute_diff(before, _repo_snapshot(repo))
    if cum.strip() == "":
        _emit(
            {
                "gate": "reject",
                "reason": "empty_diff",
                "feedback": (
                    "No change was made (empty diff); a fix task cannot be "
                    "satisfied without a change."
                ),
            }
        )
        return 30

    _emit({"gate": "review", "reason": None})
    return 0


def cmd_decide(args) -> int:
    """Loop control (Yudhishthira): trace, best-attempt, oscillation, cap, restore.

    Faithful port of nodes.yudhishthira over on-disk state. Sole writer of
    loop.json; recomputes diffs/signatures from snapshots.

    Exit 0  -> converged.
    Exit 10 -> continue (retry); the next worker pass should address `feedback`.
    Exit 20 -> stop (did_not_converge); best attempt restored to disk.
    """
    repo = args.repo
    loop = _read_json(_sp(repo, "loop.json"))
    last = _read_json(_sp(repo, "last_test.json"))
    baseline_snap = _read_json(_sp(repo, "snapshots", "baseline.json"))
    pre_iter_snap = _read_json(_sp(repo, "snapshots", "pre_iter.json"))
    if loop is None or last is None or baseline_snap is None or pre_iter_snap is None:
        return _err(
            "missing run state (loop.json / last_test.json / snapshots); run "
            "`pandavas baseline` then `pandavas run-tests` before `decide`."
        )

    it = loop["iteration"]
    max_it = loop["max_iterations"]
    approved = args.approved == "true"
    feedback = args.feedback or ""

    after = _repo_snapshot(repo)
    per_iter_diff = diffing.compute_diff(pre_iter_snap, after)
    cumulative = diffing.compute_diff(baseline_snap, after)

    new_failures = list(last.get("new_failures") or [])
    record = {
        "iteration": it,
        "test_passed": last.get("test_passed"),
        "judge_approved": approved,
        "judge_feedback": feedback,
        "diff": per_iter_diff,
        "regressions": list(last.get("regressions") or []),
        "new_failures": new_failures,
        "newly_passing": list(last.get("newly_passing") or []),
    }
    trace = list(loop.get("trace") or []) + [record]

    cand = {
        "iteration": it,
        "new_failures": new_failures,
        "new_failures_count": len(new_failures),
        "failing_count": last.get("failing_count", 0),
        "diff": cumulative,
    }
    best = loop.get("best_attempt")
    if _better(cand, best):
        best = cand
        _write_json(_sp(repo, "snapshots", "best.json"), after)

    if approved:
        loop.update(
            {
                "status": "converged",
                "trace": trace,
                "best_attempt": best,
                "updated_at": _now(),
            }
        )
        _write_json(_sp(repo, "loop.json"), loop)
        _emit(
            {
                "status": "converged",
                "iteration": it,
                "newly_passing": record["newly_passing"],
                "diff_path": STATE_DIR_NAME + "/diffs/cumulative.diff",
            }
        )
        _write_text(_sp(repo, "diffs", "cumulative.diff"), cumulative)
        return 0

    sig = [hashlib.sha256(per_iter_diff.encode("utf-8")).hexdigest(), sorted(new_failures)]
    seen = loop.get("iteration_signatures") or []
    updated_sigs = seen + [sig]

    def _stop(reason: str) -> int:
        restored = False
        if best is not None and best["iteration"] != it:
            best_snap = _read_json(_sp(repo, "snapshots", "best.json"))
            # Only restore against a real snapshot; never restore to an empty one
            # (a missing best.json must not wipe the repo).
            if best_snap is not None:
                _restore_snapshot(repo, best_snap, after)
                restored = True
        loop.update(
            {
                "status": "did_not_converge",
                "termination_reason": reason,
                "iteration_signatures": updated_sigs,
                "trace": trace,
                "best_attempt": best,
                "updated_at": _now(),
            }
        )
        _write_json(_sp(repo, "loop.json"), loop)
        _emit(
            {
                "status": "did_not_converge",
                "termination_reason": reason,
                "iteration": it,
                "best_iteration": best["iteration"] if best else None,
                "restored_best": restored,
                "new_failures": best["new_failures"] if best else new_failures,
            }
        )
        return 20

    if sig in seen:
        return _stop("oscillation")
    if it >= max_it:
        return _stop("cap")

    # Continue: roll pre_iter forward so the next pass diffs against this state.
    _write_json(_sp(repo, "snapshots", "pre_iter.json"), after)
    loop.update(
        {
            "iteration": it + 1,
            "status": "running",
            "iteration_signatures": updated_sigs,
            "trace": trace,
            "best_attempt": best,
            "updated_at": _now(),
        }
    )
    _write_json(_sp(repo, "loop.json"), loop)
    _emit({"status": "running", "iteration": it + 1, "feedback": feedback})
    return 10


def cmd_restore(args) -> int:
    name = "best.json" if args.to == "best" else "baseline.json"
    snap = _read_json(_sp(args.repo, "snapshots", name))
    if snap is None:
        return _err(f"no snapshot to restore ({name} missing).")
    _restore_snapshot(args.repo, snap, _repo_snapshot(args.repo))
    _emit({"restored": args.to})
    return 0


def cmd_commit(args) -> int:
    branch = args.branch or gitutils.slug_branch(args.task)
    message = args.message or f"pandavas: {args.task}"
    result = gitutils.commit_change(args.repo, branch, message)
    _emit(result)
    return 0 if result["committed"] else 1


# --- parser wiring -------------------------------------------------------------


def add_subparsers(sub) -> None:
    """Register every spine verb on the shared subparsers object from cli.py."""

    def _with_repo(p):
        p.add_argument("--repo", required=True, help="Path to the local repository.")
        return p

    p = _with_repo(sub.add_parser("baseline", help="Run the suite once; init run state."))
    p.add_argument("--task", required=True, help="Task description.")
    p.add_argument("--test-command", default=None, help="Override the test command.")
    p.add_argument("--junit-xml", default=None, help="JUnit XML path for per-test rigor.")
    p.add_argument("--max-iterations", type=int, default=6, help="Hard retry cap.")
    p.add_argument("--force", action="store_true", help="Discard existing run state.")
    p.set_defaults(func=cmd_baseline)

    p = _with_repo(sub.add_parser("detect-test", help="Print the detected test command."))
    p.set_defaults(func=cmd_detect_test)

    p = _with_repo(sub.add_parser("resolve-brief", help="Resolve-gate a research brief."))
    p.add_argument(
        "--brief",
        default=os.path.join(STATE_DIR_NAME, "brief.json"),
        help="Brief JSON path (default .pandavas/brief.json, relative to --repo).",
    )
    p.set_defaults(func=cmd_resolve_brief)

    p = _with_repo(sub.add_parser("apply-edits", help="Path-safe full-file writes."))
    p.add_argument("--edits", required=True, help="JSON list of {path, content}.")
    p.set_defaults(func=cmd_apply_edits)

    p = _with_repo(sub.add_parser("run-tests", help="Regression-aware test verdict."))
    p.set_defaults(func=cmd_run_tests)

    p = _with_repo(sub.add_parser("diff", help="Render cumulative/iter diff to a file."))
    p.add_argument(
        "--mode", choices=["cumulative", "iter"], default="cumulative"
    )
    p.set_defaults(func=cmd_diff)

    p = _with_repo(sub.add_parser("judge-gate", help="Deterministic pre-LLM judge gate."))
    p.set_defaults(func=cmd_judge_gate)

    p = _with_repo(sub.add_parser("decide", help="Loop control: converge/retry/stop."))
    p.add_argument("--approved", choices=["true", "false"], required=True)
    p.add_argument("--feedback", default=None, help="Judge feedback for the next pass.")
    p.set_defaults(func=cmd_decide)

    p = _with_repo(sub.add_parser("restore", help="Restore best/baseline snapshot."))
    p.add_argument("--to", choices=["best", "baseline"], default="best")
    p.set_defaults(func=cmd_restore)

    p = _with_repo(sub.add_parser("commit", help="Commit a converged change to a branch."))
    p.add_argument("--task", required=True, help="Task (for the default branch/message).")
    p.add_argument("--branch", default=None, help="Branch name (default: auto from task).")
    p.add_argument("--message", default=None, help="Commit message.")
    p.set_defaults(func=cmd_commit)


def dispatch(args) -> int:
    """Run the spine verb selected by argparse (its func default)."""
    return args.func(args)
