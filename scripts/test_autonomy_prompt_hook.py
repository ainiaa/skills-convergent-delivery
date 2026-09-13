import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).parent
PROMPT_HOOK = SCRIPTS / "autonomy_prompt_hook.py"
STOP_HOOK = SCRIPTS / "autonomy_hook.py"


class AutonomyPromptHookTest(unittest.TestCase):
    def invoke(self, script, payload, environment):
        return subprocess.run(
            [sys.executable, str(script), "--host", "codex"], input=json.dumps(payload),
            text=True, capture_output=True, check=False, env=environment,
        )

    def test_review_then_continue_repair_blocks_early_final_without_a_third_user_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "CONVERGE_LEASE_ROOT": str(root / "leases"),
                "CONVERGE_CONTROLLER_ROOT": str(root / "controller"),
            }
            workspace = os.environ.get("CONVERGE_EVAL_WORKSPACE", str(SCRIPTS.parent))

            review = self.invoke(PROMPT_HOOK, {"cwd": workspace, "prompt": "review current changes"}, environment)
            continue_repair = self.invoke(PROMPT_HOOK, {"cwd": workspace, "prompt": "继续修复"}, environment)
            first_stop = self.invoke(STOP_HOOK, {
                "cwd": workspace, "stop_hook_active": False,
            }, environment)
            second_stop = self.invoke(STOP_HOOK, {
                "cwd": workspace, "stop_hook_active": True,
            }, environment)
            final_stop = self.invoke(STOP_HOOK, {
                "cwd": workspace, "stop_hook_active": True,
            }, environment)
            states = list((root / "state").rglob("*.json"))
            state = json.loads(states[0].read_text(encoding="utf-8"))

        self.assertEqual(0, review.returncode, review.stderr)
        self.assertEqual(0, continue_repair.returncode, continue_repair.stderr)
        self.assertEqual("block", json.loads(first_stop.stdout)["decision"])
        self.assertEqual("block", json.loads(second_stop.stdout)["decision"])
        self.assertEqual("blocked", state["status"])
        self.assertEqual("approve", json.loads(final_stop.stdout)["decision"])

    def test_subprocess_failure_blocks_instead_of_crashing(self):
        import autonomy_prompt_hook
        with tempfile.TemporaryDirectory():
            with patch.object(autonomy_prompt_hook, "active_state", return_value=None), \
                    patch.object(autonomy_prompt_hook, "run",
                                 side_effect=subprocess.SubprocessError("runner crashed")), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": "/tmp", "prompt": "continue repair"}))), \
                    patch.object(sys, "argv", ["autonomy_prompt_hook.py", "--host", "codex"]), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_prompt_hook.main())
        self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_arm_uses_the_requested_workspace_for_default_roots(self):
        import autonomy_prompt_hook
        workspace = "/repo/linked"
        with patch.object(autonomy_prompt_hook, "active_state", return_value=None), \
                patch.object(autonomy_prompt_hook, "state_root", return_value=Path("/state")) as state_root, \
                patch.object(autonomy_prompt_hook, "lease_root", return_value=Path("/leases")) as lease_root, \
                patch.object(autonomy_prompt_hook, "run", return_value={"status": "armed"}):
            autonomy_prompt_hook.arm(workspace)

        state_root.assert_called_once_with(workspace)
        lease_root.assert_called_once_with(workspace)

    def test_english_exact_command_arms_but_other_user_prompts_are_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "CONVERGE_LEASE_ROOT": str(root / "leases"),
                "CONVERGE_CONTROLLER_ROOT": str(root / "controller"),
            }
            workspace = os.environ.get("CONVERGE_EVAL_WORKSPACE", str(SCRIPTS.parent))

            ignored = self.invoke(PROMPT_HOOK, {"cwd": workspace, "prompt": "review current changes"}, environment)
            armed = self.invoke(PROMPT_HOOK, {"cwd": workspace, "prompt": "continue repair"}, environment)
            states = list((root / "state").rglob("*.json"))

        self.assertEqual({"continue": True}, json.loads(ignored.stdout))
        self.assertEqual(0, armed.returncode, armed.stderr)
        self.assertEqual(1, len(states))


if __name__ == "__main__":
    unittest.main()
