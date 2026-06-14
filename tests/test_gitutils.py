"""Tests for the git delivery helpers (real local git, isolated tmp repos)."""

import subprocess

from pandavas.gitutils import commit_change, is_git_repo, slug_branch


def _init_repo(path: str) -> None:
    subprocess.run(["git", "init"], cwd=path, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=path, capture_output=True, text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=path, capture_output=True, text=True,
    )


def test_is_git_repo_false_for_plain_dir(tmp_path):
    assert is_git_repo(str(tmp_path)) is False


def test_is_git_repo_true_after_init(tmp_path):
    _init_repo(str(tmp_path))
    assert is_git_repo(str(tmp_path)) is True


def test_slug_branch_is_safe_and_deterministic():
    assert slug_branch("Fix the Add bug!") == "pandavas/fix-the-add-bug"
    assert slug_branch("") == "pandavas/change"


def test_commit_change_on_non_git_repo_reports_error(tmp_path):
    result = commit_change(str(tmp_path), "pandavas/x", "msg")
    assert result["committed"] is False
    assert result["branch"] is None
    assert "not a git repository" in result["error"]


def test_commit_change_creates_branch_and_commits(tmp_path):
    repo = str(tmp_path)
    _init_repo(repo)
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo, capture_output=True, text=True)

    # Now make a change and commit it via the helper.
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    result = commit_change(repo, "pandavas/fix-add", "pandavas: fix add")

    assert result["committed"] is True
    assert result["branch"] == "pandavas/fix-add"

    # The branch exists and is current.
    branch = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=repo, capture_output=True, text=True,
    ).stdout.strip()
    assert branch == "pandavas/fix-add"

    # The committed file holds the fix.
    show = subprocess.run(
        ["git", "show", "HEAD:calc.py"], cwd=repo, capture_output=True, text=True
    ).stdout
    assert "a + b" in show
