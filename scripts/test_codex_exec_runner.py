#!/usr/bin/env python3
"""Tests for bounded Codex CLI launch construction; no Codex run is executed."""

import io
import os
import signal
import shutil
import threading
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

from codex_exec_runner import command_for_launch, execute_launch, plan_launch
from runner_contract import freeze_launch
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "implementation-1",
        "role": "implementer",
        "runner_id": "codex-exec-v1",
        "requested": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "effective": {"provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "permissions": {"workspace": "write", "shell": True, "network": "egress"},
        "budget": {"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 12000},
    }
    value.update(overrides)
    identity = {key: item for key, item in value.items() if key != "profile_fingerprint"}
    return {**identity, "profile_fingerprint": fingerprint(identity)}


class CodexExecRunnerTest(unittest.TestCase):
    def test_leaf_commands_override_agent_settings_for_readers_and_writers(self):
        for access in ("read", "write"):
            with self.subTest(access=access), mock.patch("codex_exec_runner._is_isolated_worktree", return_value=True):
                worker_profile = profile(permissions={"workspace": access, "shell": True, "network": "egress"})
                launch = plan_launch(worker_profile, "probe", workspace="/tmp", codex_bin=sys.executable)
                command = command_for_launch(launch, "probe")
                overrides = dict(command[i + 1].split("=", 1) for i, value in enumerate(command) if value == "-c")
                self.assertEqual("false", overrides.get("agents.enabled"))
                self.assertEqual("false", overrides.get("features.multi_agent"))
                self.assertEqual("false", overrides.get("features.multi_agent_v2"))
                self.assertEqual("workspace-write" if access == "write" else "read-only",
                                 command[command.index("--sandbox") + 1])
                self.assertEqual(worker_profile["effective"]["model"], command[command.index("-m") + 1])

    def test_reader_and_progress_errors_never_deliver_partial_success(self):
        import claude_exec_runner
        from test_claude_exec_runner import profile as claude_profile

        class FaultyStream(io.BytesIO):
            def read(self, size=-1):
                data = super().read(size)
                if not data:
                    raise OSError("injected pipe failure")
                return data

        for module, worker_profile, binary_option, output in (
            (__import__("codex_exec_runner"), profile(
                permissions={"workspace": "read", "shell": True, "network": "egress"},
            ), "codex_bin", b'{"item":{"type":"agent_message","text":"partial"}}\n'),
            (claude_exec_runner, claude_profile(), "claude_bin", b'{"result":"partial"}'),
        ):
            for fault in ("stdout-empty", "stdout-partial", "stderr-empty", "stderr-partial", "progress"):
                with self.subTest(runner=worker_profile["runner_id"], fault=fault):
                    process = mock.Mock(pid=None, stdin=io.BytesIO(), stdout=io.BytesIO(output),
                                        stderr=io.BytesIO())
                    process.wait.return_value = 0
                    callback = None
                    if fault == "progress":
                        callback = mock.Mock(side_effect=RuntimeError("progress unavailable"))
                    else:
                        stream, portion = fault.split("-")
                        setattr(process, stream, FaultyStream(output if portion == "partial" else b""))
                    launch = module.plan_launch(worker_profile, "probe", workspace="/tmp",
                                                **{binary_option: sys.executable})
                    with mock.patch.object(threading, "excepthook") as uncaught:
                        receipt, content = module.execute_launch(
                            launch, "probe", allow_execute=True, capture_content=True,
                            process_factory=lambda *_args, **_kwargs: process, on_progress=callback,
                        )
                    self.assertEqual("unknown", receipt["status"])
                    self.assertEqual("RuntimeError" if callback else "OSError", receipt["error_type"])
                    self.assertIsNone(content)
                    process.kill.assert_called()
                    uncaught.assert_not_called()
                    self.assertTrue(all(getattr(process, name).closed for name in ("stdin", "stdout", "stderr")))

    def test_exit_cleans_redirected_children_for_both_runners(self):
        import claude_exec_runner
        from test_claude_exec_runner import profile as claude_profile

        for planner, executor, worker_profile, binary_option in (
            (plan_launch, execute_launch, profile(
                permissions={"workspace": "read", "shell": True, "network": "egress"},
            ), "codex_bin"),
            (claude_exec_runner.plan_launch, claude_exec_runner.execute_launch,
             claude_profile(), "claude_bin"),
        ):
            for code in (0, 7):
                with self.subTest(runner=worker_profile["runner_id"], code=code), tempfile.TemporaryDirectory() as directory:
                    ready, release, marker = [Path(directory) / name for name in ("ready", "release", "marker")]
                    child = (
                        "import time; from pathlib import Path\n"
                        f"Path({str(ready)!r}).touch()\n"
                        f"while not Path({str(release)!r}).exists(): time.sleep(0.01)\n"
                        f"Path({str(marker)!r}).touch()\n"
                    )
                    parent = (
                        "import subprocess,sys,time; from pathlib import Path\n"
                        "sys.stdin.read()\n"
                        f"subprocess.Popen([sys.executable, '-c', {child!r}], stdin=subprocess.DEVNULL, "
                        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                        f"while not Path({str(ready)!r}).exists(): time.sleep(0.01)\n"
                        f"sys.exit({code})\n"
                    )
                    processes = []

                    def factory(_command, **kwargs):
                        process = subprocess.Popen([sys.executable, "-c", parent], **kwargs)
                        processes.append(process)
                        return process

                    launch = planner(worker_profile, "probe", workspace=directory,
                                     **{binary_option: sys.executable})
                    try:
                        receipt = executor(launch, "probe", allow_execute=True, process_factory=factory)
                        self.assertEqual("completed" if code == 0 else "failed", receipt["status"])
                        self.assertEqual(code, receipt["exit_code"])
                        release.touch()
                        time.sleep(0.3)
                        self.assertFalse(marker.exists(), "child wrote after the runner returned")
                    finally:
                        for process in processes:
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass

    def test_group_cleanup_failure_never_reports_completion(self):
        for timed_out in (False, True):
            with self.subTest(timed_out=timed_out):
                process = mock.Mock(pid=123, stdin=io.BytesIO(), stdout=io.BytesIO(), stderr=io.BytesIO())
                process.wait.side_effect = [subprocess.TimeoutExpired("probe", 1), 0] if timed_out else [0, 0]
                launch = plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                                     "probe", workspace="/tmp", codex_bin=sys.executable)
                with mock.patch("codex_exec_runner.os.killpg", side_effect=PermissionError("denied")):
                    receipt = execute_launch(launch, "probe", allow_execute=True,
                                             process_factory=lambda *_args, **_kwargs: process)
                self.assertEqual("unknown", receipt["status"])
                self.assertEqual("PermissionError", receipt["error_type"])

    def test_timeout_includes_inherited_output_pipes_for_both_runners(self):
        import claude_exec_runner
        from test_claude_exec_runner import profile as claude_profile

        for planner, executor, worker_profile, binary_option in (
            (plan_launch, execute_launch, profile(
                permissions={"workspace": "read", "shell": True, "network": "egress"},
                budget={"max_turns": 1, "timeout_seconds": 1, "max_output_chars": 1000},
            ), "codex_bin"),
            (claude_exec_runner.plan_launch, claude_exec_runner.execute_launch, claude_profile(
                budget={"max_turns": 1, "timeout_seconds": 1, "max_output_chars": 1000},
            ), "claude_bin"),
        ):
            with self.subTest(runner=worker_profile["runner_id"]), tempfile.TemporaryDirectory() as directory:
                launch = planner(worker_profile, "probe", workspace=directory, **{binary_option: sys.executable})
                processes = []

                def factory(_command, **kwargs):
                    process = subprocess.Popen([
                        sys.executable, "-c",
                        "import subprocess,sys; sys.stdin.read(); "
                        "subprocess.Popen([sys.executable,'-c','import time; time.sleep(4)'])",
                    ], **kwargs)
                    processes.append(process)
                    return process

                start = time.monotonic()
                receipt = executor(launch, "probe", allow_execute=True, process_factory=factory)
                elapsed = time.monotonic() - start
                self.assertEqual("timed_out", receipt["status"])
                self.assertLess(elapsed, 3)
                self.assertIsNotNone(processes[0].poll())

    def test_freezes_model_effort_and_workspace_without_storing_the_command_prompt(self):
        read_profile = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        launch = plan_launch(
            read_profile, "Fix the isolated task", workspace="/tmp", codex_bin=shutil.which("codex")
        )
        command = command_for_launch(launch, "Fix the isolated task")
        self.assertEqual(str(Path(shutil.which("codex")).resolve()), command[0])
        self.assertIn("--json", command)
        self.assertIn("--ephemeral", command)
        self.assertNotIn("--ignore-user-config", command)
        self.assertNotIn("--ignore-rules", command)
        self.assertIn("features.respect_system_proxy=true", command)
        self.assertIn("--sandbox", command)
        self.assertEqual("read-only", command[command.index("--sandbox") + 1])
        self.assertEqual("gpt-5.6-terra", command[command.index("-m") + 1])
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertNotIn("--max-turns", command)
        self.assertEqual("-", command[-1])
        self.assertEqual(str(Path("/tmp").resolve()), launch["configuration"]["workspace"])
        self.assertNotIn("Fix the isolated task", str(launch))
        self.assertEqual("runner", launch["evidence_source"])
        self.assertEqual("planned", launch["status"])

    def test_rejects_model_or_effort_substitution(self):
        changed = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        changed["effective"]["reasoning_effort"] = "low"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            plan_launch(changed, "Fix the isolated task", workspace="/tmp")

    def test_rejects_execution_when_the_inherited_user_config_changes(self):
        read_profile = profile(permissions={"workspace": "read", "shell": True, "network": "egress"})
        with mock.patch("codex_exec_runner._user_config_fingerprint", side_effect=["a" * 64, "b" * 64]):
            launch = plan_launch(read_profile, "Fix the isolated task", workspace="/tmp")
            with self.assertRaisesRegex(ValueError, "user config changed"):
                command_for_launch(launch, "Fix the isolated task")

    def test_requires_explicit_permission_before_starting_a_real_process(self):
        with self.assertRaisesRegex(ValueError, "explicit"):
            execute_launch(
                plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                            "Fix the isolated task", workspace="/tmp"),
                "Fix the isolated task",
            )

    def test_rejects_a_prompt_that_does_not_match_the_frozen_launch(self):
        launch = plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                             "Fix the isolated task", workspace="/tmp")

        with self.assertRaisesRegex(ValueError, "prompt"):
            execute_launch(launch, "Do something else", allow_execute=True)

    def test_rejects_write_launches_in_the_primary_worktree(self):
        with self.assertRaisesRegex(ValueError, "worktree"):
            plan_launch(profile(), "Fix the isolated task", workspace=".")

    def test_rejects_a_primary_worktree_subdirectory_for_write_access(self):
        with self.assertRaisesRegex(ValueError, "worktree"):
            plan_launch(profile(), "Fix the isolated task", workspace="scripts")

    def test_rejects_a_directly_frozen_launch_that_escalates_read_access_to_write(self):
        binary = Path(shutil.which("codex")).resolve()
        launch = freeze_launch(
            profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
            "Fix the isolated task", {
                "codex_bin": str(binary),
                "binary_fingerprint": __import__("hashlib").sha256(binary.read_bytes()).hexdigest(),
                "sandbox": "workspace-write",
                "workspace": str(Path(".").resolve()),
            },
        )

        with self.assertRaisesRegex(ValueError, "sandbox"):
            command_for_launch(launch, "Fix the isolated task")

    def test_rechecks_directly_frozen_write_workspace_before_execution(self):
        binary = Path(shutil.which("codex")).resolve()
        launch = freeze_launch(profile(), "Fix the isolated task", {
            "codex_bin": str(binary),
            "binary_fingerprint": __import__("hashlib").sha256(binary.read_bytes()).hexdigest(),
            "sandbox": "workspace-write",
            "workspace": str(Path(".").resolve()),
        })

        with self.assertRaisesRegex(ValueError, "worktree"):
            command_for_launch(launch, "Fix the isolated task")

    def test_marks_output_that_exceeds_the_frozen_budget_as_non_completed(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b"too large")
            stderr = io.BytesIO()
            returncode = 0

            def wait(self, timeout):
                return self.returncode

            def kill(self):
                self.returncode = 125

        execution = execute_launch(
            plan_launch(
                profile(permissions={"workspace": "read", "shell": True, "network": "egress"},
                        budget={"max_turns": 2, "timeout_seconds": 180, "max_output_chars": 3}),
                "Fix the isolated task", workspace="/tmp",
            ),
            "Fix the isolated task", allow_execute=True, capture_content=True,
            process_factory=lambda *_args, **_kwargs: Process(),
        )

        receipt, content = execution
        self.assertEqual("output_exceeded", receipt["status"])
        self.assertEqual(125, receipt["exit_code"])
        self.assertEqual("gpt-5.6-terra", receipt["requested_model"])
        self.assertEqual("high", receipt["requested_reasoning_effort"])
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual(
            {"model": {"status": "requested", "observed": None},
             "usage": {"status": "unavailable", "value": None}},
            receipt["attestation"],
        )
        self.assertIsNone(content)

    def test_reports_bounded_io_liveness_without_persisting_output(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(b'{"type":"thread.started"}\n')
            stderr = io.BytesIO()

            def wait(self, timeout):
                return 0

            def kill(self):
                pass

        events = []
        execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Collect evidence", workspace="/tmp"),
            "Collect evidence", allow_execute=True,
            process_factory=lambda *_args, **_kwargs: Process(),
            on_progress=lambda event: events.append(event),
        )

        self.assertEqual([{"stream": "stdout", "bytes": 26}], events)

    def test_returns_the_final_jsonl_agent_message_only_in_the_ephemeral_output(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO(
                b'{"type":"item.completed","item":{"type":"agent_message","text":"First"}}\n'
                b'{"type":"item.completed","item":{"type":"agent_message","text":"Final evidence"}}\n'
            )
            stderr = io.BytesIO()

            def wait(self, timeout):
                return 0

            def kill(self):
                pass

        execution = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Collect evidence", workspace="/tmp"),
            "Collect evidence", allow_execute=True, capture_content=True,
            process_factory=lambda *_args, **_kwargs: Process(),
        )

        receipt, content = execution
        self.assertEqual("completed", receipt["status"])
        self.assertEqual("Final evidence", content)

    def test_returns_a_receipt_when_process_start_fails(self):
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True,
            process_factory=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("missing")),
        )

        self.assertEqual("unknown", receipt["status"])
        self.assertEqual("OSError", receipt["error_type"])

    def test_reaps_a_timed_out_process(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            killed = False
            reaped = False

            def wait(self, timeout=None):
                if not getattr(self, "waited", False):
                    self.waited = True
                    raise __import__("subprocess").TimeoutExpired("codex", timeout)
                self.reaped = True
                return 124

            def kill(self):
                self.killed = True

        process = Process()
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True, process_factory=lambda *_args, **_kwargs: process,
        )

        self.assertEqual("timed_out", receipt["status"])
        self.assertTrue(process.killed)
        self.assertTrue(process.reaped)

    def test_timeout_kills_the_entire_process_group(self):
        class Process:
            stdin = io.BytesIO()
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            pid = 123

            def wait(self, timeout=None):
                if not getattr(self, "waited", False):
                    self.waited = True
                    raise __import__("subprocess").TimeoutExpired("codex", timeout)
                return 124

            def kill(self):
                raise AssertionError("process-group termination should be used")

        with mock.patch("codex_exec_runner.os.killpg") as killpg:
            receipt = execute_launch(
                plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                            "Fix the isolated task", workspace="/tmp"),
                "Fix the isolated task", allow_execute=True,
                process_factory=lambda *_args, **_kwargs: Process(),
            )

        self.assertEqual("timed_out", receipt["status"])
        killpg.assert_called_once_with(123, __import__("signal").SIGKILL)

    def test_timeout_starts_while_the_prompt_writer_is_still_blocked(self):
        class Input:
            def __init__(self):
                self.writing = threading.Event()
                self.release = threading.Event()

            def write(self, _value):
                self.writing.set()
                self.release.wait()

            def close(self):
                pass

        class Process:
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            killed = False
            reaped = False

            def __init__(self):
                self.stdin = Input()

            def wait(self, timeout=None):
                if not self.killed:
                    self.stdin.writing.wait(timeout)
                    if self.stdin.release.is_set():
                        raise AssertionError("prompt writing completed before timeout started")
                    raise __import__("subprocess").TimeoutExpired("codex", timeout)
                self.reaped = True
                return 124

            def kill(self):
                self.killed = True
                self.stdin.release.set()

        process = Process()
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True, process_factory=lambda *_args, **_kwargs: process,
        )

        self.assertEqual("timed_out", receipt["status"])
        self.assertTrue(process.killed)
        self.assertTrue(process.reaped)

    def test_reaps_a_started_process_when_stdin_fails(self):
        class Input:
            def write(self, _value):
                raise BrokenPipeError("closed")

            def close(self):
                pass

        class Process:
            stdin = Input()
            stdout = io.BytesIO()
            stderr = io.BytesIO()
            killed = False
            reaped = False

            def kill(self):
                self.killed = True

            def wait(self, timeout=None):
                self.reaped = True
                return 125

        process = Process()
        receipt = execute_launch(
            plan_launch(profile(permissions={"workspace": "read", "shell": True, "network": "egress"}),
                        "Fix the isolated task", workspace="/tmp"),
            "Fix the isolated task", allow_execute=True, process_factory=lambda *_args, **_kwargs: process,
        )

        self.assertTrue(process.killed)
        self.assertTrue(process.reaped)
        self.assertEqual("BrokenPipeError", receipt["error_type"])


if __name__ == "__main__":
    unittest.main()
