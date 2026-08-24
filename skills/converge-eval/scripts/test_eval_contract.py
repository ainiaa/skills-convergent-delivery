#!/usr/bin/env python3
"""Contract tests for bounded differential Converge behavior evaluation."""

import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "skills/converge-eval/SKILL.md"
CONTRACT = ROOT / "skills/converge-eval/references/evaluation-contract.json"
CATALOG = ROOT / "references/evaluation-catalog.json"


class EvaluationContractTest(unittest.TestCase):
    def setUp(self):
        self.skill = SKILL.read_text(encoding="utf-8")
        self.contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        self.catalog = json.loads(CATALOG.read_text(encoding="utf-8"))

    def test_self_modification_freezes_control_and_compares_candidate(self):
        differential = self.contract["differential"]
        self.assertEqual(["control", "candidate"], differential["variants"])
        self.assertTrue(differential["freeze_control_before_candidate"])
        self.assertTrue(differential["same_scenarios_and_judging"])
        self.assertIn("self-modification", differential["required_for"])
        locked = self.contract["locked_surface"]
        self.assertFalse(locked["candidate_may_modify"])
        self.assertIn("evaluator_fingerprint", locked["result_fingerprints"])
        self.assertIn("worker_state_fingerprint", locked["result_fingerprints"])
        self.assertIn("state_validator_fingerprint", locked["result_fingerprints"])
        self.assertIn("worker_state_source", self.contract["required_inputs"])
        self.assertNotIn("worker_registry", self.contract["required_inputs"])
        bootstrap = self.contract["bootstrap"]
        self.assertEqual(9, bootstrap["only_from_protocol"])
        self.assertEqual(10, bootstrap["only_to_protocol"])
        self.assertFalse(bootstrap["may_claim_locked_evaluation"])

    def test_critical_decisions_require_fresh_samples_and_statistics(self):
        sampling = self.contract["sampling"]
        self.assertEqual(1, sampling["default_fresh_samples"])
        self.assertGreaterEqual(sampling["critical_min_fresh_samples"], 2)
        self.assertTrue(sampling["fresh_context_per_sample"])
        self.assertEqual(
            ["sample_count", "pass_count", "fail_count", "pass_rate", "variance"],
            sampling["report_fields"],
        )
        self.assertFalse(sampling["single_pass_establishes_stability"])
        receipt = sampling["receipt_schema"]
        self.assertEqual(3, receipt["schema_version"])
        self.assertIn("evidence_fingerprint", receipt["required_fields"])
        self.assertIn("worker_observation_fingerprint", receipt["required_fields"])
        self.assertIn("touched_paths", receipt["required_fields"])

    def test_exploration_is_reported_separately_and_is_not_a_completion_gate(self):
        self.assertFalse(self.contract["exploration"]["gating"])
        self.assertIn("exploration_distribution", self.contract["result_required_fields"])
        self.assertIn("differential", self.contract["result_required_fields"])

    def test_catalog_selects_every_historical_escape_touching_a_control_surface(self):
        entries = self.catalog["escaped_defects"]
        self.assertGreaterEqual(len(entries), 3)
        for entry in entries:
            self.assertTrue(entry["id"])
            self.assertTrue(entry["control_surfaces"])
            self.assertTrue(entry["source"].startswith("docs/04_testing/defects/"))
            self.assertTrue(entry["scenario"])

        touched = {"batch.capsule", "worker.lifecycle"}
        selected = {
            entry["id"]
            for entry in entries
            if touched.intersection(entry["control_surfaces"])
        }
        self.assertEqual(
            {
                "batch-capsule-recursive-planning-escape",
                "worker-receipt-before-host-terminal",
            },
            selected,
        )

    def test_every_defect_document_contributes_a_historical_scenario(self):
        documented = {
            str(path.relative_to(ROOT))
            for path in (ROOT / "docs/04_testing/defects").glob("*.md")
        }
        catalogued = {entry["source"] for entry in self.catalog["escaped_defects"]}

        self.assertEqual(set(), documented - catalogued)

    def test_result_classes_are_explicit_and_non_overlapping(self):
        self.assertEqual(
            ["known_acceptance", "history", "exploration", "uncovered"],
            self.contract["result_classes"],
        )

    def test_revision_loop_is_bounded_and_escalates_on_first_no_improvement(self):
        revision = self.contract["revision"]
        self.assertEqual(3, revision["max_rule_revisions"])
        self.assertEqual(1, revision["stop_after_consecutive_no_improvement"])
        self.assertEqual("escalate", revision["on_stop"])

    def test_evaluator_never_executes_external_side_effects_directly(self):
        effects = self.contract["side_effects"]
        self.assertFalse(effects["direct_external_side_effects"])
        self.assertEqual(
            ["read_only", "isolated_temporary_workspace"], effects["allowed"]
        )
        self.assertIn("不得直接执行外部副作用", self.skill)


if __name__ == "__main__":
    unittest.main()
