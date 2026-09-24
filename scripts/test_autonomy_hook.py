import json
import os
import subprocess
import sys
import tempfile
import unittest
import hashlib
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import autonomy_hook
from autonomy_arm import arm
from autonomy_begin import initial_state
from controller_snapshot import create_snapshot
from delivery_lease import lease_paths
from delivery_engine import controller_identity
from delivery_state import state_path

SCRIPT = Path(__file__).with_name("autonomy_hook.py")


class AutonomyHookTest(unittest.TestCase):

    def test_default_roots_belong_to_the_active_project(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "project"
            workspace.mkdir()

            self.assertEqual(
                (workspace / ".convergent-delivery" / "state").resolve(),
                autonomy_hook.state_root(workspace),
            )
            self.assertEqual(
                (workspace / ".convergent-delivery" / "leases").resolve(),
                autonomy_hook.lease_root(workspace),
            )
    @staticmethod
    def workspace_state_dir(root, workspace):
        return Path(root) / hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()

    def invoke(self, host, payload, environment=None):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--host", host], input=json.dumps(payload),
            text=True, capture_output=True, check=False, env=environment,
        )

    def managed_hook_state(self, directory, controller=None):
        workspace = Path(os.environ.get("CONVERGE_EVAL_WORKSPACE", SCRIPT.parent.parent)).resolve()
        state_root, lease_root = Path(directory) / "state", Path(directory) / "leases"
        initial = initial_state(
            workspace, ["complete task"], ["tests pass"], ["."], "run-hook", "writer-hook",
            mode="native", controller=controller,
        )
        common = subprocess.run(["git", "-C", str(workspace), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                text=True, capture_output=True, check=True).stdout.strip()
        self.assertEqual(common, initial["repo_id"])
        acquired = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_lease.py")), "acquire",
            "--root", str(lease_root), "--repo", initial["repo_id"], "--workspace", initial["workspace"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
        ], text=True, capture_output=True, check=False)
        self.assertEqual(0, acquired.returncode, acquired.stderr)
        created = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "-1",
        ], input=json.dumps(initial), text=True, capture_output=True, check=False)
        self.assertEqual(0, created.returncode, created.stderr)
        armed = arm(initial, ["complete task"], ["tests pass"], "hook")
        armed_write = subprocess.run([
            sys.executable, str(SCRIPT.with_name("delivery_state.py")), "write", "--input", "-",
            "--lease-root", str(lease_root), "--state-root", str(state_root), "--repo-id", initial["repo_id"],
            "--task-key", initial["task_key"], "--run-id", initial["run_id"], "--writer-id", initial["writer_id"],
            "--expected-revision", "0",
        ], input=json.dumps(armed), text=True, capture_output=True, check=False)
        self.assertEqual(0, armed_write.returncode, armed_write.stderr)
        return state_path(state_root, initial["repo_id"], initial["task_key"], initial["run_id"]), state_root, lease_root

    def test_new_snapshot_run_dispatches_the_hook_to_its_frozen_controller(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = create_snapshot(
                SCRIPT.parent.parent, root / "controller", extensions=("autonomy",)
            )
            path, state_root, lease_root = self.managed_hook_state(
                directory, controller=controller_identity(snapshot=snapshot),
            )
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            completed = subprocess.CompletedProcess([], 0, '{"decision":"approve"}\n', "")
            real_run = subprocess.run
            def execute(command, **kwargs):
                return completed if "controller_snapshot.py" in str(command[1]) else real_run(command, **kwargs)
            with patch.object(autonomy_hook.subprocess, "run", side_effect=execute) as run, \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": workspace, "session_id": "thread-1"}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(0, autonomy_hook.main())

            self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))
            command = run.call_args.args[0]
            self.assertEqual(sys.executable, command[0])
            self.assertTrue(command[1].endswith("controller_snapshot.py"))
            self.assertIn(str(path), command)
            self.assertIn("--frozen-runtime", command)

    def test_frozen_hook_receives_the_active_run_workspace_from_a_subdirectory(self):
        workspace = SCRIPT.parent.parent.resolve()
        subdirectory = workspace / "scripts"
        state = {"controller": {"snapshot": {"root": "/frozen"}}, "workspace": str(workspace)}
        active = (Path("/state/run.json"), state)
        frozen_result = subprocess.CompletedProcess([], 0, '{"decision":"block","reason":"active"}\n', "")
        with patch.object(autonomy_hook, "active_state", side_effect=[None, active]), \
                patch.object(autonomy_hook, "may_have_managed_state", return_value=True), \
                patch.object(autonomy_hook, "git_root", return_value=workspace), \
                patch.object(autonomy_hook, "run_frozen_hook", return_value=frozen_result) as frozen, \
                patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                patch("sys.stdin", StringIO(json.dumps({"cwd": str(subdirectory)}))), \
                redirect_stdout(StringIO()) as output:
            self.assertEqual(0, autonomy_hook.main())

        self.assertEqual("block", json.loads(output.getvalue())["decision"])
        self.assertEqual(str(workspace), frozen.call_args.args[2]["cwd"])

    def test_terminal_history_does_not_trigger_per_state_git_lookups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            states = self.workspace_state_dir(root, "/repo")
            states.mkdir()
            (states / "history.json").write_text(json.dumps({
                "workspace": "/repo/old", "schema_version": 11, "status": "complete",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            with patch.dict(os.environ, {"CONVERGE_STATE_ROOT": str(root)}), \
                    patch.object(autonomy_hook, "state_root", return_value=root), \
                    patch.object(autonomy_hook, "workspace_state_roots", return_value=(states,)), \
                    patch.object(autonomy_hook, "git_root", return_value=Path("/repo")) as git_root:
                self.assertIsNone(autonomy_hook.active_state("/repo"))
            git_root.assert_not_called()

    def test_git_root_lookup_has_a_bounded_runtime(self):
        completed = subprocess.CompletedProcess([], 1, b"", b"not a git repository")
        with patch.object(autonomy_hook.subprocess, "run", return_value=completed) as run:
            self.assertIsNone(autonomy_hook.git_root("/repo"))
        self.assertEqual(5, run.call_args.kwargs["timeout"])

    def test_git_timeout_does_not_block_an_unmanaged_non_git_task(self):
        for empty_state_dir in (False, True):
            with self.subTest(empty_state_dir=empty_state_dir), tempfile.TemporaryDirectory() as directory:
                if empty_state_dir:
                    (Path(directory) / ".convergent-delivery" / "state").mkdir(parents=True)
                with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                        patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                        patch("sys.stdin", StringIO(json.dumps({"cwd": directory}))), \
                        redirect_stdout(StringIO()) as output:
                    self.assertEqual(0, autonomy_hook.main())
                self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_git_timeout_does_not_block_a_git_worktree_without_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            linked = Path(directory) / "linked"
            subprocess.run(["git", "-C", str(workspace), "worktree", "add", "-q", "-b", "linked", str(linked)], check=True)
            for target in (workspace, linked):
                with self.subTest(target=target), \
                        patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                        patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                        patch("sys.stdin", StringIO(json.dumps({"cwd": str(target)}))), \
                        redirect_stdout(StringIO()) as output:
                    self.assertEqual(0, autonomy_hook.main())
                self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_git_timeout_still_blocks_a_worktree_with_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            state_dir = workspace / ".git" / "convergent-delivery" / "state" \
                / hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_git_error_still_blocks_a_worktree_with_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            state_dir = workspace / ".git" / "convergent-delivery" / "state" \
                / hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            failed = subprocess.CompletedProcess([], 1, b"", b"git failed")
            with patch.object(autonomy_hook.subprocess, "run", return_value=failed), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_git_timeout_still_blocks_a_linked_worktree_with_managed_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            linked = Path(directory) / "linked"
            subprocess.run(["git", "-C", str(workspace), "worktree", "add", "-q", "-b", "linked", str(linked)], check=True)
            common = workspace / ".git"
            state_dir = common / "convergent-delivery" / "state" \
                / hashlib.sha256(str(common.resolve()).encode()).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(linked.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(linked)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_git_timeout_does_not_trust_an_invalid_git_pointer(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            (workspace / ".git").write_text("gitdir: .\n", encoding="utf-8")
            with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(2, autonomy_hook.main())
            self.assertEqual("block", json.loads(output.getvalue())["decision"])

    def test_dangling_git_symlink_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            (workspace / ".git").symlink_to(Path(directory) / "missing-admin")
            result = self.invoke("codex", {"cwd": str(workspace)})
        self.assertEqual(2, result.returncode, result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_trailing_space_in_git_root_does_not_hide_active_run_from_subdirectory(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo "
            subdirectory = workspace / "src"
            subdirectory.mkdir(parents=True)
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            state_dir = self.workspace_state_dir(
                workspace / ".git" / "convergent-delivery" / "state", workspace,
            )
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            self.assertEqual(workspace.resolve(), autonomy_hook.git_root(subdirectory))
            result = self.invoke("codex", {"cwd": str(subdirectory)})
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_trailing_space_in_separate_git_dir_does_not_hide_active_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo"
            admin = root / "admin "
            subprocess.run(["git", "init", "-q", "--separate-git-dir", str(admin), str(workspace)], check=True)
            state_dir = self.workspace_state_dir(admin / "convergent-delivery" / "state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            result = self.invoke("codex", {"cwd": str(workspace)})
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_environment_without_marker_finds_active_common_dir_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo"
            workspace.mkdir()
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            state_dir = self.workspace_state_dir(admin / "convergent-delivery" / "state", admin)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(workspace)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_environment_overrides_ancestor_repository_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outer = root / "outer"
            outer.mkdir()
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            workspace = outer / "inner"
            workspace.mkdir()
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            state_dir = self.workspace_state_dir(admin / "convergent-delivery" / "state", admin)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(workspace)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_outer_git_environment_does_not_hide_nested_repository_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            state_dir = self.workspace_state_dir(inner / ".git" / "convergent-delivery" / "state", inner)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(inner.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(outer)}
            result = self.invoke("codex", {"cwd": str(inner)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_outer_git_environment_without_nested_repository_state_approves(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            for selected in (outer, inner):
                with self.subTest(selected=selected):
                    environment = {
                        key: value for key, value in os.environ.items()
                        if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
                    } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(selected)}
                    result = self.invoke("codex", {"cwd": str(inner)}, environment)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual({"decision": "approve"}, json.loads(result.stdout))

    def test_foreign_git_dir_cannot_hide_state_at_explicit_worktree_root(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            state_dir = self.workspace_state_dir(inner / ".git" / "convergent-delivery" / "state", inner)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(inner.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(inner)}
            result = self.invoke("codex", {"cwd": str(inner)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_outer_active_state_does_not_block_unmanaged_nested_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            outer = Path(directory) / "outer"
            inner = outer / "inner"
            inner.mkdir(parents=True)
            subprocess.run(["git", "init", "-q", str(outer)], check=True)
            subprocess.run(["git", "init", "-q", str(inner)], check=True)
            state_dir = self.workspace_state_dir(outer / ".git" / "convergent-delivery" / "state", outer)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(outer.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            for selected in (outer, inner):
                with self.subTest(selected=selected):
                    environment = {
                        key: value for key, value in os.environ.items()
                        if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
                    } | {"GIT_DIR": str(outer / ".git"), "GIT_WORK_TREE": str(selected)}
                    result = self.invoke("codex", {"cwd": str(inner)}, environment)
                    self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                    self.assertEqual({"decision": "approve"}, json.loads(result.stdout))

    def test_matching_git_environment_with_worktree_marker_keeps_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            state_dir = self.workspace_state_dir(workspace / ".git" / "convergent-delivery" / "state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(workspace / ".git"), "GIT_WORK_TREE": str(workspace)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_environment_without_managed_state_approves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "repo"
            workspace.mkdir()
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(workspace)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"decision": "approve"}, json.loads(result.stdout))

    def test_git_environment_for_another_worktree_does_not_hide_local_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            workspace = root / "workspace"
            selected.mkdir()
            workspace.mkdir()
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery" / "state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(selected)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_environment_for_another_worktree_does_not_hide_git_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            selected = root / "selected"
            workspace = root / "workspace"
            selected.mkdir()
            workspace.mkdir()
            subprocess.run(["git", "init", "-q", str(workspace)], check=True)
            admin = root / "admin.git"
            subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
            state_dir = self.workspace_state_dir(workspace / ".git" / "convergent-delivery" / "state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            environment = {
                key: value for key, value in os.environ.items()
                if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
            } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(selected)}
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_environment_for_another_worktree_with_no_state_approves(self):
        for git_workspace in (False, True):
            with self.subTest(git_workspace=git_workspace), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                selected = root / "selected"
                workspace = root / "workspace"
                selected.mkdir()
                workspace.mkdir()
                if git_workspace:
                    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
                admin = root / "admin.git"
                subprocess.run(["git", "init", "--bare", "-q", str(admin)], check=True)
                environment = {
                    key: value for key, value in os.environ.items()
                    if key not in {"CONVERGE_STATE_ROOT", "CONVERGE_LEASE_ROOT"}
                } | {"GIT_DIR": str(admin), "GIT_WORK_TREE": str(selected)}
                result = self.invoke("codex", {"cwd": str(workspace)}, environment)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual({"decision": "approve"}, json.loads(result.stdout))

    def test_invalid_git_environment_without_marker_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            environment = os.environ | {
                "GIT_DIR": str(Path(directory) / "missing-admin"), "GIT_WORK_TREE": str(workspace),
            }
            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
        self.assertEqual(2, result.returncode, result.stdout + result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_git_timeout_ignores_only_terminal_managed_history(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            state_dir = workspace / ".git" / "convergent-delivery" / "state" \
                / hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "complete",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(0, autonomy_hook.main())
            self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_no_active_autonomous_run_approves_for_both_hosts(self):
        with tempfile.TemporaryDirectory() as directory:
            for host in ("codex", "claude"):
                result = self.invoke(host, {"cwd": directory})
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_active_run_is_blocked_with_the_gate_next_action(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode)
            decision = json.loads(result.stdout)
            self.assertEqual("block", decision["decision"])
            self.assertIn("autonomous run", decision["reason"])

    def test_malformed_active_state_returns_a_structured_block(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace), "status": "active",
                "execution_control": None,
            }), encoding="utf-8")
            result = self.invoke("codex", {"cwd": str(workspace)})
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])
            self.assertEqual("", result.stderr)

    def test_active_state_without_workspace_returns_a_structured_block(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            result = self.invoke("codex", {"cwd": str(workspace)})
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])
            self.assertEqual("", result.stderr)

    def test_active_state_with_unsupported_schema_is_not_approved(self):
        for schema in (12, [], {}, True):
            with self.subTest(schema=schema), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                workspace.mkdir()
                state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace)
                state_dir.mkdir(parents=True)
                (state_dir / "run.json").write_text(json.dumps({
                    "schema_version": schema, "workspace": str(workspace), "status": "active",
                    "execution_control": {"autonomy": {"enabled": True}},
                }), encoding="utf-8")
                result = self.invoke("codex", {"cwd": str(workspace)})
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("block", json.loads(result.stdout)["decision"])
                self.assertIn("unsupported", json.loads(result.stdout)["reason"])

    def test_active_state_in_this_workspace_directory_cannot_claim_another_workspace(self):
        for is_git in (False, True):
            with self.subTest(is_git=is_git), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory) / "workspace"
                workspace.mkdir()
                if is_git:
                    subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
                base = (workspace / ".git" / "convergent-delivery" / "state" if is_git
                        else workspace / ".convergent-delivery" / "state")
                state_dir = self.workspace_state_dir(base, workspace)
                state_dir.mkdir(parents=True)
                (state_dir / "run.json").write_text(json.dumps({
                    "schema_version": 11, "workspace": str(Path(directory) / "other"),
                    "status": "active", "execution_control": {"autonomy": {"enabled": True}},
                }), encoding="utf-8")
                result = self.invoke("codex", {"cwd": str(workspace)})
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertIn("workspace", json.loads(result.stdout)["reason"])

    def test_active_legacy_schema_run_is_not_silently_approved(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(workspace / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 10, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            (state_dir / "run.json").write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False,
            )
            self.assertEqual(2, result.returncode, result.stdout)
            decision = json.loads(result.stdout)
            self.assertEqual("block", decision["decision"])

    def test_invalid_hook_payload_fails_open(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--host", "codex"], input="not-json",
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(0, result.returncode)
        self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_payload_without_a_workspace_fails_open(self):
        for payload in ({}, {"cwd": ""}, {"cwd": 3}):
            with self.subTest(payload=payload):
                result = self.invoke("codex", payload)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_multiple_active_runs_block_instead_of_failing_open(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            workspace = Path(directory) / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(home / ".convergent-delivery/state", workspace) / "a"
            state_dir.mkdir(parents=True)
            state = {
                "schema_version": 11, "workspace": str(workspace.resolve()), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }
            for name in ("first.json", "second.json"):
                (state_dir / name).write_text(json.dumps(state), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex"],
                input=json.dumps({"cwd": str(workspace)}), text=True, capture_output=True,
                check=False, env=os.environ | {
                    "HOME": str(home),
                    "CONVERGE_STATE_ROOT": str(home / ".convergent-delivery/state"),
                    "CONVERGE_LEASE_ROOT": str(home / ".convergent-delivery/leases"),
                },
            )
        self.assertEqual(2, result.returncode)
        self.assertIn("multiple autonomous runs", json.loads(result.stdout)["reason"])

    def test_non_object_managed_state_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("[1, 2]", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("is not an object", json.loads(result.stdout)["reason"])

    def test_unreadable_managed_state_blocks_instead_of_approving(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("{", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("unreadable managed state", json.loads(result.stdout)["reason"])

    def test_unreadable_state_from_another_workspace_does_not_block_this_hook(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "workspace"
            other_workspace = root / "other-workspace"
            workspace.mkdir()
            other_workspace.mkdir()
            state_dir = self.workspace_state_dir(root / "state", other_workspace) / "a"
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text("{", encoding="utf-8")

            result = self.invoke("codex", {"cwd": str(workspace)}, os.environ | {
                "CONVERGE_STATE_ROOT": str(root / "state"),
            })

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("approve", json.loads(result.stdout)["decision"])

    def test_malformed_active_state_from_a_sibling_worktree_does_not_block(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            sibling = Path(directory) / "linked"
            subprocess.run(["git", "-C", str(workspace), "worktree", "add", "-q", "-b", "linked", str(sibling)], check=True)
            common = workspace / ".git"
            state_dir = common / "convergent-delivery" / "state" \
                / hashlib.sha256(str(common.resolve()).encode()).hexdigest()
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(sibling), "status": "active",
                "execution_control": None,
            }), encoding="utf-8")
            with patch.object(autonomy_hook.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 5)), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace)}))), \
                    redirect_stdout(StringIO()) as output:
                self.assertEqual(0, autonomy_hook.main())
            self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_shared_active_state_with_an_unverified_other_owner_blocks(self):
        for owner_kind in ("missing", "different-repo"):
            with self.subTest(owner_kind=owner_kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                workspace = base / "repo"
                workspace.mkdir()
                subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
                owner = base / "other"
                if owner_kind == "different-repo":
                    owner.mkdir()
                    subprocess.run(["git", "-C", str(owner), "init", "-q"], check=True)
                common = workspace / ".git"
                state_dir = self.workspace_state_dir(common / "convergent-delivery" / "state", common)
                state_dir.mkdir(parents=True)
                (state_dir / "run.json").write_text(json.dumps({
                    "schema_version": 11, "workspace": str(owner), "status": "active",
                    "execution_control": {"autonomy": {"enabled": True}},
                }), encoding="utf-8")
                result = self.invoke("codex", {"cwd": str(workspace)})
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("block", json.loads(result.stdout)["decision"])
                self.assertIn("workspace", json.loads(result.stdout)["reason"])

    def test_forged_linked_worktree_pointer_cannot_hide_shared_active_state(self):
        for marker_kind in ("copy", "symlink"):
            with self.subTest(marker_kind=marker_kind), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                workspace = base / "repo"
                workspace.mkdir()
                subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
                subprocess.run([
                    "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                    "commit", "--allow-empty", "-qm", "base",
                ], check=True)
                sibling = base / "linked"
                subprocess.run(["git", "-C", str(workspace), "worktree", "add", "-q", "-b", "linked", str(sibling)], check=True)
                forged = base / "forged"
                forged.mkdir()
                marker = forged / ".git"
                if marker_kind == "copy":
                    marker.write_text((sibling / ".git").read_text(encoding="utf-8"), encoding="utf-8")
                else:
                    marker.symlink_to(sibling / ".git")
                common = workspace / ".git"
                state_dir = self.workspace_state_dir(common / "convergent-delivery" / "state", common)
                state_dir.mkdir(parents=True)
                (state_dir / "run.json").write_text(json.dumps({
                    "schema_version": 11, "workspace": str(forged), "status": "active",
                    "execution_control": None,
                }), encoding="utf-8")
                result = self.invoke("codex", {"cwd": str(workspace)})
                self.assertEqual(2, result.returncode, result.stderr)
                self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_unregistered_worktree_admin_cannot_hide_shared_active_state(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "repo"
            workspace.mkdir()
            subprocess.run(["git", "-C", str(workspace), "init", "-q"], check=True)
            common = (workspace / ".git").resolve()
            forged = base / "forged"
            forged.mkdir()
            admin = base / "unregistered-admin"
            admin.mkdir()
            (forged / ".git").write_text(f"gitdir: {admin.resolve()}\n", encoding="utf-8")
            (admin / "commondir").write_text(str(common), encoding="utf-8")
            (admin / "gitdir").write_text(str((forged / ".git").resolve()), encoding="utf-8")
            state_dir = self.workspace_state_dir(common / "convergent-delivery" / "state", common)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(forged), "status": "active",
                "execution_control": None,
            }), encoding="utf-8")
            result = self.invoke("codex", {"cwd": str(workspace)})
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_separate_git_dir_without_owner_backlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            workspace = base / "repo"
            common = base / "common.git"
            subprocess.run(["git", "init", "-q", "--separate-git-dir", str(common), str(workspace)], check=True)
            subprocess.run([
                "git", "-C", str(workspace), "-c", "user.name=Test", "-c", "user.email=test@example.com",
                "commit", "--allow-empty", "-qm", "base",
            ], check=True)
            sibling = base / "linked"
            subprocess.run(["git", "-C", str(workspace), "worktree", "add", "-q", "-b", "linked", str(sibling)], check=True)
            state_dir = self.workspace_state_dir(common / "convergent-delivery" / "state", common)
            state_dir.mkdir(parents=True)
            (state_dir / "run.json").write_text(json.dumps({
                "schema_version": 11, "workspace": str(workspace), "status": "active",
                "execution_control": {"autonomy": {"enabled": True}},
            }), encoding="utf-8")
            result = self.invoke("codex", {"cwd": str(sibling)})
            self.assertEqual(2, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_codex_stop_blocks_in_the_same_task_and_records_one_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            result = self.invoke("codex", {
                "cwd": str(workspace), "stop_hook_active": False,
            }, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            })

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("block", json.loads(result.stdout)["decision"])
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("active", current["status"])
            attempts = current["execution_control"]["autonomy"]["action_attempts"]
            self.assertEqual(1, len(attempts))
            self.assertEqual("intent", attempts[0]["status"])

    def test_codex_second_native_stop_terminalizes_no_progress_then_allows_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            }
            first = self.invoke("codex", {"cwd": str(workspace)}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            third = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("block", json.loads(first.stdout)["decision"])
        self.assertEqual("block", json.loads(second.stdout)["decision"])
        self.assertEqual("blocked", current["status"])
        self.assertEqual("approve", json.loads(third.stdout)["decision"])

    def test_codex_stop_after_terminalization_does_not_create_another_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = json.loads(path.read_text(encoding="utf-8"))["workspace"]
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            }

            first = self.invoke("codex", {"cwd": str(workspace)}, environment)
            second = self.invoke("codex", {"cwd": str(workspace), "stop_hook_active": True}, environment)
            state = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, first.returncode, first.stderr)
        self.assertEqual(0, second.returncode, second.stderr)
        self.assertEqual("blocked", state["status"])

    def test_codex_audit_repair_stop_blocks_with_the_frozen_next_action(self):
        from delivery_next import upgrade_state
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = upgrade_state(json.loads(path.read_text(encoding="utf-8")))
            workspace = Path(state["workspace"])
            state["current_stage"] = "autonomy-repair"
            state["execution_control"]["autonomy"]["audit_batches"] = [{
                "source_fingerprint": state["source_fingerprint"], "phase": "initial", "status": "findings",
                "covered_manifest_ids": [
                    item["id"] for item in state["execution_control"]["autonomy"]["manifest"]["items"]
                ],
                "finding_fingerprints": ["a" * 64],
                "evidence_receipt_fingerprint": "a" * 64,
            }]
            path.write_text(json.dumps(state), encoding="utf-8")
            environment = os.environ | {"CONVERGE_STATE_ROOT": str(state_root),
                                        "CONVERGE_LEASE_ROOT": str(lease_root)}

            result = self.invoke("codex", {"cwd": str(workspace)}, environment)
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("block", json.loads(result.stdout)["decision"])
        self.assertEqual("active", current["status"])

    def test_service_hook_approves_without_a_launchagent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {
                "workspace": str(root),
                "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
            }
            output = StringIO()

            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide", return_value={"decision": "block", "next_action": {}}), \
                    patch.object(autonomy_hook.subprocess, "run") as run, \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch.object(sys, "stdin", StringIO(json.dumps({"cwd": str(root)}))), redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))
        self.assertNotIn("launchctl", [call.args[0][0] for call in run.call_args_list])

    def test_service_hook_validates_the_active_workspace_lease(self):
        workspace = "/repo/linked"
        state = {
            "workspace": workspace,
            "execution_control": {"autonomy": {"runtime": {"mode": "service"}}},
        }
        with patch.object(autonomy_hook, "lease_root", return_value=Path("/leases")) as lease_root, \
                patch.object(autonomy_hook, "decide", return_value={"decision": "block", "next_action": {}}):
            decision, status = autonomy_hook.run_hook("codex", {}, (Path("/state.json"), state))

        self.assertEqual({"decision": "approve"}, decision)
        self.assertEqual(0, status)
        lease_root.assert_called_once_with(workspace)

    def test_codex_does_not_require_a_session_identifier_for_native_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))

            result = self.invoke("codex", {"cwd": state["workspace"]}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })

        self.assertEqual(0, result.returncode)
        self.assertEqual("block", json.loads(result.stdout)["decision"])

    def test_session_bound_run_does_not_continue_in_another_conversation(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            state["execution_control"]["autonomy"]["runtime"]["session_id"] = "thread-a"
            path.write_text(json.dumps(state), encoding="utf-8")
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root),
                "CONVERGE_LEASE_ROOT": str(lease_root),
            }

            other = self.invoke("codex", {
                "cwd": state["workspace"], "session_id": "thread-b",
            }, environment)
            missing = self.invoke("codex", {"cwd": state["workspace"]}, environment)
            same = self.invoke("codex", {
                "cwd": state["workspace"], "session_id": "thread-a",
            }, environment)

            self.assertEqual({"decision": "approve"}, json.loads(other.stdout))
            self.assertEqual("block", json.loads(missing.stdout)["decision"])
            self.assertEqual("block", json.loads(same.stdout)["decision"])
            current = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(1, len(current["execution_control"]["autonomy"]["action_attempts"]))

    def test_claude_active_run_never_blocks_stop_for_a_successor_task(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            workspace = Path(json.loads(path.read_text(encoding="utf-8"))["workspace"])
            result = self.invoke("claude", {"cwd": str(workspace), "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            })
            current = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(0, result.returncode, result.stderr + result.stdout)
        decision = json.loads(result.stdout)
        self.assertEqual("approve", decision["decision"])
        self.assertEqual("blocked", current["status"])

    def test_claude_stop_terminalizes_and_releases_the_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text())
            environment = os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
            }
            payload = {"cwd": state["workspace"], "stop_hook_active": True}
            first = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(first.stdout)["decision"])
            second = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(second.stdout)["decision"])
            self.assertEqual("blocked", json.loads(path.read_text())["status"])
            self.assertFalse(any(p.exists() for p in lease_paths(
                lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values()))
            third = self.invoke("claude", payload, environment)
            self.assertEqual("approve", json.loads(third.stdout)["decision"])

    def test_expired_lease_blocks_the_hook_before_queueing_a_continuation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            for lease in lease_paths(
                    lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values():
                record = json.loads(lease.read_text(encoding="utf-8"))
                record["lease_expires_at"] = "2000-01-01T00:00:00Z"
                lease.write_text(json.dumps(record), encoding="utf-8")
            capture = root / "commands"
            result = self.invoke("codex", {"cwd": state["workspace"], "session_id": "thread-123"}, os.environ | {
                "CONVERGE_STATE_ROOT": str(state_root), "CONVERGE_LEASE_ROOT": str(lease_root),
                "AUTONOMY_CAPTURE": str(capture),
            })

        self.assertEqual(2, result.returncode)
        self.assertIn("active lease", json.loads(result.stdout)["reason"])
        self.assertFalse(capture.exists())


    def run_managed_hook_in_process(self, host, payload, state_path, state_root, lease_root, execute):
        workspace = json.loads(state_path.read_text(encoding="utf-8"))["workspace"]
        output = StringIO()
        with patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                patch.object(sys, "argv", ["autonomy_hook.py", "--host", host]), \
                patch("sys.stdin", StringIO(json.dumps({"cwd": str(workspace), **payload}))), \
                patch.dict(os.environ, {
                    "CONVERGE_STATE_ROOT": str(state_root),
                    "CONVERGE_LEASE_ROOT": str(lease_root),
                }), \
                redirect_stdout(output):
            result = autonomy_hook.main()
        return result, output.getvalue()

    def test_gate_allow_short_circuits_to_an_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"workspace": str(root), "execution_control": {"autonomy": {"enabled": True}}}
            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide", return_value={"decision": "allow"}), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_service_mode_without_a_launchagent_approves(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {
                "workspace": str(root),
                "execution_control": {"autonomy": {"enabled": True, "runtime": {"mode": "service"}}},
            }
            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook, "decide",
                                 return_value={"decision": "block", "next_action": {}}), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(0, result)
        self.assertEqual({"decision": "approve"}, json.loads(output.getvalue()))

    def test_frozen_hook_failure_blocks_with_the_runner_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = {"workspace": str(root), "controller": {"snapshot": {"root": str(root)}}}
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "frozen runner exploded")

            def execute(command, **kwargs):
                return failed if "controller_snapshot.py" in str(command[1]) else real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "active_state", return_value=(root / "run.json", state)), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "codex"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": str(root)}))), \
                    redirect_stdout(output):
                result = autonomy_hook.main()

        self.assertEqual(2, result)
        self.assertIn("frozen runner exploded", json.loads(output.getvalue())["reason"])

    def test_codex_state_write_failure_blocks_instead_of_losing_the_intent(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "state write blocked")

            def execute(command, **kwargs):
                return failed if "delivery_state.py" in str(command[1]) else real_run(command, **kwargs)

            result, output = self.run_managed_hook_in_process(
                "codex", {}, path, state_root, lease_root, execute,
            )
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("state write blocked", json.loads(output)["reason"])
        self.assertEqual(0, len(current["execution_control"]["autonomy"]["action_attempts"]))

    def test_claude_terminalize_failure_falls_back_to_a_final_terminalization(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            real_run = subprocess.run
            failed = subprocess.CompletedProcess([], 2, "", "state write blocked")
            state_writes = []

            def execute(command, **kwargs):
                if "delivery_state.py" in str(command[1]):
                    state_writes.append(command)
                    if len(state_writes) == 1:
                        return failed
                return real_run(command, **kwargs)

            result, output = self.run_managed_hook_in_process(
                "claude", {"session_id": "thread-1"}, path, state_root, lease_root, execute,
            )
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("state write blocked", json.loads(output)["reason"])
        self.assertEqual(2, len(state_writes))
        self.assertEqual("blocked", current["status"])

    def test_claude_release_failure_blocks_instead_of_losing_the_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            real_run = subprocess.run

            def execute(command, **kwargs):
                if "delivery_lease.py" in str(command[1]):
                    return subprocess.CompletedProcess([], 1, "", "lease unavailable")
                return real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "write_state"), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "claude"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": state["workspace"]}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(output):
                result = autonomy_hook.main()
            current = json.loads(path.read_text(encoding="utf-8"))
            held = [p.exists() for p in lease_paths(
                lease_root, state["repo_id"], state["workspace"], state["task_key"]
            ).values()]

        self.assertEqual(2, result)
        self.assertIn("lease unavailable", json.loads(output.getvalue())["reason"])
        self.assertEqual("active", current["status"])
        self.assertTrue(any(held))

    def test_claude_release_output_that_is_not_a_release_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            path, state_root, lease_root = self.managed_hook_state(directory)
            state = json.loads(path.read_text(encoding="utf-8"))
            real_run = subprocess.run

            def execute(command, **kwargs):
                if "delivery_lease.py" in str(command[1]):
                    return subprocess.CompletedProcess([], 0, '{"status": "kept"}', "")
                return real_run(command, **kwargs)

            output = StringIO()
            with patch.object(autonomy_hook, "write_state"), \
                    patch.object(autonomy_hook.subprocess, "run", side_effect=execute), \
                    patch.object(sys, "argv", ["autonomy_hook.py", "--host", "claude"]), \
                    patch("sys.stdin", StringIO(json.dumps({"cwd": state["workspace"]}))), \
                    patch.dict(os.environ, {
                        "CONVERGE_STATE_ROOT": str(state_root),
                        "CONVERGE_LEASE_ROOT": str(lease_root),
                    }), \
                    redirect_stdout(output):
                result = autonomy_hook.main()
            current = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(2, result)
        self.assertIn("could not release autonomous lease", json.loads(output.getvalue())["reason"])
        self.assertEqual("active", current["status"])


if __name__ == "__main__":
    unittest.main()
