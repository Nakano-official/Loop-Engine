"""What changes when the plan is written in the other language, and what does not.

The list of things that had to change is short, and that is the finding: the
gates' arithmetic, the write fence, the ledger, the escalation rules and every
linter rule but L14's vocabulary were language-independent already. Only their
Python-shaped expression was not.

The tests here are the four that did change, plus the one that did not change
but was WRONG -- parse_junit read the first <testsuite> and pytest only ever
writes one, so nothing had ever shown that it was reading a suite rather than a
report.

    python3 -m unittest discover -s runner/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop  # noqa: E402
from loop import (  # noqa: E402
    LANGUAGE, LANGUAGES, failure_kind, load_settings, modules_of, parse_junit,
    test_argv, validate_plan,
)


class Language(unittest.TestCase):
    """Every test here writes module state, so every test here puts it back."""

    def setUp(self) -> None:
        self.saved = dict(LANGUAGE)

    def tearDown(self) -> None:
        LANGUAGE.clear()
        LANGUAGE.update(self.saved)

    def speak(self, name: str) -> None:
        load_settings({"language": name})


class WhichLanguage(Language):
    def test_a_plan_that_says_nothing_is_python(self):
        # Every plan written before this existed assumed it, and a plan is a
        # record of what was checked -- re-reading one must not change what it
        # meant.
        load_settings({})
        self.assertEqual(LANGUAGE["source_suffix"], ".py")

    def test_an_unknown_language_is_refused_rather_than_defaulted(self):
        # Silently falling back would check a TypeScript plan with pytest,
        # against the wrong suffixes, and every gate would report confidently
        # about files it never read.
        with self.assertRaises(SystemExit):
            self.speak("js")

    def test_the_two_are_the_whole_list(self):
        self.assertEqual(sorted(LANGUAGES), ["python", "typescript"])


class TheCommandThatProducesAVerdict(Language):
    def test_python_runs_pytest_from_the_frozen_venv(self):
        self.speak("python")
        argv, env = test_argv(["tests/test_engine.py"], Path("/tmp/r.xml"))
        self.assertIn(".venv/bin/pytest", argv[0].replace("\\", "/"))
        self.assertIn("--junitxml", argv)
        self.assertEqual(env["PYTHONDONTWRITEBYTECODE"], "1")

    def test_typescript_runs_the_frozen_vitest_once_and_not_in_watch_mode(self):
        # vitest's default is interactive. A runner that blocks forever is
        # indistinguishable from a step that never finishes.
        self.speak("typescript")
        argv, _ = test_argv(["tests/engine.test.ts"], Path("/tmp/r.xml"))
        self.assertIn("node_modules/.bin/vitest", argv[0].replace("\\", "/"))
        self.assertEqual(argv[1], "run")
        self.assertIn("--reporter=junit", argv)

    def test_neither_reaches_the_test_runner_through_a_fetcher(self):
        # npx would be willing to download one. Both are absolute paths into a
        # tree provisioning froze.
        for name in ("python", "typescript"):
            self.speak(name)
            argv, _ = test_argv([], Path("/tmp/r.xml"))
            # Spelled against POSIX rather than pathlib: the runner only ever
            # runs on the sandbox, and on Windows pathlib calls /srv/... relative
            # because it carries no drive letter.
            self.assertTrue(argv[0].replace("\\", "/").startswith("/"), argv[0])
            self.assertNotIn("npx", argv[0])


class WhereAThingLives(Language):
    def test_python_spells_it_with_dots(self):
        self.speak("python")
        self.assertEqual(
            modules_of(["src/incgame/engine.py", "src/incgame/__init__.py"]),
            ["incgame.engine", "incgame"])

    def test_typescript_spells_it_with_slashes(self):
        self.speak("typescript")
        self.assertEqual(
            modules_of(["src/idlegame/engine.ts", "src/idlegame/index.ts"]),
            ["idlegame/engine", "idlegame"])

    def test_the_other_language_s_files_are_not_modules(self):
        # A TypeScript plan that lists a .py has not written a module, and
        # saying it did would let L15 pass a contract nothing can satisfy.
        self.speak("typescript")
        self.assertEqual(modules_of(["src/idlegame/engine.py"]), [])


class ContractsMustStateAShape(Language):
    """L14, in each language's own type syntax. The rule does not change."""

    def plan(self, provides: str) -> dict:
        return {
            "steps": [{
                "id": "S1", "kind": "skeleton", "goal": "g", "depends_on": [],
                "acceptance": [
                    {"case": "normal", "given": "g", "then": "x == 1"},
                    {"case": "boundary", "given": "g", "then": "x == 0"},
                    {"case": "error", "given": "g", "then": "raises ValueError"},
                ],
                "contracts": {"provides": [provides], "requires": [],
                              "invariants": ["one"]},
                "files_write": ["src/pkg/models" + LANGUAGE["source_suffix"]],
                "files_test": ["tests/models_test" + LANGUAGE["source_suffix"]],
                "expected_tests": 3, "max_attempts": 2, "review_gate": False,
            }],
        }

    def l14(self, provides: str) -> list[str]:
        return [p for p in validate_plan(self.plan(provides)) if p.startswith("L14")]

    def test_a_bare_python_container_is_refused(self):
        self.speak("python")
        self.assertTrue(self.l14("src/pkg/models.py: def catalog() -> dict"))

    def test_a_parameterised_python_container_passes(self):
        self.speak("python")
        self.assertFalse(self.l14("src/pkg/models.py: def catalog() -> dict[str, Spec]"))

    def test_a_bare_typescript_container_is_refused(self):
        self.speak("typescript")
        self.assertTrue(self.l14("src/pkg/models.ts: function catalog(): Record"))

    def test_a_parameterised_typescript_container_passes(self):
        self.speak("typescript")
        self.assertFalse(
            self.l14("src/pkg/models.ts: function catalog(): Record<string, Spec>"))

    def test_each_language_only_knows_its_own_shapeless_names(self):
        # `dict` is not a TypeScript type and `Record` is not a Python one.
        # Sharing one vocabulary would reject valid contracts in both.
        self.speak("typescript")
        self.assertFalse(self.l14("src/pkg/models.ts: function f(): dict"))
        self.speak("python")
        self.assertFalse(self.l14("src/pkg/models.py: def f() -> Record"))


class ReadingTheReport(unittest.TestCase):
    def report(self, body: str) -> loop.TestRun:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "report.xml"
            path.write_text(body, encoding="utf-8")
            return parse_junit(path)

    def test_every_suite_is_counted_not_the_first(self):
        # pytest writes one <testsuite> for a whole run, so "the first suite"
        # and "the report" were the same thing and nothing could tell them
        # apart. vitest writes one per FILE, and VERIFY hands over all of
        # tests/ -- so the old reading would have counted one file and called
        # the rest green. A gate that under-counts failures is worse than none.
        run = self.report(
            '<testsuites tests="4" failures="2">'
            '<testsuite name="a.test.ts" tests="2" failures="0" errors="0" skipped="0">'
            '<testcase classname="a.test.ts" name="one"/>'
            '<testcase classname="a.test.ts" name="two"/>'
            '</testsuite>'
            '<testsuite name="b.test.ts" tests="2" failures="2" errors="0" skipped="0">'
            '<testcase classname="b.test.ts" name="three">'
            '<failure message="expected 0 to be greater than 0" type="AssertionError"/>'
            '</testcase>'
            '<testcase classname="b.test.ts" name="four">'
            '<failure message="nope" type="TypeError"/>'
            '</testcase>'
            '</testsuite></testsuites>')
        self.assertEqual((run.tests, run.failures), (4, 2))
        self.assertEqual(run.failure_kinds, ["AssertionError", "TypeError"])
        self.assertEqual(run.failed_files, ["b.test.ts"])

    def test_a_declared_type_is_believed_over_the_body(self):
        # vitest sets it; pytest never does. R5 turns on this value, so reading
        # it wrong changes which reds count as red.
        element = ET.fromstring('<failure message="m" type="TypeError">'
                                'tests/x.py:3: AssertionError</failure>')
        self.assertEqual(failure_kind(element), "TypeError")

    def test_without_a_declared_type_the_body_still_decides(self):
        element = ET.fromstring('<failure message="assert nan == 5.0">'
                                'tests/x.py:16: AssertionError</failure>')
        self.assertEqual(failure_kind(element), "AssertionError")

    def test_a_report_with_no_suite_at_all_is_an_error_not_an_absence(self):
        run = self.report('<testsuites tests="0"></testsuites>')
        self.assertEqual(run.errors, 1)


if __name__ == "__main__":
    unittest.main()
