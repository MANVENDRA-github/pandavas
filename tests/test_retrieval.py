"""Tests for deterministic repo retrieval."""

import os

from pandavas.retrieval import MAX_FILE_BYTES, build_context, list_files

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "sample_buggy_repo"
)


def test_list_files_filters_ignored_dirs_exts_and_oversized(tmp_path):
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x()", encoding="utf-8")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "x.pyc").write_text("x", encoding="utf-8")
    (tmp_path / "big.txt").write_text("a" * (MAX_FILE_BYTES + 1), encoding="utf-8")
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")

    files = list_files(str(tmp_path))

    assert "main.py" in files
    assert "node_modules/junk.js" not in files
    assert "__pycache__/x.pyc" not in files
    assert "big.txt" not in files


def test_build_context_has_tree_and_numbered_calc():
    ctx = build_context(FIXTURE, task="fix the add function bug")

    assert "FILE TREE" in ctx
    assert "=== calc.py ===" in ctx
    assert "1:" in ctx
    assert "def add" in ctx


def test_build_context_ranks_calc_into_selection():
    # The task mentions "add", which appears in calc.py, so it must be selected.
    ctx = build_context(FIXTURE, task="fix the add function bug")
    assert "=== calc.py ===" in ctx


def test_tiny_char_budget_never_truncates_a_file():
    ctx = build_context(FIXTURE, task="fix the add function bug", char_budget=30)
    assert isinstance(ctx, str)

    # Any file that WAS selected must appear whole: its last rendered numbered
    # line must equal the file's true last line.
    for rel in list_files(FIXTURE):
        header = f"=== {rel} ==="
        if header not in ctx:
            continue
        with open(os.path.join(FIXTURE, rel), encoding="utf-8") as f:
            true_lines = f.read().splitlines()
        n = len(true_lines)
        assert f"{n}: {true_lines[-1]}" in ctx
