import importlib.util
import json
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

            autonomy_hook_config.update(path, command, remove=True)
            configured = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("peer", configured["hooks"]["Stop"][0]["hooks"][0]["command"])
            self.assertEqual("keep", configured["hooks"]["Other"][0]["hooks"][0]["command"])


if __name__ == "__main__":
    unittest.main()
