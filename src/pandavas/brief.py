"""Typed research-brief models and the deterministic resolve gate (P1).

Implements the Research Brief Contract from docs/SPEC.md §4: a typed artifact
(Nakula's output) plus the deterministic gate that runs before the worker. The
gate has no LLM and no network; it only reads files to count lines. A dangling or
out-of-bounds anchor means Research hallucinated -> the caller loops back.
"""

from __future__ import annotations

import os

from pydantic import BaseModel, Field, model_validator


class Anchor(BaseModel):
    """A pointer into real code: a path and an inclusive line range."""

    path: str  # repo-relative
    line_start: int = Field(ge=1)
    line_end: int
    snippet: str
    why: str

    @model_validator(mode="after")
    def _check_line_range(self) -> "Anchor":
        if self.line_end < self.line_start:
            raise ValueError(
                f"line_end ({self.line_end}) must be >= "
                f"line_start ({self.line_start})"
            )
        return self


class ResearchBrief(BaseModel):
    """Nakula's anchored brief (SPEC §4.1)."""

    task: str
    acceptance_criteria: list[str]
    relevant_code: list[Anchor]
    conventions: list[Anchor] = []
    integration_points: list[Anchor] = []
    constraints: list[str] = []
    open_questions: list[str] = []
    confidence: dict[str, float] = {}


def resolve_brief(brief: ResearchBrief, repo_path: str) -> list[str]:
    """Deterministically check that every anchor resolves to real file/lines.

    Validates each anchor across relevant_code + conventions + integration_points:
    the resolved path stays inside repo_path (no traversal escape), the file
    exists as a regular file, and 1 <= line_start <= line_end <= file line count.

    Args:
        brief: The brief to validate.
        repo_path: Repository root the anchors are relative to.

    Returns:
        A list of human-readable failure strings; empty means fully resolved.
    """
    failures: list[str] = []
    repo_root = os.path.realpath(repo_path)

    anchors = (
        list(brief.relevant_code)
        + list(brief.conventions)
        + list(brief.integration_points)
    )

    for anchor in anchors:
        abs_path = os.path.realpath(os.path.join(repo_root, anchor.path))

        # Path must stay inside the repo (reject traversal / escapes).
        if abs_path != repo_root and not abs_path.startswith(repo_root + os.sep):
            failures.append(
                f"{anchor.path}: resolves outside the repository (path escape)"
            )
            continue

        if not os.path.isfile(abs_path):
            failures.append(f"{anchor.path}: not a regular file (missing or not a file)")
            continue

        with open(abs_path, "r", encoding="utf-8") as f:
            num_lines = sum(1 for _ in f)

        if anchor.line_end > num_lines:
            failures.append(
                f"{anchor.path}: line_end {anchor.line_end} exceeds file length "
                f"({num_lines} lines)"
            )

    return failures
