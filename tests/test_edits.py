"""Tests for the deterministic, path-safe edit applier."""

import os

from pandavas.edits import apply_edits, is_within_repo


def test_write_new_top_level_file(tmp_path):
    repo = str(tmp_path)
    written, rejected = apply_edits(repo, [{"path": "new.py", "content": "x = 1\n"}])

    assert written == ["new.py"]
    assert rejected == []
    assert (tmp_path / "new.py").read_text(encoding="utf-8") == "x = 1\n"


def test_overwrite_existing_file(tmp_path):
    repo = str(tmp_path)
    (tmp_path / "f.py").write_text("old\n", encoding="utf-8")

    written, rejected = apply_edits(repo, [{"path": "f.py", "content": "new\n"}])

    assert written == ["f.py"]
    assert rejected == []
    assert (tmp_path / "f.py").read_text(encoding="utf-8") == "new\n"


def test_nested_path_creates_parent_dirs(tmp_path):
    repo = str(tmp_path)
    written, rejected = apply_edits(
        repo, [{"path": "sub/dir/new.py", "content": "nested\n"}]
    )

    assert written == ["sub/dir/new.py"]
    assert rejected == []
    assert (tmp_path / "sub" / "dir" / "new.py").read_text(encoding="utf-8") == "nested\n"


def test_traversal_path_is_rejected_and_writes_nothing(tmp_path):
    repo = str(tmp_path)
    written, rejected = apply_edits(
        repo, [{"path": "../evil.py", "content": "pwn\n"}]
    )

    assert written == []
    assert rejected == ["../evil.py"]
    # Nothing was created outside the repo.
    assert not (tmp_path.parent / "evil.py").exists()


def test_is_within_repo(tmp_path):
    repo = str(tmp_path)
    assert is_within_repo(repo, "a/b.py") is True
    assert is_within_repo(repo, "../x") is False
