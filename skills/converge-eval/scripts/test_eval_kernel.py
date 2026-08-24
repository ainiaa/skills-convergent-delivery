#!/usr/bin/env python3
"""Executable tests for deterministic evaluation bookkeeping."""

import hashlib
import itertools
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from eval_contract import evaluate


ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = tempfile.TemporaryDirectory()
unittest.addModuleCleanup(ARTIFACTS.cleanup)
ARTIFACT_SEQUENCE = itertools.count(1)
CONTROL_COMMIT = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD^"], check=True,
    capture_output=True, text=True,
).stdout.strip()
CANDIDATE_COMMIT = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
    capture_output=True, text=True,
).stdout.strip()
JUDGE_SOURCE = ROOT / "skills/converge-eval/references/evaluation-contract.json"
JUDGE_FINGERPRINT = hashlib.sha256(JUDGE_SOURCE.read_bytes()).hexdigest()


def sample(scenario_id, scenario_class, result="pass", worker_ref="worker-1", **overrides):
    value = {
        "schema_version": 3,
        "scenario_id": scenario_id,
        "scenario_class": scenario_class,
        "control_source": CONTROL_COMMIT,
        "candidate_source": CANDIDATE_COMMIT,
        "judge_fingerprint": JUDGE_FINGERPRINT,
        "worker_ref": worker_ref,
        "worker_observation_fingerprint": hashlib.sha256(worker_ref.encode()).hexdigest(),
        "touched_paths": [],
        "control_result": "pass",
        "candidate_result": result,
    }
    value.update(overrides)
    artifact = Path(ARTIFACTS.name) / f"{next(ARTIFACT_SEQUENCE)}.json"
    artifact.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    value["evidence_source"] = str(artifact)
    value["evidence_fingerprint"] = hashlib.sha256(artifact.read_bytes()).hexdigest()
    value["receipt_fingerprint"] = hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return value


def secure(request):
    request = dict(request)
    if request.get("control_source") == "control":
        request["control_source"] = CONTROL_COMMIT
    if request.get("candidate_source") == "candidate":
        request["candidate_source"] = CANDIDATE_COMMIT
    request["judge_source"] = str(JUDGE_SOURCE)
    request["worker_registry"] = [
        {
            "ref": ref,
            "status": "completed",
            "evidence_level": "host_observed",
            "observation_fingerprint": hashlib.sha256(ref.encode()).hexdigest(),
        }
        for ref in sorted({item["worker_ref"] for item in request.get("sample_receipts", [])})
    ]
    return request


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

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

        self.assertEqual(10, result["sample_distribution"]["sample_count"])
        self.assertEqual(9, result["sample_distribution"]["pass_count"])
        self.assertEqual(9 / 10, result["sample_distribution"]["pass_rate"])
        self.assertEqual(8 / 9, result["gating_distribution"]["pass_rate"])
        self.assertEqual("failed", result["stop_reason"])
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

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

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
            evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

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

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

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
            evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

    def test_rejects_evidence_changed_after_the_receipt_was_created(self):
        receipt = sample("contract", "known_acceptance")
        Path(receipt["evidence_source"]).write_text("tampered", encoding="utf-8")
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

        with self.assertRaisesRegex(ValueError, "evidence fingerprint"):
            evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

    def test_evidence_artifact_must_bind_the_claimed_worker_and_results(self):
        receipt = sample("contract", "known_acceptance")
        receipt["worker_ref"] = "forged-worker"
        receipt["receipt_fingerprint"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in receipt.items() if key != "receipt_fingerprint"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()
        ).hexdigest()
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

        with self.assertRaisesRegex(ValueError, "worker|evidence identity"):
            evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

    def test_control_and_candidate_results_are_classified_differentially(self):
        request = {
            "acceptance": ["contract", "fixed"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [
                sample("contract", "known_acceptance", "fail", control_result="pass"),
                sample("fixed", "known_acceptance", "pass", control_result="fail"),
            ],
            "revisions": [],
        }

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

        self.assertEqual(1, result["differential"]["regressions"])
        self.assertEqual(1, result["differential"]["fixes"])
        self.assertEqual("failed", result["stop_reason"])

    def test_exploration_failures_are_reported_but_do_not_block_completion(self):
        request = {
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["skills/converge-review"],
            "critical_decisions": [],
            "sample_receipts": [
                sample("contract", "known_acceptance"),
                sample("probe", "exploration", "fail", worker_ref="worker-2"),
            ],
            "revisions": [],
        }

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

        self.assertEqual("complete", result["stop_reason"])
        self.assertEqual(1, result["exploration_distribution"]["fail_count"])

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
            evaluate(secure({
                **base,
                "sample_receipts": [sample(
                    "contract", "known_acceptance", candidate_source="another-candidate"
                )],
            }), ROOT / "references/evaluation-catalog.json")

        with self.assertRaisesRegex(ValueError, "frozen judge"):
            evaluate(secure({
                **base,
                "sample_receipts": [
                    sample("contract", "known_acceptance", worker_ref="worker-1"),
                    sample(
                        "probe", "exploration", worker_ref="worker-2",
                        judge_fingerprint="b" * 64,
                    ),
                ],
            }), ROOT / "references/evaluation-catalog.json")

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

        result = evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

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
            evaluate(secure(request), ROOT / "references/evaluation-catalog.json")

    def test_sources_must_resolve_to_frozen_git_commits(self):
        receipt = sample(
            "contract", "known_acceptance", control_source="caller-control",
            candidate_source="caller-candidate",
        )
        request = secure({
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "caller-control",
            "candidate_source": "caller-candidate",
            "allowed_scope": ["scripts"],
            "critical_decisions": [],
            "sample_receipts": [receipt],
            "revisions": [],
        })

        with self.assertRaisesRegex(ValueError, "Git"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")

    def test_judge_worker_and_touched_paths_are_bound_to_frozen_inputs(self):
        receipt = sample(
            "contract", "known_acceptance", touched_paths=["outside/file.py"]
        )
        request = secure({
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": "control",
            "candidate_source": "candidate",
            "allowed_scope": ["scripts"],
            "critical_decisions": [],
            "sample_receipts": [receipt],
            "revisions": [],
        })

        with self.assertRaisesRegex(ValueError, "allowed_scope"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        request["worker_registry"] = []
        with self.assertRaisesRegex(ValueError, "worker"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        request["judge_source"] = str(ROOT / "README.md")
        with self.assertRaisesRegex(ValueError, "judge"):
            evaluate(request, ROOT / "references/evaluation-catalog.json")


if __name__ == "__main__":
    unittest.main()
