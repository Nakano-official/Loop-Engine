"""The platforms' half of the safety check (DESIGN 7): what does not change
from app to app is checked once, here.

Every platform's page carries a CSP that lets nothing load or connect and
lets exactly its one script run, by hash; the window seals that hash in when
it builds the page. Every shell draws text as text.
"""
import base64
import hashlib
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "engine"))
import window as window_mod  # noqa: E402

PLATFORMS = sorted(p.parent.name for p in (ROOT / "adapters" / "platforms").glob("*/platform.json"))


def csp(html: str) -> dict[str, list[str]]:
    m = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]*)">', html)
    assert m, "the page has no CSP"
    out = {}
    for part in m.group(1).split(";"):
        words = part.split()
        if words:
            out[words[0]] = words[1:]
    return out


@pytest.mark.parametrize("name", PLATFORMS)
def test_every_page_lets_nothing_in_or_out_but_its_own_script(name):
    page = (ROOT / "adapters" / "platforms" / name / "page.html").read_text(encoding="utf-8")
    policy = csp(page)
    assert policy["default-src"] == ["'none'"]          # connect-src, frame-src ... fall back to it
    assert "connect-src" not in policy
    assert policy["script-src"] == ["'__SCRIPT_HASH__'"]
    assert policy["base-uri"] == ["'none'"] and policy["form-action"] == ["'none'"]
    assert page.count("<script>") == 1


@pytest.mark.parametrize("name", PLATFORMS)
def test_every_shell_draws_text_as_text(name):
    shell = (ROOT / "adapters" / "platforms" / name / "shell.ts").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in shell, f"{name}/shell.ts uses {sink}"


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_the_seal_is_the_hash_the_browser_computes(newline):
    page = (ROOT / "adapters" / "platforms" / "browser-dom" / "page.html").read_text(encoding="utf-8")
    page = page.replace("\r\n", "\n").replace("\n", newline)
    js = 'console.log("</p>");' + newline + "var a = 1;"
    html = window_mod._seal(page.replace("__BUNDLE__", js))
    # What a browser hashes: the script's text, after CR LF became LF.
    text = html.split("<script>", 1)[1].split("</script>", 1)[0].replace("\r\n", "\n")
    expected = "sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()
    assert csp(html)["script-src"] == [f"'{expected}'"]
    assert "__SCRIPT_HASH__" not in html
