"""Who is asking, and therefore what they may do.

There are two ways in and they are not equivalent. At this machine, the browser
and the game are on the same desktop: whoever is looking can start the thing and
watch it run. Over the tailnet it is a phone. It can read every fact the runner
produced and it can refuse work, but it cannot see the window the game opens --
so it must not be able to say the game is good.

The Host header decides which one it is. That is the same value the loopback
check already leaned on, used the same way: a page that rebound DNS to reach
this port still carries its own name, and neither name is in the list.
"""

from __future__ import annotations

import json
from pathlib import Path

LOCAL = "local"
REMOTE = "remote"
LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def hostname(header: str) -> str:
    """The host out of a Host header: no port, no IPv6 brackets, lowercased."""
    return header.rsplit(":", 1)[0].strip("[]").lower() if header else ""


class Reach:
    """Reads the machine-local config each time, so publishing or unpublishing
    the dashboard does not mean restarting it."""

    def __init__(self, config_path: Path):
        self.config_path = config_path

    def published(self) -> dict:
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
        remote = data.get("remote") if isinstance(data, dict) else None
        return remote if isinstance(remote, dict) else {}

    def of(self, headers) -> tuple[str | None, str]:
        """(scope, user). A scope of None means the request is refused."""
        host = hostname(headers.get("Host", ""))
        if host in LOOPBACK:
            return LOCAL, ""

        remote = self.published()
        expected = hostname(str(remote.get("host", "")))
        allowed = remote.get("users")
        # Fail closed on both halves. No `remote` block, or one without a list
        # of people, means the dashboard is not published -- not that it is
        # published to everyone.
        if not expected or host != expected:
            return None, ""
        if not isinstance(allowed, list) or not allowed:
            return None, ""

        # Written by the tailscale serve proxy, which overwrites whatever the
        # client sent. It is worth something only BECAUSE the Host had to match
        # first: this header is trusted exactly as far as the name it arrived
        # under is.
        user = headers.get("Tailscale-User-Login", "")
        return (REMOTE, user) if user in allowed else (None, "")
