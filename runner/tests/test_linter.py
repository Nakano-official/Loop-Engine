"""L14 -- a contract states the shape of what it hands over.

The rule exists because of one real step. `def buy_max_affordable(...) -> tuple`
passed every other rule, went out to the solver, and could not be built: the
arity is not in the signature, the stub returned a one-element tuple, and the
test's `result, count = ...` died unpacking it. RED_GATE called that a broken
call rather than a red test, correctly, and neither the solver (which sees only
the signature during STUB) nor the planner (P5 will not let it edit a green
step) could repair it afterwards.

    python3 -m unittest discover -s runner/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loop import validate_plan  # noqa: E402


def step(sid, kind, provides, requires=(), depends=()):
    return {
        "id": sid,
        "kind": kind,
        "goal": f"build {sid}",
        "depends_on": list(depends),
        "contracts": {"requires": list(requires), "provides": list(provides),
                      "invariants": []},
        "acceptance": [
            {"case": "normal", "given": "a new game", "then": "resources == 0.0"},
            {"case": "boundary", "given": "resources == 0.0", "then": "buy() returns False"},
            {"case": "error", "given": "an unknown id", "then": "raises KeyError"},
        ],
        "files_write": [f"src/pkg/{sid.lower()}.py"],
        "files_test": [f"tests/test_{sid.lower()}.py"],
        "expected_tests": 3,
        "max_attempts": 3,
        "review_gate": False,
    }


def plan(*provides):
    """The smallest plan that satisfies every other rule, so anything the
    linter reports is L14 and nothing else."""
    first, second = provides
    return {
        "version": 1,
        "steps": [
            step("S1", "skeleton", first),
            step("S2", "integration", second, requires=first, depends=["S1"]),
        ],
    }


class TheShapeMustBeStated(unittest.TestCase):
    def problems(self, *provides):
        return validate_plan(plan(*provides))

    def test_a_plan_whose_contracts_state_their_contents_is_valid(self) -> None:
        self.assertEqual(self.problems(
            ["class GameState(resources: float, owned: dict[str, int])",
             "def new_game() -> GameState"],
            ["def save(state: GameState) -> dict[str, float]",
             "def catalog() -> list[str]"]), [])

    def test_a_bare_return_type_is_rejected(self) -> None:
        # The step this rule was written for.
        problems = self.problems(
            ["def new_game() -> GameState"],
            ["def buy_max_affordable(state: GameState) -> tuple"])
        self.assertEqual(len(problems), 1)
        self.assertIn("L14", problems[0])
        self.assertIn("tuple", problems[0])

    def test_a_bare_parameter_type_is_rejected(self) -> None:
        # A caller cannot build an argument it has no description of, either.
        problems = self.problems(
            ["def new_game() -> GameState"],
            ["def production_rate(catalog: dict) -> float"])
        self.assertEqual(len(problems), 1)
        self.assertIn("L14", problems[0])

    def test_a_bare_field_on_a_declared_class_is_rejected(self) -> None:
        problems = self.problems(
            ["class GameState(resources: float, owned: dict)"],
            ["def save(state: GameState) -> dict[str, float]"])
        self.assertEqual(len(problems), 1)
        self.assertIn("owned", problems[0])

    def test_every_bare_type_in_one_signature_is_named(self) -> None:
        problems = self.problems(
            ["def new_game() -> GameState"],
            ["def build(generators: list) -> dict"])
        self.assertEqual(len(problems), 1)
        self.assertIn("dict, list", problems[0])

    def test_a_named_type_is_never_a_bare_container(self) -> None:
        # -> Purchase is the preferred answer, not a grudging exception.
        self.assertEqual(self.problems(
            ["class Purchase(state: GameState, bought: int)",
             "def new_game() -> GameState"],
            ["def buy_max_affordable(state: GameState) -> Purchase"]), [])

    def test_prose_beside_a_signature_is_not_read_as_a_type(self) -> None:
        # provides lines carry a trailing note about where the symbol lives, and
        # a plan may well say "list" in it. Only annotated positions count.
        self.assertEqual(self.problems(
            ["def new_game() -> GameState  -- defined in pkg.core, returns a dict of counts"],
            ["def save(state: GameState) -> dict[str, float]"]), [])


if __name__ == "__main__":
    unittest.main()
