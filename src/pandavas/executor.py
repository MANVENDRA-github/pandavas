"""Deterministic test executor for pandavas (the "Bhima" component).

This is the system's ground truth: it runs a repository's existing test suite in
its existing local environment and reports red/green based on the process exit
code. There is no LLM, no network, no Docker, no caching, and no parallelism
here -- none of that is in scope for P0 (see docs/SPEC.md sections 5 and 10).

Pass/fail is determined by exit code ONLY. Parsing per-framework pass/fail counts
from test output is explicitly out of scope for P0.
"""

from __future__ import annotations

import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

DEFAULT_TIMEOUT_S = 300


@dataclass(frozen=True)
class TestResult:
    """Immutable outcome of a single test run.

    Attributes:
        passed: True iff the process exited with code 0.
        exit_code: The process exit code (-1 on timeout).
        stdout: Captured standard output.
        stderr: Captured standard error (plus a note on timeout).
        command: The resolved command that was actually run.
        duration_s: Wall-clock duration of the run, in seconds.
    """

    __test__ = False  # not a pytest test class despite the "Test" prefix

    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str
    duration_s: float


def detect_test_command(repo_path: str) -> str | None:
    """Infer a sensible default test command from a repo's manifest files.

    Inspects the repo root only and returns the first match in this order:
        - pyproject.toml | setup.py | requirements.txt | a tests/ dir -> "pytest"
        - package.json                                                -> "npm test"
        - go.mod                                                      -> "go test ./..."
        - Cargo.toml                                                  -> "cargo test"
        - pom.xml                                                     -> "mvn test"

    Args:
        repo_path: Path to the repository root.

    Returns:
        The detected test command, or None if no known manifest is present.
    """

    def has(name: str) -> bool:
        return os.path.isfile(os.path.join(repo_path, name))

    tests_dir = os.path.join(repo_path, "tests")
    if (
        has("pyproject.toml")
        or has("setup.py")
        or has("requirements.txt")
        or os.path.isdir(tests_dir)
    ):
        return "pytest"
    if has("package.json"):
        return "npm test"
    if has("go.mod"):
        return "go test ./..."
    if has("Cargo.toml"):
        return "cargo test"
    if has("pom.xml"):
        return "mvn test"
    return None


class Executor(ABC):
    """Interface for running a repository's tests.

    This abstraction exists so the execution backend can later be swapped (e.g.
    to a hosted sandbox) without touching any caller or agent logic. Only the
    local backend is implemented for P0.
    """

    @abstractmethod
    def run_tests(
        self, repo_path: str, test_command: str | None = None
    ) -> TestResult:
        """Run the repo's tests and return a TestResult."""
        raise NotImplementedError


class LocalExecutor(Executor):
    """Runs tests as a local subprocess in the repo's existing environment."""

    def __init__(self, timeout_s: int = DEFAULT_TIMEOUT_S) -> None:
        """Initialize the executor.

        Args:
            timeout_s: Max wall-clock seconds a test run may take before it is
                terminated and reported as a failure. Defaults to 300.
        """
        self.timeout_s = timeout_s

    def run_tests(
        self, repo_path: str, test_command: str | None = None
    ) -> TestResult:
        """Resolve a command and run the repo's tests locally.

        Command resolution: an explicit ``test_command`` always wins; otherwise
        it is auto-detected via :func:`detect_test_command`. If neither yields a
        command, a ValueError is raised.

        Args:
            repo_path: Path to the repository root (used as the working dir).
            test_command: Optional override that always takes precedence over
                detection.

        Returns:
            A TestResult; ``passed`` is True iff the exit code is 0. A timeout
            yields ``passed=False`` and ``exit_code=-1`` rather than raising.

        Raises:
            ValueError: If no command is provided and none can be detected.
        """
        command = test_command or detect_test_command(repo_path)
        if command is None:
            raise ValueError(
                "Could not detect a test command for repo "
                f"{repo_path!r}; pass test_command explicitly."
            )

        start = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=self.timeout_s,
            )
        except subprocess.TimeoutExpired as exc:
            duration_s = time.monotonic() - start
            stdout = exc.stdout or ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode(errors="replace")
            stderr = exc.stderr or ""
            if isinstance(stderr, bytes):
                stderr = stderr.decode(errors="replace")
            note = (
                f"[pandavas] test command timed out after {self.timeout_s}s "
                f"and was terminated: {command}"
            )
            stderr = f"{stderr}\n{note}" if stderr else note
            return TestResult(
                passed=False,
                exit_code=-1,
                stdout=stdout,
                stderr=stderr,
                command=command,
                duration_s=duration_s,
            )

        duration_s = time.monotonic() - start
        return TestResult(
            passed=(completed.returncode == 0),
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            command=command,
            duration_s=duration_s,
        )
