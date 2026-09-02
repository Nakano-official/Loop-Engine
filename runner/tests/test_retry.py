"""What costs the planner an attempt, and what does not.

The planner gets a small, fixed number of tries at a plan, and every one of
them is a paid call to a model. So the question "is this a violation?" is not
a matter of tidiness -- it decides whether a valid plan is thrown away.

The distinction pinned down here: a violation is something that would still be
wrong when `plan apply` runs. A file the runner has already deleted is not
that. It is a habit worth telling the planner about, and nothing more.

What the linter considers wrong is `test_linter.py`'s subject and is stubbed
out here on purpose -- these tests are about the arithmetic of attempts, and
would otherwise fail every time a plan gained a required field.

    python3 -m unittest discover -s runner/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop  # noqa: E402


class RetryFixture(unittest.TestCase):
    """The retry loop, with both the planner and the linter scripted."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "out"
        self.out.mkdir()
        self.saved = (loop.PLANNER_OUT, dict(loop.LIMITS), loop.call_planner,
                      loop.ledger, loop.proposal_problems)
        loop.PLANNER_OUT = self.out
        self.events: list[tuple[str, dict]] = []
        loop.ledger = lambda event, **fields: self.events.append((event, fields))

    def tearDown(self) -> None:
        out, limits, call, ledger, problems = self.saved
        loop.PLANNER_OUT = out
        loop.LIMITS.clear(); loop.LIMITS.update(limits)
        loop.call_planner = call
        loop.ledger = ledger
        loop.proposal_problems = problems
        self.temp.cleanup()

    def write_proposal(self, extra: dict[str, str] | None = None) -> None:
        """The three allowed names, plus whatever else the planner left behind."""
        for name in ("SYSTEM_SPEC.md", "CONTEXT.md", "tasks.json"):
            (self.out / name).write_text("{}", encoding="utf-8")
        for name, body in (extra or {}).items():
            (self.out / name).write_text(body, encoding="utf-8")

    def plan(self, writes: list, verdicts: list[list[str]]) -> tuple[int, list[str]]:
        """Run the loop. `writes[i]` is what the planner does on attempt i+1,
        `verdicts[i]` what the linter says about the result."""
        briefs: list[str] = []
        write = iter(writes)
        verdict = iter(verdicts)

        def fake_call(brief: str) -> str:
            briefs.append(brief)
            next(write)()
            return ""

        loop.call_planner = fake_call
        loop.proposal_problems = lambda proposal: list(next(verdict))
        # The brief is just the feedback here, so a test can read what the
        # planner would have been told.
        return loop.plan_with_retry(lambda feedback: feedback, "PLAN_TEST"), briefs


class AStrayFileIsNotAViolation(RetryFixture):
    def test_a_valid_plan_passes_even_with_a_scratch_file_beside_it(self):
        # The planner writes _calc.py to check its own arithmetic. The runner
        # deletes it before reading anything, so by the time the plan is judged
        # the file does not exist. Failing here would spend an attempt undoing
        # a condition the runner had already undone -- which is exactly what
        # run 7 did, on attempt 3, to a plan that was otherwise valid.
        loop.LIMITS["revisions"] = 3
        code, briefs = self.plan(
            [lambda: self.write_proposal({"_calc.py": "print(2 * 3)\n"})], [[]])
        self.assertEqual(code, 0)
        self.assertEqual(len(briefs), 1, "a valid plan must not be retried")
        self.assertFalse((self.out / "_calc.py").exists())

    def test_the_deletion_is_still_recorded(self):
        # Not a violation is not the same as not worth knowing. Whoever reads
        # the ledger afterwards should see that a file was removed.
        loop.LIMITS["revisions"] = 3
        self.plan([lambda: self.write_proposal({"_calc.py": "x = 1\n"})], [[]])
        pruned = [fields for event, fields in self.events if event == "PLAN_PRUNED"]
        self.assertEqual(pruned, [{"attempt": 1, "removed": ["_calc.py"]}])

    def test_a_directory_is_removed_the_same_way(self):
        loop.LIMITS["revisions"] = 3
        def write() -> None:
            self.write_proposal()
            (self.out / "__pycache__").mkdir()
            (self.out / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        code, briefs = self.plan([write], [[]])
        self.assertEqual((code, len(briefs)), (0, 1))
        self.assertFalse((self.out / "__pycache__").exists())

    def test_the_habit_is_reported_when_the_attempt_fails_for_another_reason(self):
        # The note is not silence: an attempt that is being retried anyway
        # carries it, so the planner learns to stop writing the scratch file
        # without ever being failed for it.
        loop.LIMITS["revisions"] = 1
        code, briefs = self.plan(
            [lambda: self.write_proposal({"_calc.py": "x = 1\n"}),
             lambda: self.write_proposal()],
            [["L4: S2 depends on a step that does not exist"], []])
        self.assertEqual(code, 0)
        self.assertIn("_calc.py", briefs[1])
        self.assertIn("B3", briefs[1])
        self.assertIn("L4", briefs[1])

    def test_a_plan_written_under_the_wrong_name_is_still_refused(self):
        # The one case where the stray file mattered. Deleting `task.json`
        # leaves nothing to apply, and the runner says so rather than applying
        # a proposal that is not there.
        loop.LIMITS["revisions"] = 0
        with self.assertRaises(loop.Halt):
            self.plan([lambda: (self.out / "task.json").write_text(
                "{}", encoding="utf-8")], [[]])


class TheAttemptCeiling(RetryFixture):
    def test_the_last_allowed_attempt_is_revisions_plus_one(self):
        # revisions is how many times the planner may be sent back, so the
        # number of calls is one more than that.
        loop.LIMITS["revisions"] = 2
        code, briefs = self.plan(
            [self.write_proposal] * 3, [["L1: bad"], ["L1: bad"], ["L1: bad"]])
        self.assertEqual((code, len(briefs)), (2, 3))

    def test_an_escalation_ends_the_loop_without_being_judged(self):
        # An escalation is an answer addressed to the human, not a draft. The
        # linter never sees it and it never costs a retry.
        loop.LIMITS["revisions"] = 2
        code, briefs = self.plan(
            [lambda: (self.out / loop.ESCALATE_NAME).write_text(
                "the requirements contradict each other", encoding="utf-8")],
            [])
        self.assertEqual((code, len(briefs)), (0, 1))


if __name__ == "__main__":
    unittest.main()
