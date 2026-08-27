import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/autonomy_preflight.py"


class AutonomyPreflightTest(unittest.TestCase):
    def invoke(self, host, source, path):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--host", host, "--source", str(source)],
            text=True, capture_output=True, check=False, env=os.environ | {"PATH": str(path)},
        )

    def test_reports_supported_only_when_the_host_and_adapter_are_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            result = self.invoke("codex", ROOT, root)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["supported"])
        self.assertEqual({"adapter": True, "host_command": True, "queue": True}, report["checks"])

    def test_reports_claude_supported_when_the_native_stop_hook_adapter_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "claude"
            executable.write_text("#!/bin/sh\nprintf '2.1.246 (Claude Code)\\n'\n", encoding="utf-8")
            executable.chmod(0o755)
            result = self.invoke("claude", ROOT, root)
        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["supported"])
        self.assertEqual({"adapter": True, "host_command": True, "stop_hook": True}, report["checks"])

    def test_rejects_a_claude_version_below_the_tested_stop_hook_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "claude"
            executable.write_text("#!/bin/sh\nprintf '2.1.245 (Claude Code)\\n'\n", encoding="utf-8")
            executable.chmod(0o755)
            result = self.invoke("claude", ROOT, root)
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["checks"]["stop_hook"])

    def test_rejects_enablement_when_host_or_adapter_is_not_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.invoke("claude", ROOT, Path(directory))
            self.assertEqual(2, result.returncode)
            self.assertFalse(json.loads(result.stdout)["supported"])

            result = self.invoke("codex", Path(directory), Path(directory))
            self.assertEqual(2, result.returncode)
            self.assertFalse(json.loads(result.stdout)["supported"])


if __name__ == "__main__":
    unittest.main()
