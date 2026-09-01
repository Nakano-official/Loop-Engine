import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from host.dashboard.actions import Launchers


class LauncherAllowlist(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name) / "config.json"
        self.config.write_text(json.dumps({"launchers": {"game": {
            "label": "Game", "argv": ["python", "-m", "game"], "cwd": self.temp.name
        }}}), encoding="utf-8")
        self.launchers = Launchers(self.config)

    def tearDown(self):
        self.temp.cleanup()

    @patch("host.dashboard.actions.subprocess.Popen")
    def test_a_named_launcher_uses_argv_without_a_shell(self, popen):
        popen.return_value.pid = 42
        self.assertEqual(self.launchers.launch("game"), 42)
        popen.assert_called_once_with(["python", "-m", "game"], cwd=self.temp.name, shell=False)

    def test_http_input_cannot_become_a_command(self):
        with self.assertRaisesRegex(ValueError, "unknown launcher"):
            self.launchers.launch("game & calc.exe")


if __name__ == "__main__":
    unittest.main()
