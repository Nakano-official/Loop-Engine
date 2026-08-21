"""The report reader, checked directly.

parse_junit is where the gates' arithmetic lives: RED_GATE and VERIFY both do
nothing but ask it questions. Until now nothing checked it, and the cost of that
showed up twice on real runs -- R5 read the wrong attribute and rejected honest
assertions, and `green` ignored skips, so a test that stopped running counted as
a test that passed.

Standard library only, like the runner itself. Nothing here needs a venv:

    python3 -m unittest discover -s runner/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loop import parse_junit  # noqa: E402


def report(cases: str, **counts: int) -> str:
    attrs = " ".join(f'{k}="{v}"' for k, v in counts.items())
    return f'<testsuites><testsuite name="pytest" {attrs}>{cases}</testsuite></testsuites>'


PASS = '<testcase classname="tests.test_models" name="test_rate"/>'
FAIL = ('<testcase classname="tests.test_models" name="test_tick">'
        '<failure message="assert nan == 5.0">tests/test_models.py:16: AssertionError'
        '</failure></testcase>')
ERROR = ('<testcase classname="tests.test_models" name="test_import">'
         '<error message="collection failure">tests/test_models.py:1: ImportError'
         '</error></testcase>')
SKIP = ('<testcase classname="tests.test_models" name="test_save">'
        '<skipped type="pytest.skip" message="not implemented"/></testcase>')


class ReadingAReport(unittest.TestCase):
    def parse(self, xml: str):
        path = Path(self.tmp.name) / "report.xml"
        path.write_text(xml, encoding="utf-8")
        return parse_junit(path, output="(pytest output)")

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_every_test_passed(self) -> None:
        run = self.parse(report(PASS * 2, tests=2, failures=0, errors=0, skipped=0))
        self.assertTrue(run.green)
        self.assertEqual(run.tests, 2)
        self.assertEqual(run.passed_names, ["test_rate", "test_rate"])
        self.assertEqual(run.failed_files, [])

    def test_a_failure_is_not_green(self) -> None:
        run = self.parse(report(PASS + FAIL, tests=2, failures=1, errors=0, skipped=0))
        self.assertFalse(run.green)
        self.assertEqual(run.failures, 1)
        self.assertEqual(run.failed_files, ["tests.test_models"])
        # R5 reads the class off the body's last line, not off the message --
        # pytest drops the "AssertionError: " prefix whenever the explanation
        # spans lines, which is most assertions about attributes.
        self.assertEqual(run.failure_kinds, ["AssertionError"])

    def test_an_error_is_not_green(self) -> None:
        run = self.parse(report(PASS + ERROR, tests=2, failures=0, errors=1, skipped=0))
        self.assertFalse(run.green)
        self.assertEqual(run.errors, 1)
        self.assertEqual(run.failed_files, ["tests.test_models"])
        self.assertEqual(run.passed_names, ["test_rate"])

    def test_a_skip_is_not_green(self) -> None:
        # The hole this file was written for. pytest calls this run a success:
        # no failures, no errors, exit code 0. One of the two tests never ran,
        # so the suite proved half of what it claims to.
        run = self.parse(report(PASS + SKIP, tests=2, failures=0, errors=0, skipped=1))
        self.assertFalse(run.green)
        self.assertEqual(run.skipped, 1)
        self.assertEqual(run.skipped_names, ["tests.test_models::test_save"])
        # A skipped test is not a passing test and must not be counted as one:
        # RED_GATE's R4 asks whether anything already passes against the stub.
        self.assertEqual(run.passed_names, ["test_rate"])

    def test_an_empty_suite_is_not_green(self) -> None:
        # Nothing failed, because nothing ran. RED_GATE catches this at R1 by
        # comparing against expected_tests; VERIFY has no expected count and
        # relies on this.
        run = self.parse(report("", tests=0, failures=0, errors=0, skipped=0))
        self.assertFalse(run.green)
        self.assertEqual(run.tests, 0)


class WhenTheReportCannotBeRead(unittest.TestCase):
    """Unreadable is an error, never an absence. A report that says nothing must
    not be read as "nothing failed" -- that would pass a step on a run that
    never happened."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "report.xml"

    def test_no_file_at_all(self) -> None:
        run = parse_junit(self.path, output="pytest: command not found")
        self.assertFalse(run.green)
        self.assertEqual(run.errors, 1)
        self.assertEqual(run.tests, 0)

    def test_truncated_xml(self) -> None:
        # What a killed pytest leaves behind.
        self.path.write_text('<testsuites><testsuite tests="3"', encoding="utf-8")
        run = parse_junit(self.path)
        self.assertFalse(run.green)
        self.assertEqual(run.errors, 1)

    def test_well_formed_xml_that_is_not_a_report(self) -> None:
        self.path.write_text("<something-else/>", encoding="utf-8")
        run = parse_junit(self.path)
        self.assertFalse(run.green)
        self.assertEqual(run.errors, 1)


if __name__ == "__main__":
    unittest.main()
