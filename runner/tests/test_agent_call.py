"""The ceiling that fires is the one that was handed over.

solver-run and planner-run each apply `timeout --kill-after=30 "${2:-900}"`. A
limit raised in TIMEOUTS but not passed as that second argument changes nothing:
run 5's planning was killed at 900s twice while loop.py read 1800.

    python3 -m unittest discover -s runner/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loop import (  # noqa: E402
    BACKSTOP_MARGIN, PLANNER_RUN, SOLVER_RUN, TIMEOUTS, agent_command,
)

# The default inside solver-run/planner-run, applied when argument 2 is absent.
SCRIPT_DEFAULT = 900


class TheLimitIsHandedOver(unittest.TestCase):
    def test_the_planner_call_carries_its_limit(self) -> None:
        argv = agent_command("planner", PLANNER_RUN, Path("/srv/loop/planner/brief/plan.md"),
                             TIMEOUTS["planner"])
        self.assertEqual(argv[:3], ["sudo", "-u", "planner"])
        self.assertEqual(argv[-1], str(TIMEOUTS["planner"]))

    def test_the_solver_call_carries_its_limit(self) -> None:
        argv = agent_command("solver", SOLVER_RUN, Path("/srv/loop/brief/impl.md"),
                             TIMEOUTS["solver"])
        self.assertEqual(argv[:3], ["sudo", "-u", "solver"])
        self.assertEqual(argv[-1], str(TIMEOUTS["solver"]))

    def test_a_configured_limit_above_the_script_default_would_have_no_effect_unpassed(self) -> None:
        # Guards the shape of the bug rather than the number: as long as any
        # configured ceiling exceeds the scripts' own default, leaving it out of
        # the argv silently lowers it.
        raised = [k for k in ("planner", "solver") if TIMEOUTS[k] > SCRIPT_DEFAULT]
        for key in raised:
            argv = agent_command(key, Path(f"/srv/loop/bin/{key}-run"),
                                 Path("/brief.md"), TIMEOUTS[key])
            self.assertIn(str(TIMEOUTS[key]), argv,
                          f"{key}'s limit is above the script default and must be passed")

    def test_the_runners_own_timeout_sits_above_the_agents(self) -> None:
        # If the backstop fired first, the runner would report "still running"
        # for a process the script was about to kill, and would say so about an
        # agent it cannot signal.
        self.assertGreater(BACKSTOP_MARGIN, 30, "must clear the scripts' --kill-after=30")


if __name__ == "__main__":
    unittest.main()
