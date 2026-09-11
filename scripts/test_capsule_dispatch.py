import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import Mock, patch


SCRIPT = Path(__file__).with_name("capsule_dispatch.py")
SPEC = importlib.util.spec_from_file_location("capsule_dispatch", SCRIPT)
capsule_dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capsule_dispatch)


class CapsuleDispatchTest(unittest.TestCase):
    def test_dispatch_helpers_reject_unreadable_invalid_and_conflicting_local_receipts(self):
        self.assertTrue(capsule_dispatch.default_attempt_id("codex", "/tmp", "capsule").startswith("codex-"))
        self.assertEqual("ValueError", capsule_dispatch.error_reason(ValueError()))
        with self.assertRaisesRegex(ValueError, "attempt id"):
            capsule_dispatch.receipt_path("/tmp", "BAD")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "unreadable"):
                capsule_dispatch.read_receipt(root / "missing.json")
            receipt = root / "receipt.json"
            receipt.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not an object"):
                capsule_dispatch.read_receipt(receipt)
            invalid = {
                "schema_version": 2, "workspace": str(root.resolve()), "status": "unknown",
            }
            with self.assertRaisesRegex(ValueError, "status"):
                capsule_dispatch.validate_saved_receipt(invalid)
            snapshot = root / "attempt.capsule.md"
            self.assertEqual(snapshot, capsule_dispatch.write_capsule_snapshot(snapshot, "frozen"))
            self.assertEqual(snapshot, capsule_dispatch.write_capsule_snapshot(snapshot, "frozen"))
            with self.assertRaisesRegex(ValueError, "different input"):
                capsule_dispatch.write_capsule_snapshot(snapshot, "changed")
            log = root / "events.jsonl"
            log.write_text("not-json\n{}\n", encoding="utf-8")
            self.assertIsNone(capsule_dispatch.codex_thread_id(log))
            with self.assertRaisesRegex(ValueError, "unreadable"):
                capsule_dispatch.codex_thread_id(root / "missing.jsonl")

    def test_capsule_helpers_surface_local_host_failures_without_retrying(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "canonical"):
                capsule_dispatch.validate_saved_receipt({
                    "schema_version": 2, "workspace": ".", "status": "attempted",
                })
            snapshot = root / "failure.capsule.md"
            descriptor = {}

            def fail_fdopen(value, *_arguments, **_keywords):
                descriptor["value"] = value
                raise OSError("disk")

            with patch.object(capsule_dispatch.os, "fdopen", side_effect=fail_fdopen):
                with self.assertRaises(OSError):
                    capsule_dispatch.write_capsule_snapshot(snapshot, "frozen")
            self.assertFalse(snapshot.exists())
            with self.assertRaises(OSError):
                capsule_dispatch.os.fstat(descriptor["value"])
            with patch.object(capsule_dispatch, "claude_agents", side_effect=ValueError("offline")):
                unavailable = capsule_dispatch.dispatch_claude(
                    "claude", root, "capsule", root / "receipts", "offline", 1,
                )
            self.assertEqual("unavailable", unavailable["status"])
            self.assertIn("offline", unavailable["reason"])
            retried = capsule_dispatch.unavailable(
                "claude", "capsule", root / "receipts", "offline", "ignored", workspace=root,
            )
            self.assertEqual("ignored", retried["reason"])

        with patch.object(capsule_dispatch.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "PATH"):
                capsule_dispatch.executable("codex")
        with patch.object(capsule_dispatch.subprocess, "run", side_effect=OSError("broken")):
            self.assertIn("failed", capsule_dispatch.capability_error("codex", "codex"))
        completed = Mock(returncode=7, stdout="", stderr="")
        with patch.object(capsule_dispatch.subprocess, "run", return_value=completed):
            self.assertIn("status 7", capsule_dispatch.capability_error("codex", "codex"))

    def test_dispatch_records_failed_or_timed_out_launches_without_claiming_delivery(self):
        writer = Mock()
        writer.is_alive.return_value = False
        process = Mock()
        process.returncode = 7
        process.poll.return_value = 7
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capsule_dispatch.subprocess, "Popen", return_value=process), \
                patch.object(capsule_dispatch, "_start_prompt_writer", return_value=(writer, [])), \
                patch.object(capsule_dispatch, "codex_thread_id", return_value=None):
            failed = capsule_dispatch.dispatch_codex(
                "codex", directory, "capsule", Path(directory) / "receipts", "failed", 1,
            )
            self.assertEqual("failed", failed["status"])
            self.assertIn("status 7", failed["reason"])

        listed = Mock(returncode=0, stdout=json.dumps({"agents": []}), stderr="")
        with patch.object(capsule_dispatch.subprocess, "run", return_value=listed):
            self.assertEqual([], capsule_dispatch.claude_agents("claude", "/tmp", time.monotonic() + 1))
        listed.stdout = json.dumps({"agents": {}})
        with patch.object(capsule_dispatch.subprocess, "run", return_value=listed):
            with self.assertRaisesRegex(ValueError, "list"):
                capsule_dispatch.claude_agents("claude", "/tmp", time.monotonic() + 1)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capsule_dispatch, "claude_agents", return_value=[]), \
                patch.object(capsule_dispatch.subprocess, "run", side_effect=subprocess.TimeoutExpired("claude", 1)):
            timed_out = capsule_dispatch.dispatch_claude(
                "claude", directory, "capsule", Path(directory) / "receipts", "timed-out", 1,
            )
        self.assertEqual("indeterminate", timed_out["status"])
        self.assertIn("timed out", timed_out["reason"])

    def test_dispatch_helper_success_and_cli_claude_route_are_explicit(self):
        discovered = {
            "id": "agent-1", "sessionId": "session-1", "name": "converge-test", "cwd": "/tmp",
        }
        with patch.object(capsule_dispatch, "claude_agents", return_value=[None, discovered]):
            self.assertEqual("session-1", capsule_dispatch.claude_session_registered(
                "claude", "/tmp", "converge-test", set(), time.monotonic() + 1,
            ))
        with patch.object(capsule_dispatch.shutil, "which", return_value="/bin/codex"):
            self.assertEqual("/bin/codex", capsule_dispatch.executable("codex"))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capsule_dispatch, "write_exclusive", side_effect=(False, True)) as write:
            self.assertIsNone(capsule_dispatch.saved_or_new(
                Path(directory) / "retry.json", "codex-exec-v1", "retry", "capsule", directory,
            ))
        self.assertEqual(2, write.call_count)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receipt = root / "receipts" / "existing.json"
            receipt.parent.mkdir()
            existing = capsule_dispatch.result(
                "codex-exec-v1", "existing", "capsule", "delivered",
                workspace=root, external_task_id="thread-1",
            )
            capsule_dispatch.persist(receipt, existing)
            self.assertEqual(existing, capsule_dispatch.unavailable(
                "codex", "capsule", receipt.parent, "existing", "ignored", workspace=root,
            ))

            capsule = root / "capsule.md"
            capsule.write_text("", encoding="utf-8")
            arguments = [
                str(SCRIPT), "--host", "claude", "--workspace", str(root),
                "--capsule-file", str(capsule), "--receipt-dir", str(root / "receipts"),
            ]
            with patch.object(sys, "argv", arguments), redirect_stderr(io.StringIO()) as error:
                self.assertEqual(2, capsule_dispatch.main())
            self.assertIn("must not be empty", error.getvalue())

            capsule.write_text("capsule", encoding="utf-8")
            delivered = capsule_dispatch.result(
                "claude-background-v1", "claude-test", "capsule", "delivered",
                workspace=root, external_task_id="session-1",
            )
            with patch.object(sys, "argv", arguments + ["--attempt-id", "claude-test"]), \
                    patch.object(capsule_dispatch, "executable", return_value="claude"), \
                    patch.object(capsule_dispatch, "capability_error", return_value=None), \
                    patch.object(capsule_dispatch, "dispatch_claude", return_value=delivered), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(0, capsule_dispatch.main())
            self.assertEqual("session-1", json.loads(stdout.getvalue())["external_task_id"])

    def test_codex_ignores_non_object_json_before_creation_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.executable(root, "codex",
                'cat >/dev/null\nprintf \'[]\\nnull\\n42\\n"noise"\\n\' >&2\n'
                'printf \'{"type":"thread.started","thread_id":"thread-confirmed"}\\n\'\n')
            result = capsule_dispatch.dispatch_codex(
                codex, root, "capsule", root / "receipts", "noisy", 5)
            self.assertEqual("delivered", result["status"])
            self.assertEqual("thread-confirmed", result["external_task_id"])
            self.assertEqual(result, capsule_dispatch.dispatch_codex(
                "/must-not-launch", root, "capsule", root / "receipts", "noisy", 1))

    def test_explicit_attempt_rejects_a_different_workspace_for_both_hosts(self):
        for host in ('codex', 'claude'):
            with self.subTest(host=host), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                first, second = root / 'first', root / 'second'
                first.mkdir()
                second.mkdir()
                dispatch = getattr(capsule_dispatch, 'dispatch_' + host)
                # Cache a failed launch without calling a real host.
                if host == 'codex':
                    dispatch('/nonexistent-host', first, 'capsule', root / 'receipts', 'shared', 1)
                else:
                    with patch.object(capsule_dispatch, 'claude_agents', return_value=[]):
                        dispatch('/nonexistent-host', first, 'capsule', root / 'receipts', 'shared', 1)
                with self.assertRaisesRegex(ValueError, 'different input|workspace'):
                    dispatch('/nonexistent-host', second, 'capsule', root / 'receipts', 'shared', 1)

    def test_cached_receipts_bind_workspace_before_reuse_or_retry(self):
        for status in ('attempted', 'delivered', 'unavailable', 'failed', 'indeterminate'):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                path = root / 'attempt.json'
                saved = capsule_dispatch.result(
                    'codex-exec-v1', 'attempt', 'capsule', status, workspace=root,
                    external_task_id='thread-1', reason='test observation',
                )
                capsule_dispatch.persist(path, saved)
                with self.assertRaisesRegex(ValueError, 'different input'):
                    capsule_dispatch.saved_or_new(path, 'codex-exec-v1', 'attempt', 'capsule', root / 'other')
                self.assertEqual(saved, json.loads(path.read_text()))
                reused = capsule_dispatch.saved_or_new(
                    path, 'codex-exec-v1', 'attempt', 'capsule', root / '.',
                )
                if status == 'unavailable':
                    self.assertIsNone(reused)
                else:
                    self.assertEqual('indeterminate' if status == 'attempted' else status, reused['status'])

    def executable(self, directory, name, body):
        path = Path(directory) / name
        path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        path.chmod(0o755)
        return str(path)

    def test_codex_starts_a_new_thread_and_persists_only_its_delivery_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            command = root / "command"
            codex = self.executable(
                root, "codex", f'printf "%s\\n" "$@" > "{command}"\n'
                              'cat >/dev/null\nprintf \'{"type":"thread.started","thread_id":"thread-codex-1"}\\n\'\n',
            )

            result = capsule_dispatch.dispatch_codex(
                codex, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )
            receipt_text = (root / "receipts" / "attempt-one.json").read_text(encoding="utf-8")
            receipt = json.loads(receipt_text)
            arguments = command.read_text(encoding="utf-8").splitlines()

        self.assertEqual("delivered", result["status"])
        self.assertEqual("thread-codex-1", result["external_task_id"])
        self.assertEqual(result, receipt)
        self.assertEqual(["exec", "--json", "-C", str(root.resolve()), "-"], arguments)
        self.assertNotIn("frozen capsule", receipt_text)

    def test_codex_large_capsule_timeout_includes_stdin_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.executable(
                root, "codex", 'printf \'{"type":"thread.started","thread_id":"early"}\\n\'\n'
                               'exec sleep 1\n',
            )
            started = time.monotonic()
            result = capsule_dispatch.dispatch_codex(
                codex, root, "x" * (1024 * 1024), root / "receipts", "large", 0.05,
            )
            elapsed = time.monotonic() - started
            self.assertLess(elapsed, 0.5)
            self.assertEqual("indeterminate", result["status"])
            with patch.object(capsule_dispatch.subprocess, "Popen", side_effect=AssertionError("redispatch")):
                replay = capsule_dispatch.dispatch_codex(
                    codex, root, "x" * (1024 * 1024), root / "receipts", "large", 0.05,
                )
            self.assertEqual(result, replay)

    def test_codex_checks_write_error_after_observing_writer_completion(self):
        errors = []
        writer = Mock()
        def finished():
            errors.append(BrokenPipeError("stdin closed"))
            return False
        writer.is_alive.side_effect = finished
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(capsule_dispatch.subprocess, "Popen"), \
                patch.object(capsule_dispatch, "_start_prompt_writer", return_value=(writer, errors)), \
                patch.object(capsule_dispatch, "codex_thread_id", return_value="early"):
            result = capsule_dispatch.dispatch_codex(
                "codex", directory, "capsule", Path(directory) / "receipts", "write-error", 1,
            )
        self.assertEqual("indeterminate", result["status"])
        self.assertNotIn("external_task_id", result)

    def test_rejects_a_delivered_receipt_without_a_task_id(self):
        for task_id in (None, ""):
            with self.subTest(task_id=task_id), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "attempt-one.json"
                capsule = "frozen capsule"
                path.write_text(json.dumps({
                    "schema_version": 2,
                    "workspace": str(Path(directory).resolve()),
                    "adapter": "codex-exec-v1",
                    "attempt_id": "attempt-one",
                    "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                    "status": "delivered",
                    "external_task_id": task_id,
                }), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "external_task_id"):
                    capsule_dispatch.saved_or_new(
                        path, "codex-exec-v1", "attempt-one", capsule, directory,
                    )

    def test_codex_ignores_a_blank_thread_id(self):
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "events.jsonl"
            evidence.write_text(
                '{"type":"thread.started","thread_id":"   "}\n', encoding="utf-8",
            )

            self.assertIsNone(capsule_dispatch.codex_thread_id(evidence))

    def test_rejects_a_receipt_from_an_unknown_schema(self):
        for version in (1, 99):
            self.check_rejected_schema(version)

    def check_rejected_schema(self, version):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": version,
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "delivered",
                "external_task_id": "thread-1",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "schema_version"):
                capsule_dispatch.saved_or_new(
                    path, "codex-exec-v1", "attempt-one", capsule, directory,
                )

    def test_recovery_persists_an_indeterminate_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": 2,
                "workspace": str(Path(directory).resolve()),
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "attempted",
            }), encoding="utf-8")

            recovered = capsule_dispatch.saved_or_new(
                path, "codex-exec-v1", "attempt-one", capsule, directory,
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("indeterminate", recovered["status"])
        self.assertEqual(recovered, persisted)

    def test_rejects_a_terminal_receipt_without_a_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": 2,
                "workspace": str(Path(directory).resolve()),
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "failed",
                "reason": "",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "reason"):
                capsule_dispatch.saved_or_new(
                    path, "codex-exec-v1", "attempt-one", capsule, directory,
                )

    def test_codex_does_not_repeat_an_attempt_that_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            codex = self.executable(
                root, "codex", 'cat >/dev/null\n',
            )
            first = capsule_dispatch.dispatch_codex(
                codex, root, "frozen capsule", root / "receipts", "attempt-one", 0.5,
            )
            with patch.object(capsule_dispatch.subprocess, 'Popen', side_effect=AssertionError('must not replay')):
                second = capsule_dispatch.dispatch_codex(
                    codex, root, "frozen capsule", root / "receipts", "attempt-one", 0.5,
                )

        self.assertEqual("indeterminate", first["status"])
        self.assertEqual(first, second)

    def test_rejects_non_finite_or_non_positive_startup_timeout(self):
        with tempfile.TemporaryDirectory() as directory:
            capsule = Path(directory) / "capsule.md"
            capsule.write_text("frozen capsule", encoding="utf-8")
            for timeout in ("nan", "inf", "-inf", "0"):
                with self.subTest(timeout=timeout), \
                     patch.object(sys, "argv", [
                         str(SCRIPT), "--host", "codex", "--workspace", directory,
                         "--capsule-file", str(capsule), "--receipt-dir", str(Path(directory) / "receipts"),
                         f"--startup-timeout-seconds={timeout}",
                     ]), patch.object(capsule_dispatch, "executable", side_effect=AssertionError), \
                     redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(2, capsule_dispatch.main())
                    self.assertIn("positive finite", error.getvalue())

    def test_claude_snapshots_the_capsule_and_discovers_its_new_named_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "capture"
            launched = root / "launched"
            name = root / "name"
            capsule_file = root / "capsule.md"
            capsule_file.write_text("frozen capsule", encoding="utf-8")
            claude = self.executable(
                root, "claude", f'if [ "$1" = agents ]; then\n'
                                f'  if [ -f "{launched}" ]; then\n'
                                f'    printf \'[{{"id":"background-1","sessionId":"session-1","name":"%s","cwd":"%s"}}]\\n\' "$(cat \"{name}\")" "$PWD"\n'
                                f'  else\n'
                                f'    printf \'[]\\n\'\n'
                                f'  fi\n'
                                f'  exit 0\n'
                                f'fi\n'
                                f'printf "%s\\n" "$@" > "{capture}"\n'
                                f'printf "%s" "$3" > "{name}"\n'
                                f'printf "changed capsule" > "{capsule_file}"\n'
                                f'touch "{launched}"\n',
            )
            result = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )

            command = capture.read_text(encoding="utf-8")
            snapshot = Path(command.splitlines()[4])
            snapshot_text = snapshot.read_text(encoding="utf-8")
            source_text = capsule_file.read_text(encoding="utf-8")

        self.assertEqual("delivered", result["status"])
        self.assertEqual("claude-background-v1", result["adapter"])
        self.assertEqual("session-1", result["external_task_id"])
        self.assertIn("--background", command)
        self.assertIn("--append-system-prompt-file", command)
        self.assertNotIn(str(capsule_file), command)
        self.assertEqual("frozen capsule", snapshot_text)
        self.assertEqual("changed capsule", source_text)

    def test_claude_requires_agents_to_confirm_the_exact_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule_file = root / "capsule.md"
            capsule_file.write_text("frozen capsule", encoding="utf-8")
            launched = root / "launched"
            name = root / "name"
            claude = self.executable(
                root, "claude", f'if [ "$1" = agents ]; then\n'
                                f'  if [ -f "{launched}" ]; then\n'
                                f'    printf \'[]\\n\'\n'
                                f'  else\n'
                                f'    printf \'[]\\n\'\n'
                                f'  fi\n'
                                f'  exit 0\n'
                                f'fi\n'
                                f'printf "%s" "$3" > "{name}"\n'
                                f'touch "{launched}"\n',
            )
            result = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )
            repeated = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )

        self.assertEqual("indeterminate", result["status"])
        self.assertIn("did not confirm", result["reason"])
        self.assertEqual(result, repeated)

    def test_claude_does_not_confirm_a_preexisting_session_without_a_valid_agent_id(self):
        workspace = "/tmp/converge-capsule-dispatch"
        existing = {
            "id": "   ", "name": "converge-attempt", "cwd": workspace,
            "sessionId": "old-session",
        }
        with patch.object(capsule_dispatch, "claude_agents", return_value=[existing]):
            result = capsule_dispatch.claude_session_registered(
                "claude", workspace, "converge-attempt", set(), time.monotonic() + 0.02,
            )

        self.assertFalse(result)

    def test_claude_falls_back_to_its_agent_id_when_session_id_is_blank(self):
        workspace = "/tmp/converge-capsule-dispatch"
        discovered = {
            "id": "agent-1", "name": "converge-attempt", "cwd": workspace,
            "sessionId": "   ",
        }
        with patch.object(capsule_dispatch, "claude_agents", return_value=[discovered]):
            result = capsule_dispatch.claude_session_registered(
                "claude", workspace, "converge-attempt", set(), time.monotonic() + 0.02,
            )

        self.assertEqual("agent-1", result)

    def test_claude_retries_a_transient_agents_query_within_one_total_deadline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            launched = root / "launched"
            queries = root / "queries"
            name = root / "name"
            capsule_file = root / "capsule.md"
            capsule_file.write_text("frozen capsule", encoding="utf-8")
            claude = self.executable(
                root, "claude", f'if [ "$1" = agents ]; then\n'
                                f'  count=0\n'
                                f'  if [ -f "{queries}" ]; then count=$(cat "{queries}"); fi\n'
                                f'  count=$((count + 1))\n'
                                f'  printf "%s" "$count" > "{queries}"\n'
                                f'  if [ "$count" = 2 ]; then exit 1; fi\n'
                                f'  if [ -f "{launched}" ]; then\n'
                                f'    printf \'[{{"id":"background-1","sessionId":"session-1","name":"%s","cwd":"%s"}}]\\n\' "$(cat \"{name}\")" "$PWD"\n'
                                f'  else\n'
                                f'    printf \'[]\\n\'\n'
                                f'  fi\n'
                                f'  exit 0\n'
                                f'fi\n'
                                f'printf "%s" "$3" > "{name}"\n'
                                f'touch "{launched}"\n',
            )
            result = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 5,
            )

        self.assertEqual("delivered", result["status"])

    def test_capability_preflight_rejects_missing_required_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            complete = self.executable(
                root, "complete", 'if [ "$1" = exec ]; then\n'
                                  '  printf "%s\\n" "--json"\n'
                                  'elif [ "$1" = agents ]; then\n'
                                  '  printf "%s\\n" "--json --all --cwd"\n'
                                  'else\n'
                                  '  printf "%s\\n" "--background"\n'
                                  'fi\n',
            )
            incomplete = self.executable(root, "incomplete", 'printf "%s\\n" "no flags"\n')

            self.assertIsNone(capsule_dispatch.capability_error("codex", complete))
            self.assertIsNone(capsule_dispatch.capability_error("claude", complete))
            self.assertIn("--json", capsule_dispatch.capability_error("codex", incomplete))
            self.assertIn("--background", capsule_dispatch.capability_error("claude", incomplete))

    def test_codex_capsule_write_failure_is_not_misreported_as_a_definite_failure(self):
        class Input:
            def write(self, _value):
                raise BrokenPipeError()

            def close(self):
                pass

        class Process:
            stdin = Input()

            def wait(self):
                return 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(capsule_dispatch.subprocess, "Popen", return_value=Process()):
                result = capsule_dispatch.dispatch_codex(
                    "codex", root, "frozen capsule", root / "receipts", "attempt-one", 1,
                )

        self.assertEqual("indeterminate", result["status"])

    def test_codex_empty_os_error_produces_a_valid_failed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(capsule_dispatch.subprocess, "Popen", side_effect=OSError()):
                result = capsule_dispatch.dispatch_codex(
                    "codex", root, "frozen capsule", root / "receipts", "attempt-one", 1,
                )
            persisted = json.loads((root / "receipts" / "attempt-one.json").read_text(encoding="utf-8"))

        self.assertEqual("failed", result["status"])
        self.assertEqual("OSError", result["reason"])
        self.assertEqual(result, persisted)
        capsule_dispatch.validate_saved_receipt(result)

    def test_persist_rejects_an_invalid_receipt_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            receipt = capsule_dispatch.result(
                "codex-exec-v1", "attempt-one", "frozen capsule", "failed", workspace=directory, reason="   ",
            )

            with self.assertRaisesRegex(ValueError, "reason"):
                capsule_dispatch.persist(path, receipt)

            self.assertFalse(path.exists())

    def test_claude_records_a_definite_launch_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule_file = root / "capsule.md"
            capsule_file.write_text("frozen capsule", encoding="utf-8")
            claude = self.executable(
                root, "claude", 'if [ "$1" = agents ]; then\n'
                              '  printf "%s\\n" "[]"\n'
                              '  exit 0\n'
                              'fi\n'
                              'exit 7\n',
            )

            result = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )
            repeated = capsule_dispatch.dispatch_claude(
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
            )

        self.assertEqual("failed", result["status"])
        self.assertEqual(result, repeated)

    def test_missing_host_is_reported_as_unavailable_with_a_reusable_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.md"
            capsule.write_text("frozen capsule", encoding="utf-8")
            first = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex", "--workspace", str(root),
                 "--capsule-file", str(capsule), "--receipt-dir", str(root / "receipts")],
                text=True, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin"},
            )
            second = subprocess.run(
                [sys.executable, str(SCRIPT), "--host", "codex", "--workspace", str(root),
                 "--capsule-file", str(capsule), "--receipt-dir", str(root / "receipts")],
                text=True, capture_output=True, check=False, env={"PATH": "/usr/bin:/bin"},
            )

        self.assertEqual(2, first.returncode)
        self.assertEqual("unavailable", json.loads(first.stdout)["status"])
        self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))

    def test_cli_routes_only_capability_checked_dispatches_and_persists_unavailability(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capsule = root / "capsule.md"
            capsule.write_text("frozen capsule", encoding="utf-8")
            arguments = [
                str(SCRIPT), "--host", "codex", "--workspace", str(root),
                "--capsule-file", str(capsule), "--receipt-dir", str(root / "receipts"),
            ]
            delivered = capsule_dispatch.result(
                "codex-exec-v1", "codex-test", "frozen capsule", "delivered",
                workspace=root, external_task_id="thread-1",
            )
            with patch.object(sys, "argv", arguments + ["--attempt-id", "codex-test"]), \
                    patch.object(capsule_dispatch, "executable", return_value="codex"), \
                    patch.object(capsule_dispatch, "capability_error", return_value=None), \
                    patch.object(capsule_dispatch, "dispatch_codex", return_value=delivered), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(0, capsule_dispatch.main())
            self.assertEqual("thread-1", json.loads(stdout.getvalue())["external_task_id"])

            with patch.object(sys, "argv", arguments + ["--attempt-id", "missing"]), \
                    patch.object(capsule_dispatch, "executable", side_effect=ValueError("codex is not available on PATH")), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(2, capsule_dispatch.main())
            self.assertEqual("unavailable", json.loads(stdout.getvalue())["status"])

            with patch.object(sys, "argv", arguments + ["--attempt-id", "incomplete"]), \
                    patch.object(capsule_dispatch, "executable", return_value="codex"), \
                    patch.object(capsule_dispatch, "capability_error", return_value="missing --json"), \
                    patch("sys.stdout", new_callable=io.StringIO) as stdout:
                self.assertEqual(2, capsule_dispatch.main())
            self.assertEqual("unavailable", json.loads(stdout.getvalue())["status"])


if __name__ == "__main__":
    unittest.main()
