import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).with_name("capsule_dispatch.py")
SPEC = importlib.util.spec_from_file_location("capsule_dispatch", SCRIPT)
capsule_dispatch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capsule_dispatch)


class CapsuleDispatchTest(unittest.TestCase):
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

    def test_rejects_a_delivered_receipt_without_a_task_id(self):
        for task_id in (None, ""):
            with self.subTest(task_id=task_id), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "attempt-one.json"
                capsule = "frozen capsule"
                path.write_text(json.dumps({
                    "schema_version": 1,
                    "adapter": "codex-exec-v1",
                    "attempt_id": "attempt-one",
                    "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                    "status": "delivered",
                    "external_task_id": task_id,
                }), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "external_task_id"):
                    capsule_dispatch.saved_or_new(
                        path, "codex-exec-v1", "attempt-one", capsule,
                    )

    def test_rejects_a_receipt_from_an_unknown_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": 2,
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "delivered",
                "external_task_id": "thread-1",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "schema_version"):
                capsule_dispatch.saved_or_new(
                    path, "codex-exec-v1", "attempt-one", capsule,
                )

    def test_recovery_persists_an_indeterminate_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": 1,
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "attempted",
            }), encoding="utf-8")

            recovered = capsule_dispatch.saved_or_new(
                path, "codex-exec-v1", "attempt-one", capsule,
            )
            persisted = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual("indeterminate", recovered["status"])
        self.assertEqual(recovered, persisted)

    def test_rejects_a_terminal_receipt_without_a_reason(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "attempt-one.json"
            capsule = "frozen capsule"
            path.write_text(json.dumps({
                "schema_version": 1,
                "adapter": "codex-exec-v1",
                "attempt_id": "attempt-one",
                "capsule_fingerprint": capsule_dispatch.fingerprint(capsule),
                "status": "failed",
                "reason": "",
            }), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "reason"):
                capsule_dispatch.saved_or_new(
                    path, "codex-exec-v1", "attempt-one", capsule,
                )

    def test_codex_does_not_repeat_an_attempt_that_cannot_be_confirmed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            capture = root / "calls"
            codex = self.executable(
                root, "codex", f'echo call >> "{capture}"\ncat >/dev/null\n',
            )
            first = capsule_dispatch.dispatch_codex(
                codex, root, "frozen capsule", root / "receipts", "attempt-one", 0.5,
            )
            deadline = time.monotonic() + 0.5
            while not capture.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(capture.exists(), "Codex process did not start within the test deadline")
            second = capsule_dispatch.dispatch_codex(
                codex, root, "frozen capsule", root / "receipts", "attempt-one", 0.5,
            )
            calls = capture.read_text(encoding="utf-8").splitlines()

        self.assertEqual("indeterminate", first["status"])
        self.assertEqual(first, second)
        self.assertEqual(["call"], calls)

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
                claude, root, "frozen capsule", root / "receipts", "attempt-one", 1,
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


if __name__ == "__main__":
    unittest.main()
