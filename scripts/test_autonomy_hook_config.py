import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("autonomy_hook_config.py")
SPEC = importlib.util.spec_from_file_location("autonomy_hook_config", SCRIPT)
autonomy_hook_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(autonomy_hook_config)


class AutonomyHookConfigTest(unittest.TestCase):
    def test_add_remove_preserves_peer_hooks_and_never_duplicates_its_exact_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            command = "python3 /suite/scripts/autonomy_hook.py --host codex"
            path.write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": "peer"}]}
            ], "Other": [{"hooks": [{"type": "command", "command": "keep"}]}]}}), encoding="utf-8")

            autonomy_hook_config.update(path, command)
            autonomy_hook_config.update(path, command)
            configured = json.loads(path.read_text(encoding="utf-8"))
            commands = [item["command"] for entry in configured["hooks"]["Stop"] for item in entry["hooks"]]
            self.assertEqual(["peer", command], commands)
            self.assertEqual("keep", configured["hooks"]["Other"][0]["hooks"][0]["command"])

            prompt = "python3 /suite/scripts/autonomy_prompt_hook.py --host codex"
            autonomy_hook_config.update(path, prompt, event="UserPromptSubmit")
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([prompt], [
                item["command"] for entry in configured["hooks"]["UserPromptSubmit"]
                for item in entry["hooks"]
            ])

            autonomy_hook_config.update(path, command, remove=True)
            autonomy_hook_config.update(path, prompt, event="UserPromptSubmit", remove=True)
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("peer", configured["hooks"]["Stop"][0]["hooks"][0]["command"])
            self.assertEqual("keep", configured["hooks"]["Other"][0]["hooks"][0]["command"])

    def test_new_entries_carry_a_timeout_while_legacy_entries_still_remove(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            command = "python3 /suite/scripts/autonomy_hook.py --host codex"
            path.write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": command}]}
            ]}}), encoding="utf-8")

            autonomy_hook_config.update(path, command, remove=True)
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([], configured["hooks"]["Stop"])

            autonomy_hook_config.update(path, command)
            configured = json.loads(path.read_text(encoding="utf-8"))
            item = configured["hooks"]["Stop"][0]["hooks"][0]
            self.assertEqual(command, item["command"])
            self.assertEqual(30, item["timeout"])

    def test_cli_installs_and_removes_the_exact_command(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            command = "python3 /suite/scripts/autonomy_hook.py --host codex"
            for extra in ([], ["--remove"]):
                result = subprocess.run(
                    [sys.executable, str(SCRIPT), "--config", str(path), "--command", command, *extra],
                    text=True, capture_output=True, check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([], configured["hooks"]["Stop"])

    def test_removal_fails_when_the_same_script_is_still_registered_differently(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            stale = "python3 /suite/scripts/autonomy_hook.py --host codex"
            other_interpreter = "/opt/py3/bin/python3 /suite/scripts/autonomy_hook.py --host codex"
            original = json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": stale}]},
                {"hooks": [{"type": "command", "command": other_interpreter}]},
            ]}})
            path.write_text(original, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "same python3"):
                autonomy_hook_config.update(path, stale, remove=True)
            self.assertEqual(original, path.read_text(encoding="utf-8"))

    def test_removal_ignores_entries_from_another_checkout(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hooks.json"
            command = "python3 /suite/scripts/autonomy_hook.py --host codex"
            other_checkout = "python3 /elsewhere/scripts/autonomy_hook.py --host codex"
            path.write_text(json.dumps({"hooks": {"Stop": [
                {"hooks": [{"type": "command", "command": command}]},
                {"hooks": [{"type": "command", "command": other_checkout}]},
            ]}}), encoding="utf-8")

            autonomy_hook_config.update(path, command, remove=True)
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual([other_checkout], [
                item["command"] for entry in configured["hooks"]["Stop"] for item in entry["hooks"]
            ])

    def test_malformed_configurations_are_rejected_before_any_write(self):
        cases = {
            "root-is-array": [1, 2],
            "hooks-not-object": {"hooks": []},
            "entries-not-list": {"hooks": {"Stop": {}}},
            "entry-not-object": {"hooks": {"Stop": ["entry"]}},
            "hook-item-not-object": {"hooks": {"Stop": [{"hooks": ["item"]}]}},
        }
        with tempfile.TemporaryDirectory() as directory:
            for name, payload in cases.items():
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaises(ValueError):
                    autonomy_hook_config.update(path, "python3 /suite/scripts/autonomy_hook.py")
                self.assertEqual(json.dumps(payload), path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
