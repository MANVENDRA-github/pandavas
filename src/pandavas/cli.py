"""Command-line entrypoint for pandavas (P0).

Exposes a single `run` subcommand that drives the orchestrator loop. At P0 the
agents are stubs: research/worker/judge are placeholders, so the loop runs but
no files are modified (the real worker is P1). This is honest by design.
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from . import orchestrator


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pandavas",
        description="Autonomously resolve a coding task on a local repo (P0 skeleton).",
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
    return parser


def _print_report(repo: str, task: str, final: dict) -> None:
    print(
        "pandavas - P0 (stub agents: research/worker/judge are placeholders)"
    )
    print(
        "note: no files are modified yet because the worker is a stub "
        "(real worker is P1)"
    )
    print(f"repo:   {repo}")
    print(f"task:   {task}")
    print(f"status: {final.get('status')}")
    print(f"iterations: {final.get('iteration')}")
    print("trace:")
    for record in final.get("trace", []):
        print(
            f"  [{record.get('iteration')}] "
            f"tests_passed={record.get('test_passed')} "
            f"judge_approved={record.get('judge_approved')}"
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entrypoint. Returns 0 if the run converged, else 1."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Uses the DEFAULT (no-op stub) worker — there is no real worker at P0.
    final = orchestrator.run(
        task=args.task,
        repo_path=args.repo,
        test_command=args.test_command,
        max_iterations=args.max_iterations,
    )

    _print_report(args.repo, args.task, final)
    return 0 if final.get("status") == "converged" else 1
