"""Read objective runner state and append human decisions.

The dashboard deliberately does not infer whether work is good.  It reports
facts already emitted by the runner and records what the human decided about a
specific, immutable request.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return records
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            records.append({"event": "UNREADABLE_LEDGER_RECORD", "line": number})
            continue
        if isinstance(value, dict):
            records.append(value)
    return records


# What may be decided from somewhere other than this machine. Refusing work
# needs nothing but judgement, and stopping a run is the one thing you want
# reachable from a phone. Saying "I played it and it is good" is a different
# act: the review exists precisely because no machine can check the screen, so
# a device that cannot open the window must not be able to certify it.
REMOTE_DECISIONS = {"review": {"revise"}, "escalation": {"respond", "stop"}}


def request_id(kind: str, value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(kind.encode("ascii") + b"\0" + encoded).hexdigest()[:16]


class DashboardState:
    def __init__(self, project: Path, data_dir: Path):
        self.project = project.resolve()
        self.data_dir = data_dir.resolve()
        self.decisions_file = self.data_dir / "decisions.jsonl"
        # The server is threaded, so two decisions can arrive at once. Checking
        # that a request is still pending and recording the answer have to be
        # one indivisible act, or the second answer is written against a view
        # of the world the first one already invalidated.
        self._lock = threading.Lock()

    def snapshot(self) -> dict[str, Any]:
        ledger = read_jsonl(self.project / "plan" / "ledger.jsonl")
        tasks = _read_json(self.project / "plan" / "tasks.json", {})
        decisions = read_jsonl(self.decisions_file)
        answered = {
            (item.get("kind"), item.get("request_id"))
            for item in decisions if item.get("event") == "HUMAN_DECISION"
        }
        steps = tasks.get("steps", []) if isinstance(tasks, dict) else []
        step_ids = [step.get("id") for step in steps if isinstance(step, dict)]
        green = []
        for record in ledger:
            if record.get("event") == "GREEN" and record.get("step") not in green:
                green.append(record.get("step"))

        escalation_path = self.project / "plan" / "ESCALATION.md"
        escalation = None
        if escalation_path.is_file():
            text = escalation_path.read_text(encoding="utf-8", errors="replace")
            escalation_id = request_id("escalation", text)
            escalation = {
                "id": escalation_id,
                "kind": "escalation",
                "title": "実装が停止し、人間の判断を待っています",
                "detail": text,
            }
            if ("escalation", escalation_id) in answered:
                escalation = None

        all_green = next(
            (record for record in reversed(ledger) if record.get("event") == "ALL_GREEN"),
            None,
        )
        review = None
        if all_green is not None:
            review_id = request_id("review", all_green)
            if ("review", review_id) not in answered:
                review = {
                    "id": review_id,
                    "kind": "review",
                    "title": "全ステップGreenです。成果物を実際に確認してください",
                    "detail": "機械的な受け入れ条件は完了しました。成果物を起動し、承認または差し戻しを記録してください。",
                }

        pending = [item for item in (escalation, review) if item is not None]
        last = ledger[-1] if ledger else None
        if escalation:
            phase = "escalated"
        elif review:
            phase = "review_required"
        elif all_green:
            phase = "human_reviewed"
        elif ledger:
            phase = "running" if last and last.get("event") != "RUN_ALL_STOP" else "stopped"
        else:
            phase = "not_started"

        return {
            "project": str(self.project),
            "phase": phase,
            "steps": {"total": len(step_ids), "green": len(green), "ids": step_ids},
            "pending": pending,
            "last_event": last,
            "recent_events": ledger[-50:],
            "decisions": decisions[-50:],
        }

    def decide(self, kind: str, request: str, decision: str, note: str,
               scope: str = "local", user: str = "") -> dict[str, Any]:
        with self._lock:
            return self._decide(kind, request, decision, note, scope, user)

    def _decide(self, kind: str, request: str, decision: str, note: str,
                scope: str, user: str) -> dict[str, Any]:
        snapshot = self.snapshot()
        matching = next(
            (item for item in snapshot["pending"]
             if item["id"] == request and item["kind"] == kind),
            None,
        )
        if matching is None:
            raise ValueError("the request is no longer pending")
        allowed = {
            "review": {"approve", "revise"},
            "escalation": {"respond", "stop"},
        }
        if decision not in allowed.get(kind, set()):
            raise ValueError("decision is not valid for this request")
        if scope != "local" and decision not in REMOTE_DECISIONS.get(kind, set()):
            raise ValueError(
                "that has to be decided at the machine that can run the result")
        if decision in {"revise", "respond"} and not note.strip():
            raise ValueError("this decision requires a note")
        record = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "event": "HUMAN_DECISION",
            "kind": kind,
            "request_id": request,
            "decision": decision,
            "note": note.strip(),
            # Where the answer came from is part of the answer. An approval
            # recorded from a phone would mean something different from one
            # recorded at the desk, so the record says which it was.
            "scope": scope,
            "user": user,
        }
        self._append(record)
        return record

    def _append(self, record: dict[str, Any]) -> None:
        """One line, appended and flushed to the disk.

        This used to read the whole file and write it back through a temporary
        file, which made every decision a rewrite of every earlier one: a
        crash mid-rewrite, or two writers racing, could destroy answers that
        were already safe.  An append cannot touch what is already there, and
        these records are the one thing here that no other system can
        reconstruct -- the runner knows what the tests did, not what the human
        concluded from playing the thing.
        """
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.decisions_file.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
