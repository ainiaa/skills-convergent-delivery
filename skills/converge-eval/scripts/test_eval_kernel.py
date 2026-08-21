#!/usr/bin/env python3
"""Executable tests for deterministic evaluation bookkeeping."""

import hashlib
import json
import unittest
from pathlib import Path

from eval_contract import evaluate


ROOT = Path(__file__).resolve().parents[3]


def sample(scenario_id, scenario_class, result="pass", worker_ref="worker-1", **overrides):
    value = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "scenario_class": scenario_class,
        "control_source": "control",
        "candidate_source": "candidate",
        "judge_fingerprint": "a" * 64,
        "worker_ref": worker_ref,
        "evidence_source": f"artifacts/{worker_ref}/{scenario_id}.json",
        "control_result": "pass",
        "candidate_result": result,
    }
    value.update(overrides)
    value["receipt_fingerprint"] = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


class EvalKernelTest(unittest.TestCase):
    def test_selects_all_matching_history_and_computes_distribution(self):
        request = {
            "acceptance": ["worker lifecycle closes"],
            "touched_control_surfaces": ["worker.lifecycle", "batch.capsule"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["scripts"],
            "critical_decisions": ["worker ownership"],
            "sample_receipts": [
                *[
                    sample("worker lifecycle closes", "known_acceptance", worker_ref=f"worker-{n}")
                    for n in range(1, 4)
                ],
                *[
                    sample(
                        "worker-receipt-before-host-terminal", "history",
                        "fail" if n == 1 else "pass", f"worker-{n}",
                    )
                    for n in range(1, 4)
                ],
                *[
                    sample(
                        "batch-capsule-recursive-planning-escape", "history",
                        worker_ref=f"worker-{n}",
                    )
                    for n in range(1, 4)
                ],
                sample("new-worker-probe", "exploration", worker_ref="worker-4"),
            ],
            "revisions": [{
                "before_failing_samples": 2, "after_failing_samples": 1,
                "before_variance": 0.25, "after_variance": 0.2,
            }],
        }

        result = evaluate(request, ROOT / "references/evaluation-catalog.json")

        self.assertEqual(10, result["sample_distribution"]["sample_count"])
        self.assertEqual(9, result["sample_distribution"]["pass_count"])
        self.assertEqual(9 / 10, result["sample_distribution"]["pass_rate"])
        self.assertEqual(["new-worker-probe"], result["exploration"])
        self.assertEqual([], result["uncovered"])
        self.assertEqual(
            {
                "batch-capsule-recursive-planning-escape",
                "worker-receipt-before-host-terminal",
            },
            {item["id"] for item in result["history"]},
        )

    def test_stops_after_one_revision_without_improvement(self):
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [sample("contract", "known_acceptance", "fail")],
            "revisions": [{
                "before_failing_samples": 1, "after_failing_samples": 1,
                "before_variance": 0.0, "after_variance": 0.0,
            }],
        }

        result = evaluate(request, ROOT / "references/evaluation-catalog.json")

        self.assertEqual("no_improvement", result["stop_reason"])
        self.assertEqual(1, result["revisions_used"])

    def test_rejects_legacy_caller_asserted_samples(self):
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "samples": ["pass"],
            "revisions": [],
        }

        with self.assertRaisesRegex(ValueError, "fields"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")

    def test_reports_missing_required_scenarios_as_uncovered(self):
        request = {
            "acceptance": ["contract", "cleanup"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [sample("contract", "known_acceptance")],
            "revisions": [],
        }

        result = evaluate(request, ROOT / "references/evaluation-catalog.json")

        self.assertEqual(["known_acceptance:cleanup"], result["uncovered"])
        self.assertEqual("evidence_gap", result["stop_reason"])

    def test_rejects_tampered_sample_receipt(self):
        receipt = sample("contract", "known_acceptance")
        receipt["candidate_result"] = "fail"
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [receipt],
            "revisions": [],
        }

        with self.assertRaisesRegex(ValueError, "fingerprint"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")

    def test_rejects_receipts_from_another_source_or_judge(self):
        base = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "revisions": [],
        }
        with self.assertRaisesRegex(ValueError, "source"):
            evaluate({
                **base,
                "sample_receipts": [sample(
                    "contract", "known_acceptance", candidate_source="another-candidate"
                )],
            }, ROOT / "references/evaluation-catalog.json")

        with self.assertRaisesRegex(ValueError, "frozen judge"):
            evaluate({
                **base,
                "sample_receipts": [
                    sample("contract", "known_acceptance", worker_ref="worker-1"),
                    sample(
                        "probe", "exploration", worker_ref="worker-2",
                        judge_fingerprint="b" * 64,
                    ),
                ],
            }, ROOT / "references/evaluation-catalog.json")

    def test_wrong_scenario_class_cannot_cover_required_acceptance(self):
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [sample("contract", "history")],
            "revisions": [],
        }

        result = evaluate(request, ROOT / "references/evaluation-catalog.json")

        self.assertEqual(["known_acceptance:contract"], result["uncovered"])

    def test_critical_sampling_requires_fresh_workers_for_each_required_scenario(self):
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": ["review routing"],
            "sample_receipts": [
                sample("contract", "known_acceptance", worker_ref="worker-1"),
                sample("probe-a", "exploration", worker_ref="worker-2"),
                sample("probe-b", "exploration", worker_ref="worker-3"),
            ],
            "revisions": [],
        }

        with self.assertRaisesRegex(ValueError, "known_acceptance:contract.*3 fresh"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")


if __name__ == "__main__":
    unittest.main()
