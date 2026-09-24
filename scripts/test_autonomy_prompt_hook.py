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

import autonomy_prompt_hook
from delivery_state import repository_state_root


SCRIPTS = Path(__file__).parent
PROMPT_HOOK = SCRIPTS / "autonomy_prompt_hook.py"
STOP_HOOK = SCRIPTS / "autonomy_hook.py"


class AutonomyPromptHookTest(unittest.TestCase):
    def test_repair_shortcut_matches_only_explicit_continuation_phrases(self):
        self.assertTrue(autonomy_prompt_hook.matches_continue_repair({"prompt": "继续修复已知问题"}))
        # General fix requests are authorized directly by the controller; the
        # shortcut must not freeze the whole repository as their scope.
        self.assertFalse(autonomy_prompt_hook.matches_continue_repair({"prompt": "请修复这个 bug"}))
        self.assertFalse(autonomy_prompt_hook.matches_continue_repair({"prompt": "还有其他问题没有？"}))
        self.assertFalse(autonomy_prompt_hook.matches_continue_repair({"prompt": "仅审查，不要修改"}))

    def test_same_conversation_recheck_offers_only_advisory_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "CONVERGE_LEASE_ROOT": str(root / "leases"),
                "CONVERGE_CONTROLLER_ROOT": str(root / "controller"),
            }
            first = self.invoke(PROMPT_HOOK, {
                "cwd": str(repo), "session_id": "thread-a", "prompt": "继续修复已知问题",
            }, environment)
            self.assertEqual(0, first.returncode, first.stderr)
            state_path = next((root / "state").rglob("*.json"))
            completed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual("thread-a", completed["execution_control"]["autonomy"]["runtime"]["session_id"])
            completed["status"] = "complete"
            state_path.write_text(json.dumps(completed), encoding="utf-8")

            with patch.dict(os.environ, environment), patch.object(autonomy_prompt_hook, "run", return_value={"status": "armed"}) as run:
                output = StringIO()
                with patch.object(sys, "argv", ["autonomy_prompt_hook.py", "--host", "codex"]), \
                        patch("sys.stdin", StringIO(json.dumps({
                            "cwd": str(repo), "session_id": "thread-a", "prompt": "还有其他问题没有？",
                        }))), redirect_stdout(output):
                    self.assertEqual(0, autonomy_prompt_hook.main())
                self.assertIn("hookSpecificOutput", json.loads(output.getvalue()))
                self.assertEqual("UserPromptSubmit", json.loads(output.getvalue())["hookSpecificOutput"]["hookEventName"])
                run.assert_not_called()
                context = json.loads(output.getvalue())["hookSpecificOutput"]["additionalContext"]
                self.assertIn("same work item", context)
                self.assertNotIn("finish the current review", context)
                self.assertNotIn("run a fresh full-scope", context)

            with patch.dict(os.environ, environment), patch.object(autonomy_prompt_hook, "run") as run:
                other = self.invoke(PROMPT_HOOK, {
                    "cwd": str(repo), "session_id": "thread-b", "prompt": "还有其他问题没有？",
                }, environment)
                run.assert_not_called()
                self.assertEqual({"continue": True}, json.loads(other.stdout))

    def test_recheck_does_not_select_an_old_completion_when_another_task_is_active(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            common = repo / ".git"
            storage = repository_state_root(root / "state", common)
            storage.mkdir(parents=True)
            base = {
                "schema_version": 11, "workspace": str(repo.resolve()),
                "execution_control": {
                    "routing": {"allowed_paths": ["src"]},
                    "autonomy": {
                        "runtime": {"mode": "hook", "session_id": "thread-a"},
                        "manifest": {"items": [
                            {"kind": "requirement", "value": "fix A"},
                            {"kind": "acceptance", "value": "A passes"},
                            {"kind": "scope", "value": "src"},
                        ]},
                    },
                },
            }
            (storage / "old.json").write_text(json.dumps({**base, "task_key": "task-" + "a" * 64, "status": "complete"}))
            (storage / "new.json").write_text(json.dumps({**base, "task_key": "task-" + "b" * 64, "status": "active"}))
            with patch.dict(os.environ, {"CONVERGE_STATE_ROOT": str(root / "state")}):
                self.assertIsNone(autonomy_prompt_hook.completed_contract(repo.resolve(), "thread-a"))

    def test_blocked_unchanged_run_cannot_reset_budget_with_repair_shortcut(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(repo), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            from evidence_contract import workspace_source
            baseline = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "HEAD"],
                text=True, capture_output=True, check=True,
            ).stdout.strip()
            source = workspace_source(repo, baseline)["source_fingerprint"]
            storage = repository_state_root(root / "state", repo / ".git")
            storage.mkdir(parents=True)
            (storage / "blocked.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(repo.resolve()),
                "task_key": "task-" + "a" * 64, "status": "blocked",
                "source_fingerprint": source, "baseline": {"commit": baseline},
                "execution_control": {"autonomy": {"runtime": {
                    "mode": "hook", "session_id": "thread-a",
                }}},
            }))
            with patch.dict(os.environ, {"CONVERGE_STATE_ROOT": str(root / "state")}), \
                    patch.object(autonomy_prompt_hook, "run") as run:
                with self.assertRaisesRegex(ValueError, "no progress"):
                    autonomy_prompt_hook.arm(repo, "thread-a")
            run.assert_not_called()

    def invoke(self, script, payload, environment):
        return subprocess.run(
            [sys.executable, str(script), "--host", "codex"],
            input=json.dumps({"session_id": "test-thread", **payload}),
            text=True, capture_output=True, check=False, env=environment,
        )

    def test_explicit_shortcut_without_host_session_id_does_not_arm(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory) / "repo"
            repo.mkdir()
            subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
            output = StringIO()
            with patch.object(autonomy_prompt_hook, "run", return_value={"status": "armed"}) as run, \
                    patch.object(sys, "argv", ["autonomy_prompt_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(repo), "prompt": "继续修复"}))), \
                    redirect_stdout(output):
                self.assertEqual(2, autonomy_prompt_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])
            run.assert_not_called()

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
                    patch.object(autonomy_prompt_hook, "git_root", return_value=SCRIPTS.parent), \
                    patch.object(autonomy_prompt_hook, "run",
                                 side_effect=subprocess.SubprocessError("runner crashed")), \
                    patch("sys.stdin", StringIO(json.dumps({
                        "cwd": "/tmp", "session_id": "test-thread", "prompt": "continue repair",
                    }))), \
                    patch.object(sys, "argv", ["autonomy_prompt_hook.py", "--host", "codex"]), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_prompt_hook.main())
        self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_arm_uses_git_root_and_leaves_path_risks_to_the_changed_source(self):
        import autonomy_prompt_hook
        workspace = "/repo/linked/scripts"
        root = "/repo/linked"
        with patch.object(autonomy_prompt_hook, "active_state", return_value=None), \
                patch.object(autonomy_prompt_hook, "state_root", return_value=Path("/state")) as state_root, \
                patch.object(autonomy_prompt_hook, "lease_root", return_value=Path("/leases")) as lease_root, \
                patch.object(autonomy_prompt_hook.subprocess, "run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=(root + "\n").encode(), stderr=b"",
                )), \
                patch.object(autonomy_prompt_hook, "run", return_value={"status": "armed"}) as run:
            autonomy_prompt_hook.arm(workspace)

        state_root.assert_called_once_with(Path(root))
        lease_root.assert_called_once_with(Path(root))
        self.assertEqual(root, run.call_args.args[0].workspace)
        self.assertEqual([], run.call_args.args[0].risk_flag)

    def test_arm_blocks_when_git_root_cannot_be_resolved(self):
        import autonomy_prompt_hook
        with patch.object(autonomy_prompt_hook, "active_state", return_value=None), \
                patch.object(autonomy_prompt_hook.subprocess, "run", return_value=subprocess.CompletedProcess(
                    args=[], returncode=1, stdout=b"", stderr=b"not a repository",
                )):
            with self.assertRaisesRegex(ValueError, "could not resolve Git workspace root"):
                autonomy_prompt_hook.arm("/repo/linked")

    def test_arm_rejects_git_environment_for_another_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            workspace = root / "workspace"
            selected.mkdir()
            workspace.mkdir()
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(selected)}
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(autonomy_prompt_hook, "run") as run:
                with self.assertRaisesRegex(ValueError, "does not contain the requested workspace"):
                    autonomy_prompt_hook.arm(str(workspace))
            run.assert_not_called()

    def test_arm_rejects_outer_git_environment_for_nested_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(outer)}
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(autonomy_prompt_hook, "run") as run:
                with self.assertRaisesRegex(ValueError, "nested Git workspace"):
                    autonomy_prompt_hook.arm(str(inner))
            run.assert_not_called()

    def test_arm_rejects_foreign_git_dir_at_explicit_worktree_root(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(inner)}
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(autonomy_prompt_hook, "run") as run:
                with self.assertRaisesRegex(ValueError, "nested Git workspace"):
                    autonomy_prompt_hook.arm(str(inner))
            run.assert_not_called()

    def test_existing_subdirectory_run_is_not_duplicated_at_the_root(self):
        import autonomy_prompt_hook
        with patch.object(autonomy_prompt_hook, "active_state", return_value=(Path("/state/run.json"), {})), \
                patch.object(autonomy_prompt_hook, "run") as run:
            self.assertIsNone(autonomy_prompt_hook.arm("/repo/linked/scripts"))
        run.assert_not_called()

    def test_repair_shortcut_cannot_claim_another_conversations_active_run(self):
        state = {"execution_control": {"autonomy": {"runtime": {
            "mode": "hook", "session_id": "thread-a",
        }}}}
        with patch.object(autonomy_prompt_hook, "active_state", return_value=(Path("/state/run.json"), state)), \
                patch.object(autonomy_prompt_hook, "run") as run:
            with self.assertRaisesRegex(ValueError, "another conversation owns"):
                autonomy_prompt_hook.arm("/repo/linked", "thread-b")
        run.assert_not_called()

    def test_root_prompt_reuses_a_pre_upgrade_subdirectory_run(self):
        import autonomy_prompt_hook
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "repo"
            subdirectory = workspace / "src"
            subdirectory.mkdir(parents=True)
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            state_root = base / "state"
            state_file = repository_state_root(state_root, workspace) / "old" / "run.json"
            state_file.parent.mkdir(parents=True)
            state_file.write_text(json.dumps({
                "schema_version": 11, "workspace": str(subdirectory.resolve()),
                "status": "active", "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"CONVERGE_STATE_ROOT": str(state_root)}), \
                    patch.object(autonomy_prompt_hook, "run") as run:
                self.assertIsNone(autonomy_prompt_hook.arm(str(workspace)))
            run.assert_not_called()

    def test_non_git_prompt_does_not_block_an_unrelated_host_task(self):
        with tempfile.TemporaryDirectory() as directory:
            environment = os.environ | {"CONVERGE_STATE_ROOT": str(Path(directory) / "state")}
            result = self.invoke(PROMPT_HOOK, {"cwd": directory, "prompt": "continue repair"}, environment)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual({"continue": True}, json.loads(result.stdout))

    def test_git_query_failure_does_not_silently_skip_the_repair_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            output = StringIO()
            with patch("autonomy_prompt_hook.git_root", return_value=None), \
                    patch("autonomy_prompt_hook.run") as run, \
                    patch.object(sys, "argv", ["autonomy_prompt_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace), "prompt": "继续修复"}))), \
                    redirect_stdout(output):
                self.assertEqual(2, autonomy_prompt_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])
            run.assert_not_called()

    def test_dangling_git_symlink_blocks_explicit_repair_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            (workspace / ".git").symlink_to(Path(directory) / "missing-admin")
            environment = os.environ | {"CONVERGE_STATE_ROOT": str(Path(directory) / "state")}
            result = self.invoke(PROMPT_HOOK, {"cwd": str(workspace), "prompt": "继续修复"}, environment)
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_trailing_space_in_git_root_still_arms_repair_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo "
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "CONVERGE_LEASE_ROOT": str(root / "leases"),
                "CONVERGE_CONTROLLER_ROOT": str(root / "controller"),
            }
            result = self.invoke(PROMPT_HOOK, {"cwd": str(workspace), "prompt": "继续修复"}, environment)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual("UserPromptSubmit", json.loads(result.stdout)["hookSpecificOutput"]["hookEventName"])

    def test_trailing_space_in_separate_git_dir_arms_in_real_common_dir(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo"
            admin = root / "admin "
            subprocess.run(["git", "init", "-q", "--separate-git-dir", str(admin), str(workspace)], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"CONVERGE_CONTROLLER_ROOT": str(root / "controller")}
            result = self.invoke(PROMPT_HOOK, {"cwd": str(workspace), "prompt": "继续修复"}, environment)
            states = list((admin / "convergent-delivery" / "state").rglob("*.json"))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(1, len(states))

    def test_subdirectory_prompt_uses_repo_root_without_unchanged_security_risk(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / "src").mkdir(parents=True)
            (repo / "SECURITY.md").write_text("security policy\n", encoding="utf-8")
            source = repo / "src" / "main.py"
            source.write_text("value = 1\n", encoding="utf-8")
            for argv in (["init", "-q"], ["add", "."],
                         ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base"]):
                subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True)
            source.write_text("value = 2\n", encoding="utf-8")
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
                "CONVERGE_LEASE_ROOT": str(root / "leases"),
                "CONVERGE_CONTROLLER_ROOT": str(root / "controller"),
            }

            result = self.invoke(PROMPT_HOOK, {"cwd": str(repo / "src"), "prompt": "continue repair"}, environment)
            stop = self.invoke(STOP_HOOK, {"cwd": str(repo / "src"), "stop_hook_active": False}, environment)
            states = list((root / "state").rglob("*.json"))
            state = json.loads(states[0].read_text(encoding="utf-8")) if states else None

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("block", json.loads(stop.stdout)["decision"])
        self.assertEqual(str(repo.resolve()), state["workspace"])
        self.assertEqual(["src/main.py"], state["source_receipt"]["changed_paths"])
        self.assertEqual([], state["execution_control"]["routing"]["profile"]["risk_flags"])
        self.assertEqual("normal", state["execution_control"]["routing"]["review_tier"])

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
            state = json.loads(states[0].read_text(encoding="utf-8"))

        self.assertEqual({"continue": True}, json.loads(ignored.stdout))
        self.assertEqual(0, armed.returncode, armed.stderr)
        self.assertEqual(1, len(states))
        routing = state["execution_control"]["routing"]
        self.assertEqual("high", routing["profile"]["uncertainty"])
        self.assertEqual("planned", routing["route"])
        from task_profile import infer_path_risks
        self.assertEqual(
            sorted(infer_path_risks(state["source_receipt"]["changed_paths"])),
            routing["profile"]["risk_flags"],
        )
        self.assertEqual("high" if routing["profile"]["risk_flags"] else "normal", routing["review_tier"])


if __name__ == "__main__":
    unittest.main()
