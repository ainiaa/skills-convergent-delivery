import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("runtime_adapter.py")
SPEC = importlib.util.spec_from_file_location("runtime_adapter", MODULE_PATH)
runtime_adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_adapter)


class RuntimeAdapterTest(unittest.TestCase):
    def test_codex_negotiates_only_observed_capabilities(self):
        result = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": False,
                      "tree_query": True, "restrict_dispatch": False}
        )

        self.assertEqual("automatic", result["mode"])
        self.assertEqual(["dispatch", "query", "wait", "tree_query"], result["capabilities"])
        self.assertNotIn("interrupt", result["capabilities"])
        self.assertEqual(64, len(result["binding_fingerprint"]))

    def test_cleanup_receipt_is_derived_from_the_frozen_runtime_binding(self):
        binding = runtime_adapter.negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                      "tree_query": True, "restrict_dispatch": False}
        )

        receipt = runtime_adapter.cleanup_receipt(
            binding, 3, ["worker-1"], [], [], "2026-08-21T00:00:00Z"
        )

        self.assertEqual("tree_query", receipt["mode"])
        self.assertEqual(binding["binding_fingerprint"], receipt["runtime_fingerprint"])
        self.assertEqual(3, receipt["observed_revision"])

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

    def test_wait_timeout_and_host_status_are_normalized_without_false_terminal_state(self):
        self.assertEqual("working", runtime_adapter.normalize_status("timeout"))
        self.assertEqual("completed", runtime_adapter.normalize_status("done"))
        self.assertEqual("interrupted", runtime_adapter.normalize_status("cancelled"))
        with self.assertRaisesRegex(ValueError, "unknown host status"):
            runtime_adapter.normalize_status("maybe")


if __name__ == "__main__":
    unittest.main()
