"""Deterministic git delivery helpers (P3).

Turns a converged change on disk into a branch + commit, fulfilling the
"branch/diff" output promised in docs/SPEC.md §2. No LLM, no network -- a thin,
defensive wrapper over the local `git` CLI. Every operation degrades gracefully:
a non-git repo or a missing `git` is reported, never raised.
"""

from __future__ import annotations

import re
import subprocess


def _git(repo_path: str, *args: str) -> subprocess.CompletedProcess:
    """Run a git command in repo_path and capture output (never raises)."""
    return subprocess.run(
        ["git", *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )


def is_git_repo(repo_path: str) -> bool:
    """True if repo_path is inside a git work tree and git is available."""
    try:
        result = _git(repo_path, "rev-parse", "--is-inside-work-tree")
    except (OSError, FileNotFoundError):
        return False
    return result.returncode == 0 and result.stdout.strip() == "true"


def slug_branch(task: str, prefix: str = "pandavas") -> str:
    """Build a safe branch name like 'pandavas/fix-the-add-bug' from a task."""
    slug = re.sub(r"[^a-z0-9]+", "-", task.lower()).strip("-")
    slug = slug[:40].strip("-") or "change"
    return f"{prefix}/{slug}"


def commit_change(repo_path: str, branch: str, message: str) -> dict:
    """Create ``branch`` from the current HEAD and commit all changes to it.

    Args:
        repo_path: Repository root.
        branch: Branch name to create and switch to.
        message: Commit message.

    Returns:
        A dict: {"committed": bool, "branch": <name or None>, "error": <str or None>}.
        Returns committed=False with an error message on any failure (not a git
        repo, branch exists, nothing to commit, git missing) -- never raises.
    """
    if not is_git_repo(repo_path):
        return {"committed": False, "branch": None, "error": "not a git repository"}

    created = _git(repo_path, "checkout", "-b", branch)
    if created.returncode != 0:
        return {
            "committed": False,
            "branch": None,
            "error": f"could not create branch {branch!r}: {created.stderr.strip()}",
        }

    _git(repo_path, "add", "-A")
    committed = _git(repo_path, "commit", "-m", message)
    if committed.returncode != 0:
        # e.g. nothing to commit; leave the branch created but report it.
        return {
            "committed": False,
            "branch": branch,
            "error": f"commit failed: {committed.stderr.strip() or committed.stdout.strip()}",
        }

    return {"committed": True, "branch": branch, "error": None}
