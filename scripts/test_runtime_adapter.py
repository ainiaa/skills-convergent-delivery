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

    def test_worker_lifecycle_is_disabled_without_a_concrete_host_bridge(self):
        codex = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )
        claude = runtime_adapter.negotiate(
            "claude-code", {"dispatch": True, "query": True, "tree_query": True}
        )

        self.assertFalse(runtime_adapter.allows_worker_lifecycle(codex))
        self.assertFalse(runtime_adapter.allows_worker_lifecycle(claude))
        self.assertFalse(runtime_adapter.allows_worker_lifecycle(codex, cross_session=True))
        self.assertFalse(runtime_adapter.allows_worker_lifecycle(claude, cross_session=True))

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.bind_observed("codex", {
                "query_id": "capabilities-123", "observed_at": "2026-08-21T00:00:00Z",
                "profile": "codex", "capabilities": ["dispatch", "query", "tree_query"],
            })

    def test_same_session_native_worker_boundary_does_not_authorize_cross_session_fallback(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "tree_query": True}
        )

        self.assertFalse(runtime_adapter.allows_worker_lifecycle(binding))
        self.assertFalse(runtime_adapter.allows_worker_lifecycle(binding, cross_session=True))
        self.assertEqual("terminal-only", runtime_adapter.watchdog_mode(binding))

    def test_codex_requires_tree_visibility_and_never_claims_restrict_dispatch(self):
        result = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "restrict_dispatch": True}
        )

        self.assertEqual("manual", result["mode"])
        self.assertEqual([], result["capabilities"])
        self.assertIn("tree", result["reason"])

    def test_public_observation_input_cannot_enable_an_auto_watchdog(self):
        observation = {
            "query_id": "capabilities-123",
            "observed_at": "2026-08-25T00:00:00Z",
            "profile": "claude-code",
            "capabilities": [
                "dispatch", "query", "activity_query", "process_query", "wait",
                "interrupt", "resume", "tree_query",
            ],
        }
        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.bind_observed("claude-code", observation)

    def test_generic_bind_cannot_construct_a_host_observed_runtime_binding(self):
        with self.assertRaises(TypeError):
            runtime_adapter.bind(
                "claude-code", "automatic", ["dispatch", "query", "tree_query"], "forged",
                evidence_level="host_observed",
            )

    def test_legacy_runtime_binding_schemas_are_rejected(self):
        current = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )
        for schema_version in (1, 2, 3):
            with self.subTest(schema_version=schema_version):
                binding = dict(current)
                binding["schema_version"] = schema_version
                with self.assertRaisesRegex(ValueError, "schema_version must be 4"):
                    runtime_adapter.validate_binding(binding)

    def test_public_observation_input_cannot_mint_a_cleanup_receipt(self):
        observation = {
            "query_id": "capabilities-123", "observed_at": "2026-08-21T00:00:00Z",
            "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
        }
        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.bind_observed("codex", observation)

    def test_controller_attested_binding_cannot_claim_a_host_observed_cleanup(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
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

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
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

    def test_cleanup_requires_a_bound_tree_query_observation(self):
        binding = runtime_adapter.negotiate(
            "claude-code", {
                "dispatch": True, "query": True, "wait": True, "interrupt": True,
                "tree_query": False, "restrict_dispatch": True,
            }
        )

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.cleanup_receipt(
                binding, 3, ["worker-1"], [], [], "2026-08-21T00:00:00Z"
            )

    def test_tree_query_arguments_alone_cannot_clear_workers(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.cleanup_receipt(
                binding, 1, [], [], [], "2026-08-21T00:00:00Z"
            )

    def test_cleanup_receipt_requires_a_real_timestamp(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "tree_query": True}
        )

        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
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

    def test_public_observation_input_cannot_enable_recovery(self):
        observation = {
            "query_id": "capabilities-456", "observed_at": "2026-08-25T00:00:00Z",
            "profile": "claude-code",
            "capabilities": [
                "dispatch", "query", "activity_query", "process_query", "wait",
                "interrupt", "resume", "restrict_dispatch",
            ],
        }
        with self.assertRaisesRegex(ValueError, "concrete host bridge"):
            runtime_adapter.bind_observed("claude-code", observation)

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
