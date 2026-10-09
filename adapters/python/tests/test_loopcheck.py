"""The comparison function, in both directions: what must pass passes, what
must fail fails, and every outcome leaves the record the window reads."""
import dataclasses
import enum
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import loopcheck  # noqa: E402

EXAMPLES = {
    "fixtures": {"CURSOR": {"type": "GeneratorSpec",
                            "value": {"name": "cursor", "base_cost": 15.0}}},
    "examples": [
        {"id": "M2.E1", "then": {"observe": ["p"], "equals": [33.75]}},
        {"id": "M1.E2", "then": {"observe": ["g"], "equals": [{"$": "CURSOR"}]}},
        {"id": "M1.E3", "then": {"raises": "UnknownGenerator"}},
        {"id": "M6.E1", "then": {"observe": ["v"], "equals": [{"rows": ["a", "b"], "owned": {"x": 1, "y": 2}}]}},
        {"id": "M9.E1", "then": {"observe": ["f"], "equals": [True]}},
        {"id": "M9.E2", "tol": {"rel": 0.1}, "then": {"observe": ["f"], "equals": [100.0]}},
    ],
}


class UnknownGenerator(Exception):
    pass


@dataclasses.dataclass
class Spec:
    name: str
    base_cost: float


class Phase(enum.Enum):
    PLAYING = "playing"


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    path = tmp_path / "examples.json"
    path.write_text(json.dumps(EXAMPLES), encoding="utf-8")
    monkeypatch.setenv("LOOP_EXAMPLES", str(path))
    monkeypatch.setenv("LOOP_RECORD_DIR", str(tmp_path))
    monkeypatch.setattr(loopcheck, "_examples", None)
    return tmp_path


def records(tmp_path):
    return [json.loads(l) for l in (tmp_path / "records.jsonl").read_text(encoding="utf-8").splitlines()]


# ---- must pass ------------------------------------------------------------

def test_equal_value_passes_and_is_recorded(env):
    loopcheck.check(loopcheck.start("M2.E1"), 33.75 + 1e-12)
    assert records(env) == [
        {"t": "start", "id": "M2.E1"},
        {"t": "check", "id": "M2.E1", "ok": True, "expected": [33.75], "actual": [33.75 + 1e-12]},
    ]


def test_record_compares_with_a_fixture(env):
    loopcheck.check(loopcheck.start("M1.E2"), Spec("cursor", 15.0))
    assert records(env)[-1]["ok"] is True


def test_map_order_does_not_matter(env):
    loopcheck.check(loopcheck.start("M6.E1"), {"owned": {"y": 2, "x": 1}, "rows": ("a", "b")})
    assert records(env)[-1]["ok"] is True


def test_named_error_passes(env):
    def boom():
        raise UnknownGenerator("dragon")
    loopcheck.check_raises(loopcheck.start("M1.E3"), boom)
    assert records(env)[-1] == {"t": "check", "id": "M1.E3", "ok": True,
                                "expected": {"raises": "UnknownGenerator"},
                                "actual": {"raises": "UnknownGenerator"}}


def test_example_tolerance_is_used(env):
    loopcheck.check(loopcheck.start("M9.E2"), 105.0)
    assert records(env)[-1]["ok"] is True


def test_enum_is_its_value():
    assert loopcheck.canon([Phase.PLAYING]) == ["playing"]


def test_nan_equals_nan_only():
    assert loopcheck.equal(float("nan"), float("nan"))
    assert not loopcheck.equal(float("nan"), 0.0)


# ---- must fail ------------------------------------------------------------

def test_wrong_value_fails_and_is_recorded(env):
    with pytest.raises(AssertionError):
        loopcheck.check(loopcheck.start("M2.E1"), 33.0)
    assert records(env)[-1]["ok"] is False


def test_list_order_matters(env):
    with pytest.raises(AssertionError):
        loopcheck.check(loopcheck.start("M6.E1"), {"owned": {"x": 1, "y": 2}, "rows": ["b", "a"]})


def test_bool_is_not_a_number(env):
    with pytest.raises(AssertionError):
        loopcheck.check(loopcheck.start("M9.E1"), 1)


def test_missing_field_fails(env):
    with pytest.raises(AssertionError):
        loopcheck.check(loopcheck.start("M1.E2"), {"name": "cursor"})


def test_wrong_error_fails(env):
    def boom():
        raise ValueError("no")
    with pytest.raises(AssertionError):
        loopcheck.check_raises(loopcheck.start("M1.E3"), boom)
    assert records(env)[-1]["actual"] == {"raises": "ValueError"}


def test_returning_instead_of_raising_fails(env):
    with pytest.raises(AssertionError):
        loopcheck.check_raises(loopcheck.start("M1.E3"), lambda: Spec("x", 1.0))
    assert records(env)[-1]["actual"] == {"returned": {"name": "x", "base_cost": 1.0}}


def test_tolerance_is_not_unlimited(env):
    with pytest.raises(AssertionError):
        loopcheck.check(loopcheck.start("M9.E2"), 120.0)


def test_crash_leaves_start_without_check(env):
    ex = loopcheck.start("M2.E1")
    with pytest.raises(ZeroDivisionError):
        loopcheck.check(ex, 1 / 0)
    assert records(env) == [{"t": "start", "id": "M2.E1"}]


def test_unknown_example_is_recorded_then_refused(env):
    with pytest.raises(KeyError):
        loopcheck.start("M404.E1")
    assert records(env) == [{"t": "start", "id": "M404.E1"}]


def test_a_value_without_canonical_form_is_refused():
    with pytest.raises(TypeError):
        loopcheck.canon(object())
