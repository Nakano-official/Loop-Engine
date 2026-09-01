"""What the planner is told about the machine it is planning for.

environment_facts gathers rather than states, because a written-down fact rots
and a gathered one cannot. The display is the case where that matters most: a
criterion like "the window opens" becomes a test that raises TclError, which is
an honest red -- RED_GATE passes it -- and which no implementation can ever turn
green. The step burns every attempt of every tier, then an escalation, and the
cause appears in nothing the solver or the planner can see.

    python3 -m unittest discover -s runner/tests
"""

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import loop  # noqa: E402


class WhatTheMachineLooksLike(unittest.TestCase):
    def facts(self, display: str, tk_ok: bool = True) -> str:
        with patch.dict(os.environ, {"DISPLAY": display}), patch("loop.run") as run:
            run.return_value = SimpleNamespace(
                returncode=0 if tk_ok else 1, stdout="Python 3.12.3", stderr="")
            return loop.environment_facts()

    def test_no_display_is_stated_together_with_what_to_do_about_it(self):
        facts = self.facts(display="")
        self.assertIn("NONE. DISPLAY is not set", facts)
        self.assertIn("checkable by pytest with no display", facts)

    def test_a_machine_that_does_have_a_screen_says_so_and_drops_the_warning(self):
        facts = self.facts(display=":0")
        self.assertIn("DISPLAY=:0", facts)
        self.assertNotIn("checkable by pytest with no display", facts)

    def test_a_missing_toolkit_is_reported_rather_than_assumed(self):
        self.assertIn("tkinter does NOT import", self.facts(display="", tk_ok=False))
        self.assertIn("tkinter imports", self.facts(display="", tk_ok=True))


if __name__ == "__main__":
    unittest.main()
