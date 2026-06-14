"""Unit tests for the deterministic test executor (pandavas.executor)."""

import sys

import pytest

from pandavas.executor import LocalExecutor, detect_test_command


def _touch(path):
    path.write_text("", encoding="utf-8")


def test_detect_pytest_from_pyproject(tmp_path):
    _touch(tmp_path / "pyproject.toml")
    assert detect_test_command(str(tmp_path)) == "pytest"


def test_detect_npm_from_package_json(tmp_path):
    _touch(tmp_path / "package.json")
    assert detect_test_command(str(tmp_path)) == "npm test"


def test_detect_go_from_go_mod(tmp_path):
    _touch(tmp_path / "go.mod")
    assert detect_test_command(str(tmp_path)) == "go test ./..."


def test_detect_cargo_from_cargo_toml(tmp_path):
    _touch(tmp_path / "Cargo.toml")
    assert detect_test_command(str(tmp_path)) == "cargo test"


def test_detect_maven_from_pom_xml(tmp_path):
    _touch(tmp_path / "pom.xml")
    assert detect_test_command(str(tmp_path)) == "mvn test"


def test_detect_returns_none_for_empty_dir(tmp_path):
    assert detect_test_command(str(tmp_path)) is None


def test_explicit_command_overrides_detection(tmp_path):
    # package.json would detect "npm test", but the explicit override must win.
    _touch(tmp_path / "package.json")
    cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    result = LocalExecutor().run_tests(str(tmp_path), test_command=cmd)
    assert result.command == cmd
    assert result.passed is True


def test_exit_zero_reports_passed(tmp_path):
    cmd = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
    result = LocalExecutor().run_tests(str(tmp_path), test_command=cmd)
    assert result.passed is True
    assert result.exit_code == 0


def test_exit_one_reports_failed(tmp_path):
    cmd = f'"{sys.executable}" -c "import sys; sys.exit(1)"'
    result = LocalExecutor().run_tests(str(tmp_path), test_command=cmd)
    assert result.passed is False
    assert result.exit_code == 1


def test_raises_when_no_command_and_none_detectable(tmp_path):
    with pytest.raises(ValueError):
        LocalExecutor().run_tests(str(tmp_path))
