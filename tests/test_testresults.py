"""Tests for the deterministic JUnit XML parser."""

import pytest

from pandavas.testresults import failures, parse_junit_xml, passed


def test_testsuite_passed_failed_skipped():
    xml = """
    <testsuite name="suite" tests="3">
      <testcase classname="m.TestA" name="test_ok"/>
      <testcase classname="m.TestA" name="test_bad">
        <failure message="boom">AssertionError</failure>
      </testcase>
      <testcase classname="m.TestA" name="test_skip">
        <skipped message="nope"/>
      </testcase>
    </testsuite>
    """
    results = parse_junit_xml(xml)

    assert results == {
        "m.TestA::test_ok": "passed",
        "m.TestA::test_bad": "failed",
        "m.TestA::test_skip": "skipped",
    }
    assert failures(results) == {"m.TestA::test_bad"}
    assert passed(results) == {"m.TestA::test_ok"}


def test_error_child_maps_to_failed():
    xml = """
    <testsuite name="suite">
      <testcase classname="m" name="test_err">
        <error message="crash">Traceback</error>
      </testcase>
    </testsuite>
    """
    results = parse_junit_xml(xml)

    assert results == {"m::test_err": "failed"}
    assert failures(results) == {"m::test_err"}


def test_testsuites_root_wraps_multiple_suites():
    xml = """
    <testsuites>
      <testsuite name="s1">
        <testcase classname="a" name="t1"/>
      </testsuite>
      <testsuite name="s2">
        <testcase classname="b" name="t2">
          <failure>x</failure>
        </testcase>
      </testsuite>
    </testsuites>
    """
    results = parse_junit_xml(xml)

    assert results == {"a::t1": "passed", "b::t2": "failed"}


def test_empty_no_testcases():
    xml = '<testsuite name="empty" tests="0"></testsuite>'
    results = parse_junit_xml(xml)

    assert results == {}
    assert failures(results) == set()
    assert passed(results) == set()


def test_classname_present_and_absent():
    xml = """
    <testsuite name="suite">
      <testcase classname="pkg.Mod" name="with_class"/>
      <testcase name="no_class"/>
    </testsuite>
    """
    results = parse_junit_xml(xml)

    assert results["pkg.Mod::with_class"] == "passed"
    assert results["no_class"] == "passed"


def test_malformed_xml_raises_value_error():
    with pytest.raises(ValueError):
        parse_junit_xml("<testsuite><testcase name='oops'></testsuite>")
