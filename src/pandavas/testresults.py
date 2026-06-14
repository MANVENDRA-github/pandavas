"""Deterministic JUnit XML parsing into per-test results (P2).

Parses the JUnit XML pytest emits with --junitxml into {test_id: status}, the
per-test core Bhima uses for red->green and regression checks. No LLM, no file
I/O (operate on the passed-in text), no executor coupling.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def parse_junit_xml(xml_text: str) -> dict[str, str]:
    """Parse JUnit XML text into {test_id: status}.

    Handles both a <testsuites> root and a single <testsuite> root, iterating
    every <testcase>. test_id is "<classname>::<name>" when classname is present
    and non-empty, else just "<name>". Status is "failed" for a <failure>/<error>
    child, "skipped" for a <skipped> child, else "passed".

    Args:
        xml_text: The JUnit XML document as a string.

    Returns:
        Mapping of test id to status. Empty if there are no testcases.

    Raises:
        ValueError: If the XML is malformed.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise ValueError(f"Malformed JUnit XML: {exc}") from exc

    results: dict[str, str] = {}
    for testcase in root.iter("testcase"):
        name = testcase.get("name", "")
        classname = testcase.get("classname", "")
        test_id = f"{classname}::{name}" if classname else name

        if testcase.find("failure") is not None or testcase.find("error") is not None:
            status = "failed"
        elif testcase.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"

        results[test_id] = status

    return results


def failures(results: dict[str, str]) -> set[str]:
    """Return the set of test ids whose status is "failed" (errors map here too)."""
    return {tid for tid, status in results.items() if status == "failed"}


def passed(results: dict[str, str]) -> set[str]:
    """Return the set of test ids whose status is "passed"."""
    return {tid for tid, status in results.items() if status == "passed"}
