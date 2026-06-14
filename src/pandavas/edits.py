"""Deterministic, path-safe edit applier (P1).

The gate for writing the worker's (Arjuna's) changes into a repo. Full-file
replacement only -- no diffs, no deletion, no patch logic -- and every target is
contained inside the repo (traversal/escape is rejected, nothing is written).
No LLM, no network.
"""

from __future__ import annotations

import os


def is_within_repo(repo_path: str, rel_path: str) -> bool:
    """Return True only if rel_path resolves to a location inside repo_path.

    Uses os.path.realpath so symlinks and ".." are resolved before the check;
    absolute paths or "../" climbs that escape the repo return False.
    """
    repo_root = os.path.realpath(repo_path)
    target = os.path.realpath(os.path.join(repo_root, rel_path))
    return target == repo_root or target.startswith(repo_root + os.sep)


def apply_edits(repo_path: str, edits: list[dict]) -> tuple[list[str], list[str]]:
    """Write full-file edits into the repo, rejecting any that escape it.

    Args:
        repo_path: Repository root.
        edits: List of {"path": <repo-relative>, "content": <full new content>}.

    Returns:
        (written, rejected): repo-relative paths that were written, and those
        rejected for escaping the repo (for which nothing was written).
    """
    written: list[str] = []
    rejected: list[str] = []

    for edit in edits:
        rel_path = edit["path"]
        if not is_within_repo(repo_path, rel_path):
            rejected.append(rel_path)
            continue

        abs_path = os.path.join(repo_path, rel_path)
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8") as f:
            f.write(edit["content"])
        written.append(rel_path)

    return written, rejected


def delete_files(repo_path: str, rel_paths: list[str]) -> tuple[list[str], list[str]]:
    """Delete repo-relative files, rejecting any that escape the repo.

    Used by restore-to-best to remove files created in a worse iteration that are
    not part of the best snapshot. Missing files are treated as already-deleted.

    Args:
        repo_path: Repository root.
        rel_paths: Repo-relative paths to delete.

    Returns:
        (deleted, rejected): paths removed, and paths rejected for escaping.
    """
    deleted: list[str] = []
    rejected: list[str] = []

    for rel_path in rel_paths:
        if not is_within_repo(repo_path, rel_path):
            rejected.append(rel_path)
            continue
        abs_path = os.path.join(repo_path, rel_path)
        try:
            os.remove(abs_path)
            deleted.append(rel_path)
        except FileNotFoundError:
            deleted.append(rel_path)  # already gone -> goal satisfied
        except OSError:
            rejected.append(rel_path)

    return deleted, rejected
