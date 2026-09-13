import json
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

    def test_codex_start_uses_the_direct_app_server_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            server = MagicMock()
            server.__enter__.return_value = server
            server.request.side_effect = [
                {"thread": {"id": "thread-1"}},
                {"turn": {"id": "turn-1"}},
            ]
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_CodexAppServer", return_value=server):
                started = host_bridge.codex_start(package, "frozen prompt")

        self.assertEqual("thread-1", started["task_id"])
        self.assertEqual(("thread/start", {"cwd": package["workspace"], "ephemeral": True}),
                         server.request.call_args_list[0].args)
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

    def test_preflight_reports_ready_host_adapters(self):
        with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT), \
                patch.object(host_bridge, "_claude_agent_list", return_value=[]):
            result = host_bridge.preflight()

        self.assertEqual(
            {
                "codex": {"status": "ready", "host_fingerprint": HOST_FINGERPRINT},
                "claude": {"status": "ready", "host_fingerprint": HOST_FINGERPRINT},
            },
            result,
        )

    def test_codex_schema_fingerprint_hashes_the_generated_schema(self):
        def generate(arguments, **_kwargs):
            output = Path(arguments[arguments.index("--out") + 1])
            (output / "schema.json").write_text("{}", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(host_bridge, "_binary_identity", return_value=("codex", FINGERPRINT)), \
                patch.object(host_bridge.subprocess, "run", side_effect=generate):
            fingerprint = host_bridge.codex_schema_fingerprint()

        self.assertEqual(64, len(fingerprint))

    def test_app_server_request_returns_its_matching_response(self):
        server = host_bridge._CodexAppServer("codex", timeout_seconds=1)
        server.process = SimpleNamespace(stdin=Mock())
        server.messages.put({"id": 1, "result": {"ready": True}})

        self.assertEqual({"ready": True}, server.request("initialize", {}))
        server.process.stdin.write.assert_called_once()
        server.process.stdin.flush.assert_called_once()

    def test_app_server_request_rejects_an_invalid_response(self):
        server = host_bridge._CodexAppServer("codex", timeout_seconds=1)
        server.process = SimpleNamespace(stdin=Mock())
        server.messages.put({"id": 1, "result": {}, "error": "unexpected"})

        with self.assertRaisesRegex(ValueError, "rejected initialize"):
            server.request("initialize", {})

    def test_app_server_reader_records_terminal_turn_status(self):
        server = host_bridge._CodexAppServer("codex")
        server.process = SimpleNamespace(stdout=[json.dumps({
            "method": "turn/completed", "params": {"turn": {"id": "turn-1", "status": "completed"}},
        })])

        server._read()

        self.assertEqual("completed", server.turn_statuses["turn-1"])

    def test_app_server_reader_records_stream_errors(self):
        def broken_stream():
            raise OSError("stream failed")
            yield None

        server = host_bridge._CodexAppServer("codex")
        server.process = SimpleNamespace(stdout=broken_stream())
        server._read()

        self.assertIsInstance(server.messages.get_nowait(), OSError)

    def test_app_server_enters_and_closes_its_ephemeral_process(self):
        process = Mock()
        process.poll.return_value = None
        process.stdout = []
        with patch.object(host_bridge, "_binary_identity", return_value=("codex", FINGERPRINT)), \
                patch.object(host_bridge.subprocess, "Popen", return_value=process), \
                patch.object(host_bridge._CodexAppServer, "request", return_value={}):
            server = host_bridge._CodexAppServer("codex")
            self.assertIs(server, server.__enter__())
            server.close()

        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)

    def test_app_server_request_rejects_timeout_and_invalid_stream(self):
        timeout = host_bridge._CodexAppServer("codex", timeout_seconds=0)
        timeout.process = SimpleNamespace(stdin=Mock())
        with self.assertRaisesRegex(ValueError, "did not answer initialize"):
            timeout.request("initialize", {})

        invalid = host_bridge._CodexAppServer("codex", timeout_seconds=1)
        invalid.process = SimpleNamespace(stdin=Mock())
        invalid.messages.put(ValueError("bad stream"))
        with self.assertRaisesRegex(ValueError, "stream is invalid"):
            invalid.request("initialize", {})

        waiting = host_bridge._CodexAppServer("codex", timeout_seconds=0.001)
        waiting.process = SimpleNamespace(stdin=Mock())
        with self.assertRaisesRegex(ValueError, "did not answer initialize"):
            waiting.request("initialize", {})

    def test_host_package_and_receipt_reject_invalid_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            with self.assertRaisesRegex(ValueError, "host is invalid"):
                host_bridge.package(
                    host="other", sample_id="sample", workspace=directory, prompt="prompt",
                    judge_argv=["python3"], launch_fingerprint=FINGERPRINT,
                    host_fingerprint=HOST_FINGERPRINT,
                )
            with self.assertRaisesRegex(ValueError, "host package"):
                host_bridge._package({})
            with self.assertRaisesRegex(ValueError, "host task"):
                host_bridge._started({}, package)
            with self.assertRaisesRegex(ValueError, "terminal status"):
                host_bridge.terminal_observation(
                    package, task_id="thread-1", status="working", host_fingerprint=HOST_FINGERPRINT,
                )
            observation = host_bridge.terminal_observation(
                package, task_id="thread-1", status="completed", host_fingerprint=HOST_FINGERPRINT,
            )
            with self.assertRaisesRegex(ValueError, "frozen judge"):
                host_bridge.finalize(
                    package, observation,
                    {"argv": ["python3", "judge.py"], "exit_code": True,
                     "stdout_fingerprint": FINGERPRINT, "stderr_fingerprint": FINGERPRINT},
                )
        with self.assertRaisesRegex(ValueError, "workspace is invalid"):
            host_bridge.package(
                host="codex", sample_id="sample", workspace="/missing/converge-workspace", prompt="prompt",
                judge_argv=["python3"], launch_fingerprint=FINGERPRINT, host_fingerprint=HOST_FINGERPRINT,
            )

    def test_host_bridge_rejects_invalid_primitive_values(self):
        with self.assertRaisesRegex(ValueError, "text is invalid"):
            host_bridge._text(" ", "text")
        with self.assertRaisesRegex(ValueError, "digest is invalid"):
            host_bridge._sha256("not-a-digest", "digest")
        with self.assertRaisesRegex(ValueError, "argv is invalid"):
            host_bridge._argv([], "argv")

    def test_codex_schema_fingerprint_rejects_an_empty_schema_directory(self):
        with patch.object(host_bridge, "_binary_identity", return_value=("codex", FINGERPRINT)), \
                patch.object(host_bridge.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(ValueError, "did not generate"):
                host_bridge.codex_schema_fingerprint()

    def test_codex_observe_rejects_a_lost_ephemeral_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-lost",
                "turn_id": "turn-lost", "host_fingerprint": HOST_FINGERPRINT,
            }
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "connection is unavailable"):
                    host_bridge.codex_observe(package, started)

    def test_codex_observe_handles_active_and_unknown_turn_statuses(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-active",
                "turn_id": "turn-active", "host_fingerprint": HOST_FINGERPRINT,
            }
            server = SimpleNamespace(turn_statuses={"turn-active": "inProgress"}, close=Mock())
            host_bridge._CODEX_SERVERS["thread-active"] = server
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                self.assertIsNone(host_bridge.codex_observe(package, started))
                server.turn_statuses["turn-active"] = "unknown"
                with self.assertRaisesRegex(ValueError, "unknown turn status"):
                    host_bridge.codex_observe(package, started)
            host_bridge._CODEX_SERVERS.pop("thread-active", None)

    def test_codex_observe_validates_the_host_and_turn_listing(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            claude_package = self.package(directory, host="claude")
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-empty",
                "turn_id": "turn-empty", "host_fingerprint": HOST_FINGERPRINT,
            }
            with self.assertRaisesRegex(ValueError, "not for Codex"):
                host_bridge.codex_observe(claude_package, started)
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "schema changed"):
                    host_bridge.codex_observe(package, started, request=Mock())
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "did not return"):
                    host_bridge.codex_observe(package, started, request=Mock(return_value={"data": []}))
            host_bridge._CODEX_SERVERS["thread-empty"] = SimpleNamespace(turn_statuses={}, close=Mock())
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT):
                self.assertIsNone(host_bridge.codex_observe(package, started))
            host_bridge._CODEX_SERVERS.pop("thread-empty", None)

    def test_codex_start_rejects_a_non_codex_package(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            with self.assertRaisesRegex(ValueError, "not for Codex"):
                host_bridge.codex_start(package, "frozen prompt")

    def test_codex_start_closes_the_connection_after_a_failed_start(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            server = MagicMock()
            server.__enter__.return_value = server
            server.request.return_value = {"thread": {}}
            with patch.object(host_bridge, "codex_schema_fingerprint", return_value=HOST_FINGERPRINT), \
                    patch.object(host_bridge, "_CodexAppServer", return_value=server):
                with self.assertRaisesRegex(ValueError, "thread id"):
                    host_bridge.codex_start(package, "frozen prompt")

        server.close.assert_called_once()

    def test_host_dispatchers_select_the_package_host(self):
        with tempfile.TemporaryDirectory() as directory:
            codex = self.package(directory)
            claude = self.package(directory, host="claude")
            with patch.object(host_bridge, "codex_start", return_value={"task_id": "codex"}) as codex_start, \
                    patch.object(host_bridge, "claude_start", return_value={"task_id": "claude"}) as claude_start, \
                    patch.object(host_bridge, "codex_observe", return_value={"status": "completed"}), \
                    patch.object(host_bridge, "claude_observe", return_value={"status": "completed"}):
                self.assertEqual({"task_id": "codex"}, host_bridge.start(codex, "prompt"))
                self.assertEqual({"task_id": "claude"}, host_bridge.start(claude, "prompt"))
                self.assertEqual({"status": "completed"}, host_bridge.observe(codex, {}))
                self.assertEqual({"status": "completed"}, host_bridge.observe(claude, {}))

        codex_start.assert_called_once()
        claude_start.assert_called_once()

    def test_claude_start_rejects_a_failed_background_command(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            with patch.object(host_bridge, "_binary_identity", return_value=("claude", HOST_FINGERPRINT)):
                with self.assertRaisesRegex(ValueError, "returned status 1"):
                    host_bridge.claude_start(
                        package, "frozen prompt", agents=Mock(return_value=[]),
                        run=Mock(return_value=SimpleNamespace(returncode=1)),
                    )

    def test_claude_start_rejects_a_non_claude_package(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            with self.assertRaisesRegex(ValueError, "not for Claude"):
                host_bridge.claude_start(package, "frozen prompt")

    def test_claude_start_rejects_changed_or_unregistered_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            with patch.object(host_bridge, "_binary_identity", return_value=("claude", FINGERPRINT)):
                with self.assertRaisesRegex(ValueError, "binary changed"):
                    host_bridge.claude_start(package, "frozen prompt", agents=Mock(return_value=[]))
            with patch.object(host_bridge, "_binary_identity", return_value=("claude", HOST_FINGERPRINT)):
                with self.assertRaisesRegex(ValueError, "inventory is invalid"):
                    host_bridge.claude_start(package, "frozen prompt", agents=Mock(return_value={}))
                with self.assertRaisesRegex(ValueError, "did not confirm"):
                    host_bridge.claude_start(
                        package, "frozen prompt", agents=Mock(side_effect=[[], []]),
                        run=Mock(return_value=SimpleNamespace(returncode=0)),
                    )

    def test_claude_observe_returns_none_while_the_session_is_working(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            started = {
                "protocol": "host-bridge-v1", "host": "claude", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "agent-1",
                "turn_id": "session-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            agents = Mock(return_value=[{
                "id": "agent-1", "sessionId": "session-1", "cwd": package["workspace"], "state": "working",
            }])
            with patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT):
                self.assertIsNone(host_bridge.claude_observe(package, started, agents=agents))

    def test_claude_observe_rejects_wrong_host_binary_and_session(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory, host="claude")
            codex_package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "claude", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "agent-1",
                "turn_id": "session-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            with self.assertRaisesRegex(ValueError, "not for Claude"):
                host_bridge.claude_observe(codex_package, started)
            with patch.object(host_bridge, "_binary_fingerprint", return_value=FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "binary changed"):
                    host_bridge.claude_observe(package, started, agents=Mock(return_value=[]))
            with patch.object(host_bridge, "_binary_fingerprint", return_value=HOST_FINGERPRINT):
                with self.assertRaisesRegex(ValueError, "did not return"):
                    host_bridge.claude_observe(package, started, agents=Mock(return_value=[]))
                with self.assertRaisesRegex(ValueError, "unknown evaluator state"):
                    host_bridge.claude_observe(package, started, agents=Mock(return_value=[{
                        "id": "agent-1", "sessionId": "session-1", "cwd": package["workspace"], "state": "other",
                    }]))

    def test_wait_terminal_returns_the_first_terminal_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            expected = {"status": "completed"}
            with patch.object(host_bridge, "observe", return_value=expected):
                self.assertIs(expected, host_bridge.wait_terminal(
                    package, started, deadline=time.monotonic() + 1,
                ))

    def test_wait_terminal_polls_before_the_host_becomes_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            package = self.package(directory)
            started = {
                "protocol": "host-bridge-v1", "host": "codex", "sample_id": package["sample_id"],
                "package_fingerprint": host_bridge._fingerprint(package), "task_id": "thread-1",
                "turn_id": "turn-1", "host_fingerprint": HOST_FINGERPRINT,
            }
            expected = {"status": "completed"}
            with patch.object(host_bridge, "observe", side_effect=[None, expected]):
                self.assertIs(expected, host_bridge.wait_terminal(
                    package, started, deadline=time.monotonic() + 1, poll_seconds=0.001,
                ))

    def test_wait_terminal_rejects_invalid_deadline_and_poll_interval(self):
        with self.assertRaisesRegex(ValueError, "deadline"):
            host_bridge.wait_terminal({}, {}, deadline=True)
        with self.assertRaisesRegex(ValueError, "poll interval"):
            host_bridge.wait_terminal({}, {}, deadline=1, poll_seconds=0)

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
