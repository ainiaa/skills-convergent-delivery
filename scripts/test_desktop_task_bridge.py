import unittest

import desktop_task_bridge
from worker_profile import fingerprint


def profile(**overrides):
    value = {
        "schema_version": 1,
        "worker_id": "implementer-1",
        "role": "implementer",
        "runner_id": "codex-exec-v1",
        "requested": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
        "effective": {
            "provider": "openai", "model": "gpt-5.6-luna", "reasoning_effort": "high",
        },
        "permissions": {"workspace": "write", "shell": True, "network": "egress"},
        "budget": {"max_turns": 4, "timeout_seconds": 1800, "max_output_chars": 48000},
    }
    value.update(overrides)
    if "profile_fingerprint" not in overrides:
        value["profile_fingerprint"] = fingerprint(value)
    return value


class DesktopTaskBridgeTest(unittest.TestCase):
    def test_create_action_freezes_the_exact_requested_model_and_effort(self):
        action = desktop_task_bridge.create_action(
            profile(), "Implement the frozen task.", project_id="project-1", title="Bridge task",
        )

        self.assertEqual("desktop-task-v1", action["adapter"])
        self.assertEqual("requested", action["model_binding"]["status"])
        self.assertEqual(profile()["profile_fingerprint"], action["model_binding"]["profile_fingerprint"])
        self.assertEqual("gpt-5.6-luna", action["arguments"]["model"])
        self.assertEqual("high", action["arguments"]["thinking"])
        self.assertEqual(
            {"type": "project", "projectId": "project-1", "environment": {"type": "worktree"}},
            action["arguments"]["target"],
        )

    def test_create_rejects_non_implementer_or_model_substitution(self):
        reviewer = profile(
            role="reviewer", permissions={"workspace": "read", "shell": False, "network": "egress"},
        )
        with self.assertRaisesRegex(ValueError, "implementer"):
            desktop_task_bridge.create_action(reviewer, "prompt", project_id="project-1", title="Bridge")

        substituted = profile(effective={
            "provider": "openai", "model": "gpt-5.6-terra", "reasoning_effort": "high",
        })
        with self.assertRaisesRegex(ValueError, "substitution"):
            desktop_task_bridge.create_action(substituted, "prompt", project_id="project-1", title="Bridge")

        tampered = profile(profile_fingerprint="not-the-profile-fingerprint")
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            desktop_task_bridge.create_action(tampered, "prompt", project_id="project-1", title="Bridge")

    def test_only_a_resolved_thread_id_confirms_creation(self):
        action = desktop_task_bridge.create_action(
            profile(), "prompt", project_id="project-1", title="Bridge",
        )

        delivered = desktop_task_bridge.creation_receipt(action, {"threadId": "thread-1", "hostId": "local"})
        indeterminate = desktop_task_bridge.creation_receipt(action, {"clientThreadId": "client-1"})

        self.assertEqual("delivered", delivered["status"])
        self.assertEqual("thread-1", delivered["task_ref"]["thread_id"])
        self.assertEqual("indeterminate", indeterminate["status"])
        self.assertNotIn("task_ref", indeterminate)

    def test_query_and_cleanup_require_an_attested_terminal_host_observation(self):
        action = desktop_task_bridge.create_action(
            profile(), "prompt", project_id="project-1", title="Bridge",
        )
        receipt = desktop_task_bridge.creation_receipt(action, {"threadId": "thread-1", "hostId": "local"})

        query = desktop_task_bridge.query_action(receipt, timeout_ms=60_000)
        self.assertEqual(
            {"targets": [{"threadId": "thread-1", "hostId": "local"}], "timeoutMs": 60_000},
            query["arguments"],
        )
        with self.assertRaisesRegex(ValueError, "terminal"):
            desktop_task_bridge.archive_action(receipt, "working")
        with self.assertRaisesRegex(ValueError, "observation"):
            desktop_task_bridge.archive_action(receipt, "completed")

        observation = desktop_task_bridge.terminal_observation(
            receipt, query,
            {"tool": "wait_threads", "status": "completed",
             "task_ref": {"thread_id": "thread-1", "host_id": "local"}},
        )
        archive = desktop_task_bridge.archive_action(receipt, observation)
        self.assertEqual(
            {"threadId": "thread-1", "hostId": "local", "archived": True}, archive["arguments"],
        )

        with self.assertRaisesRegex(ValueError, "observation"):
            desktop_task_bridge.terminal_observation(
                receipt, query,
                {"tool": "wait_threads", "status": "completed", "task_ref": {"thread_id": "other"}},
            )


if __name__ == "__main__":
    unittest.main()
