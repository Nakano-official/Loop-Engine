"""The flow against the real box: the host's pipeline drives loop-window over
the runner key, the window builds the workspace as runner, exec runs the
generated tests with no network and no write access, and the verdict comes
back as records.

Needs the box up and provisioned (45-engine.sh). Skipped unless LOOP_BOX=1.
The design is the idle game as written -- TypeScript, browser-dom -- and the
solver is a stand-in that returns the TypeScript reference implementation,
so no model is involved: what is tested is the plumbing.
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import pipeline  # noqa: E402

pytestmark = pytest.mark.skipif(os.environ.get("LOOP_BOX") != "1", reason="LOOP_BOX=1 not set")

DESIGN = ROOT / "docs" / "formats" / "examples" / "idlegame.design.json"
CORRECT = {p.stem: p.read_text(encoding="utf-8")
           for p in (ROOT / "adapters" / "typescript" / "tests" / "idlegame").glob("*.ts")}


def reference(d, module, feedback):
    return {f"app/{module['name']}.ts": CORRECT[module["name"]]}


def test_the_box_takes_the_idle_game_to_green(tmp_path):
    ledger = tmp_path / "ledger.jsonl"
    out = pipeline.run(DESIGN, reference, pipeline.RemoteWindow(), "box-test",
                       ledger=pipeline.Ledger(ledger))
    assert out.stage == "done", (out.reason, out.detail)
    assert out.green == ["catalog", "economy", "scale", "format", "rules", "save", "view", "game"]


def test_the_box_sends_a_stuck_module_back_to_the_design(tmp_path):
    def stuck(d, module, feedback):
        if module["name"] == "rules":
            return {"app/rules.ts": CORRECT["rules"].replace("state.resource + 1.0", "state.resource + 2.0")}
        return reference(d, module, feedback)

    out = pipeline.run(DESIGN, stuck, pipeline.RemoteWindow(), "box-test", max_attempts=2,
                       ledger=pipeline.Ledger(tmp_path / "ledger.jsonl"))
    assert out.stage == "モジュール設計" and "granularity" in out.reason
    assert out.detail["examples"] == ["M4.E1"]
