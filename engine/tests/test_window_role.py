"""run-role and progress, with a stand-in for the launcher: what a Claude role's
stream-json trace says while it runs, and what comes back when it is done."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import window as window_mod  # noqa: E402

THINKING = [{"type": "system", "subtype": "init"},
            {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 500},
            {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed"}},
            {"type": "system", "subtype": "thinking_tokens", "estimated_tokens": 24000}]
WROTE = [{"type": "assistant", "message": {"content": [
             {"type": "tool_use", "name": "Write", "input": {"file_path": "/srv/loop/roles/definer/out/definition.json"}}]}},
         {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": False, "content": "ok"}]}},
         {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "x"}}]}},
         {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "no"}]}}]
RESULT = [{"type": "result", "subtype": "success", "result": "done", "num_turns": 3, "duration_ms": 600000,
           "usage": {"input_tokens": 12, "output_tokens": 30000, "cache_read_input_tokens": 9000}}]


def lines(events):
    return "\n".join(json.dumps(e) for e in events) + "\n"


def test_a_role_still_thinking_is_told_apart_from_one_that_is_done():
    s = window_mod.trace_summary(lines(THINKING) + '{"type": "sys')       # a cut-off last line
    assert (s["thinking_tokens"], s["done"], s["rate_limit"], s["tool_count"]) == (24000, False, "allowed", 0)
    s = window_mod.trace_summary(lines(THINKING + WROTE + RESULT))
    assert s["done"] and s["tool_count"] == 2 and (s["tool_errors"], s["api_errors"]) == (1, 0)
    assert s["tools"][0] == {"name": "Write", "file": "definition.json"}
    assert s["usage"] == {"input_tokens": 12, "output_tokens": 30000, "cache_read_input_tokens": 9000,
                          "duration_ms": 600000, "num_turns": 3}
    # A failed tool call is the agent's own business; an API retry is what can stop a role.
    s = window_mod.trace_summary(lines(THINKING + [{"type": "system", "subtype": "api_retry"}]))
    assert (s["tool_errors"], s["api_errors"]) == (0, 1)


@pytest.fixture
def win(tmp_path):
    roles = tmp_path / "roles"
    for side in ("in", "out"):
        (roles / "definer" / side).mkdir(parents=True)
    return window_mod.Window(tmp_path / "work", window_mod.local_runner, roles=roles)


def test_run_role_gives_the_launcher_a_trace_and_takes_it_back(win):
    seen = {}

    def launcher(role, brief):
        out = win.roles / role / "out"
        seen["trace_dir"] = (out / "trace").is_dir()
        (out / "trace" / "progress.jsonl").write_text(lines(THINKING), encoding="utf-8")
        (out / "definition.json").write_text('{"items": [', encoding="utf-8")     # half-written
        seen["midway"] = win.progress(role)
        (out / "trace" / "progress.jsonl").write_text(lines(THINKING + WROTE + RESULT), encoding="utf-8")
        (out / "definition.json").write_text("{}", encoding="utf-8")
        return 0, "done"

    win.run_role_fn = launcher
    res = win.run_role("ws1", "definer", {"brief": "x"})
    assert seen["trace_dir"]
    assert seen["midway"]["running"] and seen["midway"]["thinking_tokens"] == 24000
    assert seen["midway"]["quiet_seconds"] < 5
    assert seen["midway"]["draft"] == '{"items": ['        # the file as far as it has got
    assert res["files"] == {"definition.json": "{}"} and res["usage"]["output_tokens"] == 30000
    assert '"result"' in res["trace"]
    assert win.progress("definer")["running"] is False
    with pytest.raises(ValueError):
        win.progress("solver")


def test_a_draft_counts_what_a_role_has_written_so_far():
    sys.path.insert(0, str(ROOT / "engine"))
    import apps
    design = {"modules": [{"id": "M1", "name": "a", "kind": "pure", "depends_on": [], "functions": {"f": {}},
                           "examples": [{}, {}]},
                          {"id": "M2", "name": "b", "kind": "assembly", "depends_on": ["M1"], "functions": {},
                           "examples": []}]}
    d = apps.draft_summary("designer", json.dumps(design))
    assert (d["modules"], d["written"], d["examples"]) == (2, 1, 2)
    assert d["design"]["modules"][1]["depends_on"] == ["a"]
    assert apps.draft_summary("definer", '{"items": [{"id": "D1", "statement": "x"}, {"id": "D2", "statement": ""}]}')         == {"items": 2, "written": 1}
    assert apps.draft_summary("tester", '{"items": {"D1": [{}], "D2": []}}') == {"items": 2, "with_examples": 1,
                                                                                 "examples": 1}
    assert apps.draft_summary("designer", '{"modules": [') is None          # an Edit half-way
