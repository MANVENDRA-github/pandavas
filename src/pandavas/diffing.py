"""Deterministic snapshot + unified-diff capture (P2).

Captures the worker's change as a unified diff for the judge, without any git
dependency, LLM, or network. File enumeration reuses retrieval.list_files so the
same IGNORE_DIRS / IGNORE_EXTS / MAX_FILE_BYTES rules apply.
"""

from __future__ import annotations

import difflib
import os

from . import retrieval


def snapshot(repo_path: str) -> dict[str, str]:
    """Return {repo-relative path: content} for every candidate text file."""
    result: dict[str, str] = {}
    for rel in retrieval.list_files(repo_path):
        abs_path = os.path.join(repo_path, rel.replace("/", os.sep))
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                result[rel] = f.read()
        except OSError:
            continue
    return result


def changed_files(before: dict[str, str], after: dict[str, str]) -> set[str]:
    """Return paths added, removed, or whose content changed between snapshots."""
    changed: set[str] = set()
    for path in set(before) | set(after):
        if before.get(path) != after.get(path):
            changed.add(path)
    return changed


def _split(content: str) -> list[str]:
    """Split into lines without terminators, to pair with difflib lineterm=""."""
    return content.splitlines()


def compute_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Produce one unified diff string covering all changed files, sorted by path.

    Added files diff against empty (new file), removed files diff against empty
    (deletion), and modified files diff before vs after. Returns "" if nothing
    changed.
    """
    parts: list[str] = []
    for path in sorted(changed_files(before, after)):
        before_lines = _split(before.get(path, ""))
        after_lines = _split(after.get(path, ""))
        diff = difflib.unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
        parts.append("\n".join(diff))
    return "\n".join(parts)
