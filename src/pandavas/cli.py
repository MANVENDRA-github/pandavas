"""Command-line entrypoint for pandavas.

Exposes the `run` subcommand that drives the standalone orchestrator loop and prints
an ASCII-only run report (Windows-first), plus the keyless skill-mode verbs wired in
from `spine.py` (`baseline`, `run-tests`, `decide`, ...; see `docs/SKILL_MODE.md`). With --offline the stub research/worker/
judge nodes are injected so no LLM (and no API key) is needed -- useful for an
install/wiring check; the real executor still runs the tests. On a converged real
run it can also commit the change to a new git branch.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional, Sequence

from . import gitutils, nodes, orchestrator, spine
from .executor import LocalExecutor
from .llm import LLMClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pandavas",
        description="Autonomously resolve a coding task on a local repo.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run_p = sub.add_parser("run", help="Run the orchestrator loop on a local repo.")
    run_p.add_argument("--repo", required=True, help="Path to a local repository.")
    run_p.add_argument("--task", required=True, help="Task description.")
    run_p.add_argument(
        "--test-command",
        default=None,
        help="Override the auto-detected test command.",
    )
    run_p.add_argument(
        "--max-iterations",
        type=int,
        default=6,
        help="Hard cap on retry iterations (default: 6).",
    )
    run_p.add_argument(
        "--offline",
        action="store_true",
        help="Use stub agents (no LLM/API key) to verify install/wiring.",
    )
    run_p.add_argument(
        "--report",
        default=None,
        help="Optional path to write a JSON run report.",
    )
    run_p.add_argument(
        "--trace",
        default=None,
        help="Optional path to write the full per-iteration JSON trace.",
    )
    run_p.add_argument(
        "--junit-xml",
        default=None,
        help="Path to a JUnit XML file your test command emits (enables per-test "
        "rigor for non-pytest frameworks; relative paths resolve under --repo).",
    )
    run_p.add_argument(
        "--branch",
        default=None,
        help="Branch name to commit a converged change to (default: auto from task).",
    )
    run_p.add_argument(
        "--no-git",
        action="store_true",
        help="Do not create a git branch/commit on a converged change.",
    )

    # Keyless deterministic verbs for skill mode (baseline, run-tests, decide, ...).
    spine.add_subparsers(sub)
    return parser


def _print_report(repo: str, task: str, final: dict, offline: bool) -> None:
    status = final.get("status")
    if offline:
        print("OFFLINE MODE: stub agents, no LLM (install/wiring check only)")
    print("pandavas - run report")
    print(f"repo:    {repo}")
    print(f"task:    {task}")
    print(f"status:  {status}")
    if offline and status == "converged":
        print("note:    offline wiring check passed; this is NOT a verified fix")

    reason = final.get("termination_reason")
    if status == "did_not_converge" and reason:
        print(f"reason:  {reason}")

    print(f"iterations: {final.get('iteration')}")

    if status == "research_failed" and final.get("research_error"):
        print(f"research error: {final.get('research_error')}")

    regressions = final.get("regressions") or []
    if regressions:
        print(f"regressions: {', '.join(regressions)}")

    new_failures = final.get("new_failures") or []
    if new_failures:
        print(f"new failures: {', '.join(new_failures)}")

    newly_passing = final.get("newly_passing") or []
    if newly_passing:
        print(f"newly passing (red->green): {', '.join(newly_passing)}")

    best = final.get("best_attempt")
    if status == "did_not_converge" and best:
        print(f"best attempt: iteration {best.get('iteration')}")

    print("")
    print("change diff:")
    print(final.get("last_diff") or "(no changes)")


def _report_dict(repo: str, task: str, final: dict, usage: Optional[dict]) -> dict:
    best = final.get("best_attempt")
    return {
        "status": final.get("status"),
        "termination_reason": final.get("termination_reason"),
        "iterations": final.get("iteration"),
        "repo": repo,
        "task": task,
        "last_diff": final.get("last_diff"),
        "trace": final.get("trace"),
        "regressions": final.get("regressions"),
        "new_failures": final.get("new_failures"),
        "newly_passing": final.get("newly_passing"),
        "best_iteration": best.get("iteration") if best else None,
        "token_usage": usage,
    }


def _write_json(path: str, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint. Returns 0 if the run converged, else 1."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Skill-mode verbs are deterministic and self-contained; dispatch them before
    # any run-specific argument is touched. The `run` path below is unchanged.
    if args.command != "run":
        return spine.dispatch(args)

    executor = LocalExecutor(junit_xml=args.junit_xml)
    run_kwargs = {
        "task": args.task,
        "repo_path": args.repo,
        "test_command": args.test_command,
        "max_iterations": args.max_iterations,
        "executor": executor,
    }

    client = None
    if args.offline:
        # Inject stub nodes so no LLMClient is constructed (no API key needed).
        run_kwargs["research"] = nodes.nakula_research
        run_kwargs["worker"] = nodes.arjuna_worker
        run_kwargs["judge"] = nodes.sahadeva_judge
    else:
        # Build the client up front so we can report token usage and fail fast
        # with a clean message if a key/provider is missing.
        try:
            client = LLMClient()
        except (ValueError, RuntimeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        run_kwargs["llm_client"] = client

    try:
        final = orchestrator.run(**run_kwargs)
    except (ValueError, RuntimeError) as exc:
        # e.g. no detectable test command, or a missing model env var.
        print(f"error: {exc}", file=sys.stderr)
        return 1

    _print_report(args.repo, args.task, final, args.offline)

    usage = client.usage if client is not None else None
    if usage is not None:
        print(
            f"tokens:  {usage['total_tokens']} total "
            f"({usage['calls']} LLM calls)"
        )

    # Commit a converged real change to a new branch (best-effort, never fatal).
    if final.get("status") == "converged" and not args.no_git and not args.offline:
        branch = args.branch or gitutils.slug_branch(args.task)
        result = gitutils.commit_change(args.repo, branch, f"pandavas: {args.task}")
        if result["committed"]:
            print(f"git:     committed change to branch '{result['branch']}'")
        else:
            print(f"git:     no commit ({result['error']})")

    if args.report:
        _write_json(args.report, _report_dict(args.repo, args.task, final, usage))
    if args.trace:
        _write_json(
            args.trace,
            {
                "task": args.task,
                "repo": args.repo,
                "status": final.get("status"),
                "trace": final.get("trace"),
            },
        )

    return 0 if final.get("status") == "converged" else 1
