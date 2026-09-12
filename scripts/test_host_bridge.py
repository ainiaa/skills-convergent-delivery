import tempfile
import unittest
from pathlib import Path

import host_bridge


FINGERPRINT = "a" * 64
HOST_FINGERPRINT = "b" * 64


class HostBridgeTest(unittest.TestCase):
    def package(self, workspace):
        return host_bridge.package(
            host="codex", sample_id="known_acceptance:roots", workspace=workspace,
            prompt="Run the frozen evaluator task.", judge_argv=["python3", "judge.py"],
            launch_fingerprint=FINGERPRINT, host_fingerprint=HOST_FINGERPRINT,
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


if __name__ == "__main__":
    unittest.main()
