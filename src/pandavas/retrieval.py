"""Deterministic repo retrieval for the research agent (P1).

Builds a bounded, line-numbered view of a repository so the research LLM (Nakula)
can cite resolvable line ranges. Everything here is deterministic: no LLM, no
network, no caching. Line numbers are the file's true 1-indexed positions so the
downstream resolve gate (brief.resolve_brief) can verify anchors against them.
"""

from __future__ import annotations

import os
import re

IGNORE_DIRS = {
    ".git",
    ".pandavas",  # pandavas skill-mode working/state dir (never repo content)
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "htmlcov",
}
IGNORE_EXTS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".pdf",
    ".zip",
    ".gz",
    ".tar",
    ".whl",
    ".so",
    ".dll",
    ".exe",
    ".bin",
    ".pyc",
    ".lock",
}
MAX_FILE_BYTES = 100_000  # skip larger files
DEFAULT_MAX_FILES = 8
DEFAULT_CHAR_BUDGET = 40_000

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def list_files(repo_path: str) -> list[str]:
    """Return sorted repo-relative paths of candidate text files.

    Skips anything under an IGNORE_DIRS directory, any IGNORE_EXTS extension, and
    any file larger than MAX_FILE_BYTES.
    """
    repo_root = os.path.abspath(repo_path)
    results: list[str] = []

    for dirpath, dirnames, filenames in os.walk(repo_root):
        # Prune ignored directories in place so os.walk never descends into them.
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for name in filenames:
            if os.path.splitext(name)[1].lower() in IGNORE_EXTS:
                continue
            full = os.path.join(dirpath, name)
            try:
                if os.path.getsize(full) > MAX_FILE_BYTES:
                    continue
            except OSError:
                continue
            rel = os.path.relpath(full, repo_root).replace(os.sep, "/")
            results.append(rel)

    return sorted(results)


def _tokenize(text: str) -> set[str]:
    """Lowercase alphanumeric tokens of length >= 2."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if len(t) >= 2}


def _score(path: str, content: str, tokens: set[str]) -> int:
    """Score a file against task tokens; path hits weigh more than content hits."""
    path_hits = sum(1 for t in _TOKEN_RE.findall(path.lower()) if t in tokens)
    content_hits = sum(1 for t in _TOKEN_RE.findall(content.lower()) if t in tokens)
    return path_hits * 5 + content_hits


def _render_file(rel_path: str, content: str) -> str:
    """Render a file as a header plus true 1-indexed, line-numbered content."""
    lines = content.splitlines()
    numbered = "\n".join(f"{i}: {line}" for i, line in enumerate(lines, 1))
    return f"=== {rel_path} ===\n{numbered}"


def build_context(
    repo_path: str,
    task: str,
    max_files: int = DEFAULT_MAX_FILES,
    char_budget: int = DEFAULT_CHAR_BUDGET,
) -> str:
    """Assemble a file tree plus the highest-ranked files, line-numbered.

    Files are ranked by token overlap with the task. The top files are included
    up to ``max_files``, but a file is added only if its full numbered rendering
    fits in the remaining ``char_budget`` -- files are never truncated mid-content
    (that would break line-number fidelity), only included whole or skipped.

    Args:
        repo_path: Repository root.
        task: Natural-language task used to rank files.
        max_files: Cap on the number of files included.
        char_budget: Budget (chars) for the included file renderings.

    Returns:
        The assembled context string (file tree + selected numbered files).
    """
    repo_root = os.path.abspath(repo_path)
    files = list_files(repo_root)

    contents: dict[str, str] = {}
    for rel in files:
        full = os.path.join(repo_root, rel.replace("/", os.sep))
        try:
            with open(full, "r", encoding="utf-8", errors="replace") as f:
                contents[rel] = f.read()
        except OSError:
            continue

    tokens = _tokenize(task)
    ranked = sorted(
        contents,
        key=lambda p: (-_score(p, contents[p], tokens), p),
    )

    tree = "FILE TREE\n" + "\n".join(files)
    sections = [tree]

    remaining = char_budget
    selected = 0
    for rel in ranked:
        if selected >= max_files:
            break
        rendered = _render_file(rel, contents[rel])
        if len(rendered) <= remaining:
            sections.append(rendered)
            remaining -= len(rendered)
            selected += 1

    return "\n\n".join(sections)
