"""Tests for the pandavas CLI (all offline; no API key required)."""

import json
import os
import sys
from unittest import mock

from pandavas.cli import main

# Non-pytest commands so the gate uses exit-code fallback (a no-op worker then
# genuinely cannot satisfy a failing command). The P2 regression gate tolerates
# pre-existing pytest failures, so a buggy pytest repo would otherwise converge
# under a no-op worker -- hence explicit exit-code commands here.
PASS_CMD = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
FAIL_CMD = f'"{sys.executable}" -c "import sys; sys.exit(1)"'


def test_offline_cannot_fix_failing_repo_exits_1(capsys, tmp_path):
    code = main(
        [
            "run",
            "--repo",
            str(tmp_path),
            "--task",
            "fix the failing tests",
            "--offline",
            "--test-command",
            FAIL_CMD,
            "--max-iterations",
            "2",
        ]
    )
    out = capsys.readouterr().out

    assert code == 1
    assert "status:" in out
    assert "OFFLINE MODE" in out


def test_offline_passing_repo_converges_exits_0(capsys, tmp_path):
    code = main(
        [
            "run",
            "--repo",
            str(tmp_path),
            "--task",
            "no-op",
            "--offline",
            "--test-command",
            PASS_CMD,
        ]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "status:  converged" in out


def test_report_file_written_with_status_and_diff(tmp_path):
    repo = os.path.join(str(tmp_path), "repo")
    os.makedirs(repo)
    report = os.path.join(str(tmp_path), "report.json")

    main(
        [
            "run",
            "--repo",
            repo,
            "--task",
            "x",
            "--offline",
            "--test-command",
            PASS_CMD,
            "--report",
            report,
        ]
    )

    with open(report, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "status" in data
    assert "last_diff" in data


def test_no_test_command_reports_clean_error_not_traceback(capsys, tmp_path):
    # Empty repo, no --test-command -> the baseline run can't detect one. The CLI
    # must report a clean error and exit 1, not crash with a traceback.
    code = main(["run", "--repo", str(tmp_path), "--task", "x", "--offline"])
    captured = capsys.readouterr()

    assert code == 1
    assert "error:" in captured.err
    assert "Traceback" not in captured.err


def test_trace_file_written(tmp_path):
    repo = os.path.join(str(tmp_path), "repo")
    os.makedirs(repo)
    trace = os.path.join(str(tmp_path), "trace.json")

    main(
        [
            "run",
            "--repo",
            repo,
            "--task",
            "x",
            "--offline",
            "--test-command",
            PASS_CMD,
            "--trace",
            trace,
        ]
    )

    with open(trace, "r", encoding="utf-8") as f:
        data = json.load(f)

    assert "trace" in data
    assert data["status"] == "converged"


def test_offline_constructs_no_llm_client(tmp_path):
    def boom(*args, **kwargs):
        raise AssertionError("LLMClient must not be constructed in --offline mode")

    # If --offline ever built an LLMClient, this patch would raise.
    with mock.patch("pandavas.orchestrator.LLMClient", boom):
        code = main(
            [
                "run",
                "--repo",
                str(tmp_path),
                "--task",
                "x",
                "--offline",
                "--test-command",
                PASS_CMD,
            ]
        )

    assert code == 0
