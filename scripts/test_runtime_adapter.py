import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("runtime_adapter.py")
SPEC = importlib.util.spec_from_file_location("runtime_adapter", MODULE_PATH)
runtime_adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_adapter)


class RuntimeAdapterTest(unittest.TestCase):
    def test_codex_negotiates_only_controller_attested_supported_capabilities(self):
        result = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "activity_query": True,
                      "process_query": True, "wait": True, "interrupt": True,
                      "resume": True, "tree_query": True, "restrict_dispatch": False}
        )

        self.assertEqual("automatic", result["mode"])
        self.assertEqual(4, result["schema_version"])
        self.assertEqual("controller_attested", result["evidence_level"])
        self.assertEqual(["dispatch", "query", "wait", "interrupt", "tree_query"], result["capabilities"])
        self.assertNotIn("activity_query", result["capabilities"])
        self.assertNotIn("process_query", result["capabilities"])
        self.assertNotIn("resume", result["capabilities"])
        self.assertIsNone(result["capability_observation_fingerprint"])
        self.assertIsNone(result["capability_observation"])
        self.assertEqual(64, len(result["binding_fingerprint"]))

    def test_only_trusted_local_hosts_allow_controller_attested_worker_lifecycle(self):
        codex = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )
        claude = runtime_adapter.negotiate(
            "claude-code", {"dispatch": True, "query": True, "tree_query": True}
        )

        self.assertTrue(runtime_adapter.allows_worker_lifecycle(codex))
        self.assertTrue(runtime_adapter.allows_worker_lifecycle(claude))

    def test_only_a_bound_host_capability_observation_can_enable_auto_watchdog(self):
        controller_attested = runtime_adapter.negotiate(
            "claude-code", {
                "dispatch": True, "query": True, "activity_query": True,
                "process_query": True, "wait": True, "interrupt": True,
                "resume": True, "tree_query": True,
            },
        )
        observation = {
            "query_id": "capabilities-123",
            "observed_at": "2026-08-25T00:00:00Z",
            "profile": "claude-code",
            "capabilities": [
                "dispatch", "query", "activity_query", "process_query", "wait",
                "interrupt", "resume", "tree_query",
            ],
        }
        host_observed = runtime_adapter.bind_observed("claude-code", observation)

        self.assertEqual("terminal-only", runtime_adapter.watchdog_mode(controller_attested))
        self.assertEqual("host_observed", host_observed["evidence_level"])
        self.assertEqual("observed", runtime_adapter.watchdog_mode(host_observed))
        self.assertEqual(64, len(host_observed["capability_observation_fingerprint"]))
        self.assertEqual(observation, host_observed["capability_observation"])

    def test_generic_bind_cannot_construct_a_host_observed_runtime_binding(self):
        with self.assertRaises(TypeError):
            runtime_adapter.bind(
                "claude-code", "automatic", ["dispatch", "query", "tree_query"], "forged",
                evidence_level="host_observed",
            )

    def test_cleanup_receipt_only_becomes_host_observed_with_bound_host_observation(self):
        binding = runtime_adapter.bind_observed("codex", {
            "query_id": "capabilities-123", "observed_at": "2026-08-21T00:00:00Z",
            "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
        })

        observation = {
            "query_id": "query-123",
            "observed_at": "2026-08-21T00:00:00Z",
            "registered_refs": ["worker-1"],
            "active_refs": [],
            "unexpected_refs": [],
        }
        receipt = runtime_adapter.cleanup_receipt(
            binding, 3, ["worker-1"], [], [], "2026-08-21T00:00:00Z",
            host_observation=observation,
        )

        self.assertEqual("tree_query", receipt["mode"])
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual("host_observed", receipt["evidence_level"])
        self.assertEqual(64, len(receipt["observation_fingerprint"]))
        self.assertEqual(binding["binding_fingerprint"], receipt["runtime_fingerprint"])
        self.assertEqual(3, receipt["observed_revision"])

    def test_controller_attested_binding_cannot_claim_a_host_observed_cleanup(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        with self.assertRaisesRegex(ValueError, "host-observed runtime binding"):
            runtime_adapter.cleanup_receipt(
                binding, 1, [], [], [], "2026-08-21T00:00:00Z",
                host_observation={
                    "query_id": "query-123", "observed_at": "2026-08-21T00:00:00Z",
                    "registered_refs": [], "active_refs": [], "unexpected_refs": [],
                },
            )

    def test_cleanup_receipt_rejects_a_forged_runtime_binding(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )
        binding["capabilities"] = ["dispatch", "query", "restrict_dispatch"]

        with self.assertRaisesRegex(ValueError, "fingerprint"):
            runtime_adapter.cleanup_receipt(
                binding, 1, [], [], [], "2026-08-21T00:00:00Z"
            )

    def test_single_context_cannot_forge_automatic_worker_control(self):
        binding = runtime_adapter.bind(
            "single-context", "automatic", ["dispatch", "query", "tree_query"], "forged"
        )
        with self.assertRaisesRegex(ValueError, "single-context"):
            runtime_adapter.validate_binding(binding)

    def test_claude_without_stable_query_downgrades_to_manual(self):
        result = runtime_adapter.negotiate(
            "claude-code", {"dispatch": True, "query": False, "wait": True, "interrupt": True,
                            "tree_query": False, "restrict_dispatch": True}
        )

        self.assertEqual("manual", result["mode"])
        self.assertEqual([], result["capabilities"])
        self.assertIn("stable query", result["reason"])

    def test_single_context_never_claims_worker_control(self):
        result = runtime_adapter.negotiate(
            "single-context", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                               "tree_query": True, "restrict_dispatch": True}
        )

        self.assertEqual("manual", result["mode"])
        self.assertEqual([], result["capabilities"])

    def test_automatic_workers_require_leaf_enforcement_or_subtree_visibility(self):
        result = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                      "tree_query": False, "restrict_dispatch": False}
        )

        self.assertEqual("manual", result["mode"])
        self.assertIn("subtree", result["reason"])

    def test_restrict_dispatch_cleanup_is_controller_attested_not_verified(self):
        binding = runtime_adapter.negotiate(
            "claude-code", {
                "dispatch": True, "query": True, "wait": True, "interrupt": True,
                "tree_query": False, "restrict_dispatch": True,
            }
        )

        receipt = runtime_adapter.cleanup_receipt(
            binding, 3, ["worker-1"], [], [], "2026-08-21T00:00:00Z"
        )

        self.assertEqual("restrict_dispatch", receipt["mode"])
        self.assertEqual("controller_attested", receipt["evidence_level"])
        self.assertIsNone(receipt["observation_fingerprint"])

    def test_tree_query_arguments_alone_are_controller_attested(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        receipt = runtime_adapter.cleanup_receipt(
            binding, 1, [], [], [], "2026-08-21T00:00:00Z"
        )

        self.assertEqual("controller_attested", receipt["evidence_level"])
        self.assertIsNone(receipt["observation_fingerprint"])

    def test_cleanup_receipt_requires_a_real_timestamp(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        with self.assertRaisesRegex(ValueError, "timestamp"):
            runtime_adapter.cleanup_receipt(
                binding, 1, [], [], [], "caller-claims-this-is-host-observed"
            )

    def test_wait_timeout_and_host_status_are_normalized_without_false_terminal_state(self):
        self.assertEqual("working", runtime_adapter.normalize_status("timeout"))
        self.assertEqual("completed", runtime_adapter.normalize_status("done"))
        self.assertEqual("interrupted", runtime_adapter.normalize_status("cancelled"))
        with self.assertRaisesRegex(ValueError, "unknown host status"):
            runtime_adapter.normalize_status("maybe")

    def test_terminal_only_waiting_cannot_trigger_an_automatic_watchdog_interrupt(self):
        binding = runtime_adapter.negotiate(
            "codex", {
                "dispatch": True, "query": True, "wait": True, "interrupt": True,
                "tree_query": True, "restrict_dispatch": False,
            }
        )

        self.assertEqual("terminal-only", runtime_adapter.watchdog_mode(binding))
        self.assertFalse(runtime_adapter.can_auto_watchdog(binding))
        for _ in range(2):
            self.assertEqual(
                {"action": "wait", "task_id": "task-1", "worker_ref": "worker-1"},
                runtime_adapter.watchdog_action(
                    binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=True,
                    activity_observed=None, process_running=None, soft_probe_complete=False,
                ),
            )
        self.assertEqual(
            {"action": "interrupt", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=False,
                activity_observed=None, process_running=None, soft_probe_complete=False, user_stop=True,
            ),
        )

    def test_only_observable_and_recoverable_workers_allow_automatic_watchdog(self):
        binding = runtime_adapter.bind_observed("claude-code", {
            "query_id": "capabilities-456", "observed_at": "2026-08-25T00:00:00Z",
            "profile": "claude-code",
            "capabilities": [
                "dispatch", "query", "activity_query", "process_query", "wait",
                "interrupt", "resume", "restrict_dispatch",
            ],
        })

        self.assertEqual("observed", runtime_adapter.watchdog_mode(binding))
        self.assertTrue(runtime_adapter.can_auto_watchdog(binding))
        self.assertEqual(
            {"action": "query", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=True,
                activity_observed=False, process_running=False, soft_probe_complete=False,
            ),
        )
        self.assertEqual(
            {"action": "interrupt", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=True,
                activity_observed=False, process_running=False, soft_probe_complete=True,
            ),
        )
        self.assertEqual(
            {"action": "wait", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=True,
                activity_observed=True, process_running=False, soft_probe_complete=True,
            ),
        )
        self.assertEqual(
            {"action": "wait", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=True,
                activity_observed=False, process_running=True, soft_probe_complete=True,
            ),
        )

    def test_watchdog_falls_back_to_query_when_wait_is_not_supported(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        self.assertEqual(
            {"action": "query", "task_id": "task-1", "worker_ref": "worker-1"},
            runtime_adapter.watchdog_action(
                binding, task_id="task-1", worker_ref="worker-1", wait_timed_out=False,
                activity_observed=None, process_running=None, soft_probe_complete=False,
            ),
        )


if __name__ == "__main__":
    unittest.main()
