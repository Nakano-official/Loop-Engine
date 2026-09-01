"""Completion facts must survive the final push, not wait for another step."""

import sys
import unittest
from pathlib import Path
from unittest.mock import call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop  # noqa: E402


class GreenCheckpoint(unittest.TestCase):
    @patch("loop.publish")
    @patch("loop.run")
    @patch("loop.ledger")
    def test_green_is_written_before_the_step_is_committed(self, ledger, run, publish):
        order = []
        ledger.side_effect = lambda *args, **kwargs: order.append("ledger")
        run.side_effect = lambda *args, **kwargs: order.append("git")
        publish.side_effect = lambda *args, **kwargs: order.append("publish")

        loop.complete_green("S11", "finish the game", 1)

        self.assertEqual(order, ["ledger", "git", "git", "git", "publish"])
        ledger.assert_called_once_with("GREEN", step="S11", attempts=1)
        self.assertEqual(run.call_args_list[0], call(["git", "add", "-A"], check=True))


class RunCheckpoint(unittest.TestCase):
    @patch("loop.publish")
    @patch("loop.run")
    @patch("loop.ledger")
    @patch("loop.completion_recorded", return_value=False)
    def test_all_green_is_committed_before_it_is_published(
            self, recorded, ledger, run, publish):
        order = []
        ledger.side_effect = lambda *args, **kwargs: order.append("ledger")
        run.side_effect = lambda *args, **kwargs: order.append("git")
        publish.side_effect = lambda *args, **kwargs: order.append("publish")

        loop.complete_run({"S2", "S1"}, {"steps": [{"id": "S1"}, {"id": "S2"}]})

        self.assertEqual(order, ["ledger", "git", "git", "publish"])
        self.assertEqual(ledger.call_args.args[0], "ALL_GREEN")
        self.assertEqual(ledger.call_args.kwargs["steps"], ["S1", "S2"])
        self.assertEqual(run.call_args_list[0], call(
            ["git", "add", "--", "plan/ledger.jsonl"], check=True))
        publish.assert_called_once_with("run completion")

    @patch("loop.publish")
    @patch("loop.run")
    @patch("loop.ledger")
    @patch("loop.completion_recorded", return_value=True)
    def test_reopening_a_completed_plan_does_not_create_another_commit(
            self, recorded, ledger, run, publish):
        loop.complete_run({"S1"}, {"steps": [{"id": "S1"}]})
        ledger.assert_not_called()
        run.assert_not_called()
        publish.assert_not_called()


if __name__ == "__main__":
    unittest.main()
