"""Tests for the typed research brief and the deterministic resolve gate."""

import os

import pytest
from pydantic import ValidationError

from pandavas.brief import Anchor, ResearchBrief, resolve_brief

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_buggy_repo"
)
CALC = os.path.join(FIXTURE, "calc.py")


def _calc_line_count() -> int:
    with open(CALC, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def _brief(anchor: Anchor) -> ResearchBrief:
    return ResearchBrief(
        task="t",
        acceptance_criteria=["c"],
        relevant_code=[anchor],
    )


def test_resolves_clean_when_anchor_points_at_real_lines():
    n = _calc_line_count()
    anchor = Anchor(
        path="calc.py", line_start=1, line_end=n, snippet="def add", why="the bug"
    )
    assert resolve_brief(_brief(anchor), FIXTURE) == []


def test_nonexistent_path_is_a_failure():
    anchor = Anchor(
        path="nope.py", line_start=1, line_end=1, snippet="x", why="missing"
    )
    failures = resolve_brief(_brief(anchor), FIXTURE)
    assert len(failures) == 1
    assert "nope.py" in failures[0]


def test_line_end_beyond_file_length_is_a_failure():
    n = _calc_line_count()
    anchor = Anchor(
        path="calc.py", line_start=1, line_end=n + 100, snippet="x", why="oob"
    )
    failures = resolve_brief(_brief(anchor), FIXTURE)
    assert len(failures) == 1
    assert "calc.py" in failures[0]


def test_traversal_path_escapes_repo_and_is_a_failure():
    anchor = Anchor(
        path="../escape.py", line_start=1, line_end=1, snippet="x", why="escape"
    )
    failures = resolve_brief(_brief(anchor), FIXTURE)
    assert len(failures) == 1
    assert "../escape.py" in failures[0]


def test_anchor_line_end_before_line_start_raises():
    with pytest.raises(ValidationError):
        Anchor(path="calc.py", line_start=5, line_end=2, snippet="x", why="bad")
