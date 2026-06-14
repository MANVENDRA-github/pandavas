"""Tests for deterministic snapshot + unified-diff capture."""

from pandavas.diffing import changed_files, compute_diff, snapshot


def test_snapshot_includes_source_excludes_ignored_dir(tmp_path):
    (tmp_path / "main.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.js").write_text("x()", encoding="utf-8")

    snap = snapshot(str(tmp_path))

    assert snap["main.py"] == "print('hi')\n"
    assert "node_modules/junk.js" not in snap


def test_compute_diff_for_modified_file():
    before = {"calc.py": "def add(a, b):\n    return a - b\n"}
    after = {"calc.py": "def add(a, b):\n    return a + b\n"}

    diff = compute_diff(before, after)

    assert "calc.py" in diff
    assert "-    return a - b" in diff
    assert "+    return a + b" in diff


def test_compute_diff_for_added_file():
    before: dict[str, str] = {}
    after = {"new.py": "x = 1\ny = 2\n"}

    diff = compute_diff(before, after)

    assert "new.py" in diff
    assert "+x = 1" in diff
    assert "+y = 2" in diff


def test_compute_diff_no_changes_returns_empty():
    snap = {"a.py": "same\n"}
    assert compute_diff(snap, dict(snap)) == ""


def test_changed_files_reports_added_removed_modified():
    before = {"keep.py": "k\n", "mod.py": "old\n", "gone.py": "g\n"}
    after = {"keep.py": "k\n", "mod.py": "new\n", "added.py": "a\n"}

    assert changed_files(before, after) == {"mod.py", "gone.py", "added.py"}
