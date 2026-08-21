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
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": False}
        )

        self.assertEqual("automatic", result["mode"])
        self.assertEqual(["dispatch", "query", "wait"], result["capabilities"])
        self.assertNotIn("interrupt", result["capabilities"])

    def test_claude_without_stable_query_downgrades_to_manual(self):
        result = runtime_adapter.negotiate(
            "claude-code", {"dispatch": True, "query": False, "wait": True, "interrupt": True}
        )

        self.assertEqual("manual", result["mode"])
        self.assertEqual([], result["capabilities"])
        self.assertIn("stable query", result["reason"])

    def test_single_context_never_claims_worker_control(self):
        result = runtime_adapter.negotiate(
            "single-context", {"dispatch": True, "query": True, "wait": True, "interrupt": True}
        )

        self.assertEqual("manual", result["mode"])
        self.assertEqual([], result["capabilities"])

    def test_wait_timeout_and_host_status_are_normalized_without_false_terminal_state(self):
        self.assertEqual("working", runtime_adapter.normalize_status("timeout"))
        self.assertEqual("completed", runtime_adapter.normalize_status("done"))
        self.assertEqual("interrupted", runtime_adapter.normalize_status("cancelled"))
        with self.assertRaisesRegex(ValueError, "unknown host status"):
            runtime_adapter.normalize_status("maybe")


if __name__ == "__main__":
    unittest.main()
