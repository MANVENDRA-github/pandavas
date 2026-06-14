"""Deterministic test executor for pandavas (the "Bhima" component).

This is the system's ground truth: it runs a repository's existing test suite in
its existing local environment. There is no LLM, no network, no Docker, no
caching, and no parallelism here.

Overall red/green is the process exit code. For per-test results, pytest runs are
captured via an injected JUnit XML file automatically; any other framework that
emits JUnit XML can opt in by constructing LocalExecutor(junit_xml=<path>) so the
regression-aware gate works for it too. Without parseable per-test results the
caller falls back to exit-code-only pass/fail.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from .testresults import parse_junit_xml

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
        per_test: {test_id: status} from JUnit XML for pytest runs, else None.
    """

    __test__ = False  # not a pytest test class despite the "Test" prefix

    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    command: str
    duration_s: float
    per_test: Optional[dict] = None


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

    def __init__(
        self, timeout_s: int = DEFAULT_TIMEOUT_S, junit_xml: Optional[str] = None
    ) -> None:
        """Initialize the executor.

        Args:
            timeout_s: Max wall-clock seconds a test run may take before it is
                terminated and reported as a failure. Defaults to 300.
            junit_xml: Optional path (absolute, or relative to the repo) to a
                JUnit XML file the test command itself produces. When set, that
                file is parsed for per-test results instead of pytest's auto
                temp file -- enabling per-test rigor for any framework that can
                emit JUnit XML (jest-junit, gotestsum, etc.).
        """
        self.timeout_s = timeout_s
        self.junit_xml = junit_xml

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

        # Decide where per-test JUnit XML comes from. An explicit junit_xml means
        # the command emits its own file (any framework); otherwise pytest gets an
        # auto-injected temp file. parse_path is what we read; temp_junit is what
        # we own and must clean up.
        run_command = command
        temp_junit = None
        parse_path = None
        if self.junit_xml:
            parse_path = (
                self.junit_xml
                if os.path.isabs(self.junit_xml)
                else os.path.join(repo_path, self.junit_xml)
            )
        elif "pytest" in command.lower():
            fd, temp_junit = tempfile.mkstemp(suffix=".xml")
            os.close(fd)
            run_command = f'{command} --junitxml="{os.path.abspath(temp_junit)}"'
            parse_path = temp_junit

        try:
            start = time.monotonic()
            try:
                completed = subprocess.run(
                    run_command,
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

            # Parse per-test results if available; never crash on failure.
            per_test = None
            if parse_path is not None:
                try:
                    with open(parse_path, "r", encoding="utf-8") as f:
                        per_test = parse_junit_xml(f.read())
                except (OSError, ValueError):
                    per_test = None

            return TestResult(
                passed=(completed.returncode == 0),
                exit_code=completed.returncode,
                stdout=completed.stdout,
                stderr=completed.stderr,
                command=command,
                duration_s=duration_s,
                per_test=per_test,
            )
        finally:
            # Only clean up the temp file we created (never the user's junit_xml).
            if temp_junit is not None:
                try:
                    os.remove(temp_junit)
                except OSError:
                    pass
