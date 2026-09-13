import json
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import host_bridge


FINGERPRINT = "a" * 64
HOST_FINGERPRINT = "b" * 64


class HostBridgeTest(unittest.TestCase):
    def package(self, workspace, *, host="codex", host_fingerprint=HOST_FINGERPRINT):
        return host_bridge.package(
            host=host, sample_id="known_acceptance:roots", workspace=workspace,
            prompt="Run the frozen evaluator task.", judge_argv=["python3", "judge.py"],
            launch_fingerprint=FINGERPRINT, host_fingerprint=host_fingerprint,
        )

    def test_package_binds_one_sample_to_one_host_and_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)

        self.assertEqual("host-bridge-v1", package["protocol"])
        self.assertEqual("codex", package["host"])
        self.assertEqual(Path(directory).resolve(), Path(package["workspace"]))
        self.assertEqual(FINGERPRINT, package["launch_fingerprint"])
        self.assertEqual(HOST_FINGERPRINT, package["host_fingerprint"])
        self.assertNotIn("prompt", package)

    def test_terminal_receipt_requires_the_exact_host_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            observation = host_bridge.terminal_observation(
                package, task_id="thread-1", status="completed", host_fingerprint=HOST_FINGERPRINT,
            )
            receipt = host_bridge.finalize(
                package, observation,
                {"argv": ["python3", "judge.py"], "exit_code": 0,
                 "stdout_fingerprint": FINGERPRINT, "stderr_fingerprint": FINGERPRINT},
            )

        self.assertEqual("host_observed", receipt["evidence_level"])
        self.assertEqual("completed", receipt["terminal_status"])
        self.assertNotIn("prompt", receipt)

    def test_terminal_receipt_rejects_an_observation_for_another_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            observation = host_bridge.terminal_observation(
                package, task_id="thread-1", status="completed", host_fingerprint=HOST_FINGERPRINT,
            )
            observation["sample_id"] = "known_acceptance:other"
            with self.assertRaisesRegex(ValueError, "sample"):
                host_bridge.finalize(
                    package, observation,
                    {"argv": ["python3", "judge.py"], "exit_code": 0,
                     "stdout_fingerprint": FINGERPRINT, "stderr_fingerprint": FINGERPRINT},
                )

    def test_codex_start_rejects_schema_drift_before_creating_a_thread(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            request = Mock()
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "schema changed"):
                    host_bridge.codex_start(package, "frozen prompt", request=request)

        request.assert_not_called()

    def test_codex_start_bootstraps_daemon_and_uses_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            run = Mock(return_value=SimpleNamespace(returncode=0))
            proxy = MagicMock()
            proxy.__enter__.return_value = proxy
            proxy.request.side_effect = [
                {"thread": {"id": "thread-1"}},
                {"turn": {"id": "turn-1"}},
            ]
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_codex_proxy", return_value=proxy):
                started = host_bridge.codex_start(package, "frozen prompt", run=run)

        self.assertEqual("thread-1", started["task_id"])
        self.assertEqual(
            ["codex", "app-server", "daemon", "bootstrap"], run.call_args_list[0].args[0],
        )
        self.assertEqual(["codex", "app-server", "daemon", "start"], run.call_args_list[1].args[0])
        self.assertEqual(("thread/start", {"cwd": package["workspace"], "ephemeral": False}),
                         proxy.request.call_args_list[0].args)
        host_bridge._CODEX_SERVERS.pop("thread-1", None)

    def test_codex_observe_returns_a_terminal_observation_for_the_started_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            request = Mock(side_effect=[
                {"thread": {"id": "thread-1"}},
                {"turn": {"id": "turn-1"}},
                {"data": [{"id": "turn-1", "status": "completed"}]},
            ])
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                started = host_bridge.codex_start(package, "frozen prompt", request=request)
                observation = host_bridge.codex_observe(package, started, request=request)

        self.assertEqual("thread-1", started["task_id"])
        self.assertEqual("completed", observation["status"])

    def test_codex_observe_uses_the_live_connection_terminal_notification(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-live",
                "turn_id": "turn-live", "host_fingerprint": HOST_FINGERPRINT,
            }
            server = SimpleNamespace(turn_statuses={"turn-live": "completed"}, close=Mock())
            host_bridge._CODEX_SERVERS["thread-live"] = server
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                observation = host_bridge.codex_observe(package, started)

        self.assertEqual("completed", observation["status"])
        server.close.assert_called_once()

    def test_started_record_reloads_after_a_bridge_restart_without_a_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            host_bridge.persist_started(package, started)
            reloaded = host_bridge.load_started(package)
            record = json.loads(host_bridge.record_path(package).read_text())

        self.assertEqual(started, reloaded)
        self.assertNotIn("prompt", json.dumps(record))

    def test_conflicting_started_record_is_rejected_without_relaunch(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            host_bridge.persist_started(package, started)
            with self.assertRaisesRegex(ValueError, "conflicting"):
                host_bridge.persist_started(package, {**started, "task_id": "thread-other"})

    def test_new_proxy_resumes_the_exact_saved_task_and_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            host_bridge.persist_started(package, started)
            proxy = MagicMock()
            proxy.__enter__.return_value = proxy
            proxy.request.return_value = {
                "thread": {"id": "thread-1", "turns": [{"id": "turn-1", "status": "completed"}]},
            }
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_codex_proxy", return_value=proxy):
                observation = host_bridge.codex_observe(package, started)

        self.assertEqual("completed", observation["status"])
        proxy.request.assert_called_once_with(
            "thread/resume", {"threadId": "thread-1", "excludeTurns": False},
        )

    def test_existing_started_record_never_creates_a_replacement_task(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            host_bridge.persist_started(package, started)
            run = Mock()
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_codex_proxy") as proxy:
                resumed = host_bridge.codex_start(package, "frozen prompt", run=run)

        self.assertEqual(started, resumed)
        run.assert_not_called()
        proxy.assert_not_called()

    def test_preflight_requires_a_startable_codex_daemon(self):
        with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_codex_daemon") as daemon, \
                patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_claude_agent_list", return_value=[]):
            result = host_bridge.preflight()

        self.assertEqual("ready", result["codex"]["status"])
        daemon.assert_called_once_with("codex", subprocess.run)

    def test_preflight_reports_an_unstartable_codex_daemon(self):
        with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_codex_daemon", side_effect=ValueError("missing standalone")), \
                patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_claude_agent_list", return_value=[]):
            result = host_bridge.preflight()

        self.assertEqual("unavailable", result["codex"]["status"])
        self.assertIn("missing standalone", result["codex"]["reason"])

    def test_proxy_resume_identity_mismatch_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            host_bridge.persist_started(package, started)
            proxy = MagicMock()
            proxy.__enter__.return_value = proxy
            proxy.request.return_value = {
                "thread": {"id": "thread-other", "turns": [{"id": "turn-1", "status": "completed"}]},
            }
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_codex_proxy", return_value=proxy), \
                    self.assertRaisesRegex(ValueError, "does not match"):
                host_bridge.codex_observe(package, started)

    def test_claude_start_and_observe_require_the_registered_session_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            agent_name = f"converge-eval-{host_bridge._fingerprint(package)[:24]}"
            before = []
            registered = [{
                "id": "agent-1", "sessionId": "session-1", "name": agent_name,
                "cwd": str(Path(directory).resolve()), "state": "working",
            }]
            completed = [{**registered[0], "state": "completed"}]
            agents = Mock(side_effect=[before, registered, completed])
            run = Mock(return_value=Mock(returncode=0))
            with patch.object(host_bridge, "_binary_identity", return_value=("claude", HOST_FINGERPRINT)), \
                    patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT):
                started = host_bridge.claude_start(package, "frozen prompt", agents=agents, run=run)
                observation = host_bridge.claude_observe(package, started, agents=agents)

        self.assertEqual("agent-1", started["task_id"])
        self.assertEqual("completed", observation["status"])
        self.assertEqual(["claude", "--background"], run.call_args.args[0][:2])

    def test_wait_terminal_returns_no_receipt_when_the_host_never_becomes_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            with patch.object(host_bridge, "observe", return_value=None):
                with self.assertRaisesRegex(ValueError, "did not become terminal"):
                    host_bridge.wait_terminal(package, started, deadline=time.monotonic())


if __name__ == "__main__":
    unittest.main()
