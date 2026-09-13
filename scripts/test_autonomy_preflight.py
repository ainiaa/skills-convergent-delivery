import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts/autonomy_preflight.py"
SPEC = importlib.util.spec_from_file_location("autonomy_preflight", SCRIPT)
autonomy_preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(autonomy_preflight)


class AutonomyPreflightTest(unittest.TestCase):
    def invoke(self, host, source, path, config=None, verify_registration=False,
               expect_stop=None, expect_prompt=None):
        arguments = [sys.executable, str(SCRIPT), "--host", host, "--source", str(source)]
        if verify_registration:
            arguments.append("--verify-registration")
        if config is not None:
            arguments += ["--config", str(config)]
        if expect_stop is not None:
            arguments += ["--expect-stop", expect_stop]
        if expect_prompt is not None:
            arguments += ["--expect-prompt", expect_prompt]
        return subprocess.run(
            arguments,
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
        self.assertEqual({"adapter": True, "host_command": True}, report["checks"])

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

    def test_registration_check_fails_when_the_host_config_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            result = self.invoke(
                "codex", ROOT, root, config=root / "missing/hooks.json", verify_registration=True,
            )
        self.assertEqual(2, result.returncode)
        report = json.loads(result.stdout)
        self.assertFalse(report["checks"]["hook_registered"])
        self.assertFalse(report["supported"])

    def test_registration_check_passes_when_the_managed_hooks_are_registered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            config = root / "hooks.json"
            config.write_text(json.dumps({"hooks": {
                "Stop": [{"hooks": [{
                    "type": "command", "timeout": 30,
                    "command": f"/usr/bin/python3 {ROOT}/scripts/autonomy_hook.py --host codex",
                }]}],
                "UserPromptSubmit": [{"hooks": [{
                    "type": "command", "timeout": 30,
                    "command": f"/usr/bin/python3 {ROOT}/scripts/autonomy_prompt_hook.py --host codex",
                }]}],
            }}), encoding="utf-8")
            result = self.invoke("codex", ROOT, root, config=config, verify_registration=True)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertTrue(json.loads(result.stdout)["checks"]["hook_registered"])

    def test_claude_version_probe_failure_keeps_the_stop_hook_unsupported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "claude"
            executable.write_text("this file has no valid executable format\n", encoding="utf-8")
            executable.chmod(0o755)
            result = self.invoke("claude", ROOT, root)
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["checks"]["stop_hook"])

    def test_adapter_output_that_is_not_a_decision_report_fails_the_adapter_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            source = root / "suite"
            (source / "scripts").mkdir(parents=True)
            (source / "scripts" / "autonomy_hook.py").write_text(
                "#!/usr/bin/env python3\nprint('not-json')\n", encoding="utf-8",
            )
            result = self.invoke("codex", source, root)
        self.assertEqual(2, result.returncode)
        self.assertFalse(json.loads(result.stdout)["checks"]["adapter"])

    def test_malformed_host_configurations_read_as_unregistered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            (home / ".codex").mkdir(parents=True)
            with patch.dict(os.environ, {"HOME": str(home)}):
                self.assertEqual(
                    home / ".codex" / "hooks.json", autonomy_preflight.hook_config_path("codex"),
                )
                self.assertEqual(
                    home / ".claude" / "settings.json", autonomy_preflight.hook_config_path("claude"),
                )
            cases = {
                "root-is-array.json": [],
                "entries-not-list.json": {"hooks": {"Stop": {}}},
                "entry-not-object.json": {"hooks": {"Stop": ["entry"]}},
                "hook-item-not-object.json": {"hooks": {"Stop": [{"hooks": ["item"]}]}},
            }
            for name, payload in cases.items():
                path = root / name
                path.write_text(json.dumps(payload), encoding="utf-8")
                self.assertEqual([], autonomy_preflight.registered_commands(path, "Stop"))

    def test_codex_registration_requires_both_managed_hooks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "hooks.json"
            config.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{
                "type": "command",
                "command": f"/usr/bin/python3 {ROOT}/scripts/autonomy_hook.py --host codex",
            }]}]}}), encoding="utf-8")
            self.assertFalse(autonomy_preflight.hook_registered("codex", config))
            self.assertFalse(autonomy_preflight.hook_registered("claude", config))

            config.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [{
                "type": "command",
                "command": f"/usr/bin/python3 {ROOT}/scripts/autonomy_hook.py --host claude",
            }]}]}}), encoding="utf-8")
            self.assertTrue(autonomy_preflight.hook_registered("claude", config))

    def test_exact_command_expectation_rejects_a_stale_interpreter_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / "codex"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o755)
            config = root / "hooks.json"
            stale_stop = f"/usr/bin/python3 {ROOT}/scripts/autonomy_hook.py --host codex"
            stale_prompt = f"/usr/bin/python3 {ROOT}/scripts/autonomy_prompt_hook.py --host codex"
            config.write_text(json.dumps({"hooks": {
                "Stop": [{"hooks": [{"type": "command", "command": stale_stop}]}],
                "UserPromptSubmit": [{"hooks": [{"type": "command", "command": stale_prompt}]}],
            }}), encoding="utf-8")
            fresh_stop = stale_stop.replace("/usr/bin/python3", "/opt/py3/bin/python3")

            # The substring fallback would accept the stale entry; the exact
            # expectation must reject it.
            result = self.invoke(
                "codex", ROOT, root, config=config, verify_registration=True, expect_stop=fresh_stop,
            )
            self.assertEqual(2, result.returncode)
            self.assertFalse(json.loads(result.stdout)["checks"]["hook_registered"])

            result = self.invoke(
                "codex", ROOT, root, config=config, verify_registration=True,
                expect_stop=stale_stop, expect_prompt=stale_prompt,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(json.loads(result.stdout)["checks"]["hook_registered"])


if __name__ == "__main__":
    unittest.main()
