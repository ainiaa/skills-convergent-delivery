#!/usr/bin/env python3
"""Executable tests for deterministic evaluation bookkeeping."""

import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from pathlib import Path

import eval_contract
from eval_contract import _evaluate_receipts as evaluate


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
from delivery_next import upgrade_state  # noqa: E402
from runtime_adapter import _bind  # noqa: E402
from task_profile import freeze_routing  # noqa: E402
from test_delivery_state import state as legacy_state  # noqa: E402

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
WORKER_REFS = [f"worker-{number}" for number in range(1, 5)]
HOST_OBSERVATION = {
    "query_id": "host-query-eval-workers",
    "observed_at": "2026-08-24T00:00:00Z",
    "registered_refs": WORKER_REFS,
    "active_refs": [],
    "unexpected_refs": [],
}
HOST_OBSERVATION_FINGERPRINT = hashlib.sha256(json.dumps(
    HOST_OBSERVATION, sort_keys=True, separators=(",", ":")
).encode()).hexdigest()


def sample(scenario_id, scenario_class, result="pass", worker_ref="worker-1", **overrides):
    value = {
        "schema_version": 4,
        "scenario_id": scenario_id,
        "scenario_class": scenario_class,
        "control_source": CONTROL_COMMIT,
        "candidate_source": CANDIDATE_COMMIT,
        "judge_fingerprint": JUDGE_FINGERPRINT,
        "worker_ref": worker_ref,
        "worker_observation_fingerprint": HOST_OBSERVATION_FINGERPRINT,
        "evidence_level": "evaluator_attested",
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
    state = upgrade_state(legacy_state())
    state["workspace"] = str(ROOT)
    state.update(
        status="blocked", blocked_code="environment",
        blocked_reason="legacy evaluation worker fixture",
    )
    state["execution_control"]["routing"] = freeze_routing(
        {
            **state["execution_control"]["routing"]["profile"],
            "coupling": "independent", "delegable_tasks": len(WORKER_REFS),
            "context_isolation_benefit": True,
        }, ["."],
    )
    state["execution_control"]["review"]["integration_budget_remaining"] = 1
    capability_observation = {
        "query_id": "host-capabilities-eval", "observed_at": "2026-08-24T00:00:00Z",
        "profile": "codex", "capabilities": ["dispatch", "query", "wait", "interrupt", "tree_query"],
    }
    state["runtime_binding"] = _bind(
        "codex", "automatic", capability_observation["capabilities"], "legacy test fixture",
        "host_observed", capability_observation,
    )
    state["workers"] = [{
            "ref": ref,
            "parent_ref": None,
            "task_id": state["task_key"],
            "depth": 1,
            "may_dispatch": False,
            "role": "evaluator",
            "owner_run_id": state["run_id"],
            "status": "completed",
            "progress": None,
        } for ref in WORKER_REFS]
    state["worker_tree_receipt"] = {
        "schema_version": 2, "observed_revision": state["revision"],
        "observed_at": HOST_OBSERVATION["observed_at"],
        "runtime_fingerprint": state["runtime_binding"]["binding_fingerprint"],
        "mode": "tree_query", "evidence_level": "host_observed",
        "observation_fingerprint": HOST_OBSERVATION_FINGERPRINT,
        "registered_refs": WORKER_REFS, "active_refs": [], "unexpected_refs": [],
    }
    artifact = Path(ARTIFACTS.name) / f"state-{next(ARTIFACT_SEQUENCE)}.json"
    artifact.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    request["worker_state_source"] = str(artifact)
    return request


class DeterministicBridgeTest(unittest.TestCase):
    def test_real_frozen_differential_and_failure_boundaries(self):
        from controller_snapshot import create_snapshot
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / 'repo'
            repo.mkdir()
            def git(*args):
                return subprocess.run(['git', '-C', str(repo), *args], check=True,
                                      capture_output=True, text=True).stdout.strip()
            git('init', '-q')
            judge = "import unittest, calc\nclass Check(unittest.TestCase):\n def test_value(self): self.assertEqual(calc.value(), 2)\n"
            (repo / 'judge.py').write_text(judge)
            (repo / 'alias').symlink_to('calc.py')
            suite = {'allowed_scope': ['calc.py'], 'touched_control_surfaces': [],
                     'scenarios': [{'id': 'value', 'class': 'known_acceptance', 'judge': 'judge.py'}]}
            (repo / 'suite.json').write_text(json.dumps(suite))
            def tree(value):
                (repo / 'calc.py').write_text(value)
                git('add', '.')
                return git('write-tree')
            control = tree('def value(): return 1\n')
            good = tree('def value(): return 2\n')
            snapshot = create_snapshot(ROOT, root / 'controller')
            request = {'controller_snapshot': snapshot, 'control_source': control,
                       'candidate_source': good, 'suite': 'suite.json', 'timeout_seconds': 1}
            with self.assertRaisesRegex(ValueError, 'frozen snapshot'):
                eval_contract.deterministic_evaluate(request, repo)
            request_file = root / 'request.json'
            def run(overrides=None):
                request_file.write_text(json.dumps({**request, **(overrides or {})}))
                result = subprocess.run([sys.executable, str(Path(snapshot['root']) /
                    'skills/converge-eval/scripts/eval_contract.py'), '--deterministic',
                    '--input', str(request_file), '--repository', str(repo)],
                    capture_output=True, text=True, timeout=30)
                self.assertTrue(result.stdout, result.stderr)
                observed = json.loads(result.stdout)
                # Exercise the public function on its instrumented source as well as the frozen CLI.
                with patch.object(eval_contract, 'CONTROL_ROOT', Path(snapshot['root'])), \
                     patch.object(eval_contract, 'LOCKED_CATALOG', Path(snapshot['root']) / 'references/evaluation-catalog.json'):
                    try:
                        direct = eval_contract.deterministic_evaluate({**request, **(overrides or {})}, repo)
                    except ValueError:
                        self.assertEqual('uncovered', observed['status'])
                    else:
                        self.assertEqual(observed['status'], direct['status'])
                return result.returncode, observed
            code, result = run()
            self.assertEqual(0, code, result)
            self.assertEqual('process_observed', result['evidence_level'])
            self.assertEqual(['value'], result['differential']['fixed'])
            self.assertEqual('uncovered', result['release_status'])
            broken = tree('import missing_dependency\n')
            code, result = run({'control_source': broken})
            self.assertEqual('uncovered', result['status'])
            self.assertEqual([], result['differential']['fixed'])
            code, result = run({'control_source': good, 'candidate_source': control})
            self.assertNotEqual(0, code)
            self.assertEqual(['value'], result['differential']['regressions'])
            self.assertNotEqual(0, run({'candidate_source': control})[0])
            hanging = tree('import time\ndef value(): time.sleep(5); return 2\n')
            code, result = run({'candidate_source': hanging})
            self.assertNotEqual(0, code)
            self.assertEqual(124, result['samples'][0]['candidate']['exit_code'])
            (repo / 'judge.py').write_text('import unittest\n')
            changed_judge = tree('def value(): return 2\n')
            self.assertNotEqual(0, run({'candidate_source': changed_judge})[0])
            self.assertEqual('import unittest\n', (repo / 'judge.py').read_text())
            self.assertNotEqual(0, run({'suite': '../suite.json'})[0])
            for timeout in (0, True, 601):
                self.assertNotEqual(0, run({'timeout_seconds': timeout})[0])
            empty_control = changed_judge
            empty_candidate = tree('def value(): return 3\n')
            code, result = run({'control_source': empty_control, 'candidate_source': empty_candidate})
            self.assertNotEqual(0, code)
            self.assertFalse(result['samples'][0]['candidate']['pass'])
            (repo / 'alias').unlink()
            (repo / 'alias').symlink_to('/tmp')
            escaped = tree('def value(): return 4\n')
            self.assertNotEqual(0, run({'candidate_source': escaped})[0])


class EvalAvailabilityTest(unittest.TestCase):
    def test_preflight_requires_both_host_adapters(self):
        bridge = Mock()
        bridge.preflight.return_value = {
            "codex": {"status": "ready", "host_fingerprint": "a" * 64},
            "claude": {"status": "unavailable", "reason": "missing"},
        }
        with patch.object(eval_contract, "_host_bridge", return_value=bridge):
            result = eval_contract.preflight()

        self.assertEqual("uncovered", result["status"])
        self.assertFalse(result["eligible"])
        self.assertEqual("unavailable_host_bridge", result["stop_reason"])

    def test_deterministic_cli_preflight_and_invalid_input_are_structured(self):
        script = str(Path(eval_contract.__file__))
        result = subprocess.run([sys.executable, script, '--preflight', '--deterministic'],
                                capture_output=True, text=True, check=False)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual('ready', json.loads(result.stdout)['status'])
        self.assertIn('model_behavior', json.loads(result.stdout)['uncovered'])
        with tempfile.TemporaryDirectory() as directory:
            request = Path(directory) / 'request.json'
            for content in ('{}', 'invalid json'):
                request.write_text(content)
                result = subprocess.run([sys.executable, script, '--deterministic',
                                        '--input', str(request), '--repository', str(ROOT)],
                                        capture_output=True, text=True, check=False)
                self.assertEqual(2, result.returncode)
                self.assertEqual('uncovered', json.loads(result.stdout)['status'])
                self.assertTrue(json.loads(result.stdout)['stop_reason'])

    def test_public_evaluation_reports_missing_bridge_before_reading_artifacts(self):
        bridge = Mock()
        bridge.preflight.return_value = {
            "codex": {"status": "unavailable", "reason": "missing"},
            "claude": {"status": "unavailable", "reason": "missing"},
        }
        with patch.object(eval_contract, "_host_bridge", return_value=bridge), \
                patch.object(eval_contract, "_worker_state", side_effect=AssertionError("read artifacts")):
            result = eval_contract.evaluate({}, ROOT)
        self.assertEqual("uncovered", result["status"])
        self.assertFalse(result["eligible"])
        self.assertEqual("unavailable_host_bridge", result["stop_reason"])

    def test_cli_preflight_reports_bridge_readiness_but_never_fabricates_a_live_result(self):
        with tempfile.TemporaryDirectory() as binaries:
            preflight = subprocess.run(
                [sys.executable, str(Path(eval_contract.__file__)), "--preflight"],
                capture_output=True, text=True, check=False,
                env={**os.environ, "PATH": binaries},
            )
        self.assertEqual(2, preflight.returncode)
        self.assertEqual("uncovered", json.loads(preflight.stdout)["status"])
        self.assertEqual("unavailable_host_bridge", json.loads(preflight.stdout)["stop_reason"])
        evaluation = subprocess.run(
            [sys.executable, str(Path(eval_contract.__file__)), "--input", "/missing/request",
             "--repository", str(ROOT)], capture_output=True, text=True, check=False,
        )
        self.assertEqual(2, evaluation.returncode)
        self.assertEqual("uncovered", json.loads(evaluation.stdout)["status"])


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

        result = evaluate(secure(request), ROOT)
        self.assertEqual("diagnostic", result["evidence_level"])
        self.assertEqual("uncovered", result["release_status"])

        self.assertEqual(10, result["sample_distribution"]["sample_count"])
        self.assertEqual(9, result["sample_distribution"]["pass_count"])
        self.assertEqual(9 / 10, result["sample_distribution"]["pass_rate"])
        self.assertEqual(8 / 9, result["gating_distribution"]["pass_rate"])
        self.assertEqual("failed", result["stop_reason"])
        self.assertEqual(["new-worker-probe"], result["exploration"])
        self.assertEqual([], result["uncovered"])
        self.assertEqual(64, len(result["state_validator_fingerprint"]))
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

        result = evaluate(secure(request), ROOT)

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
            evaluate(secure(request), ROOT)

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

        result = evaluate(secure(request), ROOT)

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
            evaluate(secure(request), ROOT)

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
            evaluate(secure(request), ROOT)

    def test_evidence_artifact_must_stay_outside_the_candidate_repository(self):
        receipt = sample("contract", "known_acceptance")
        candidate_artifact = ROOT / "README.md"
        receipt["evidence_source"] = str(candidate_artifact)
        receipt["evidence_fingerprint"] = hashlib.sha256(candidate_artifact.read_bytes()).hexdigest()
        receipt["receipt_fingerprint"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in receipt.items() if key != "receipt_fingerprint"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode()
        ).hexdigest()
        request = {
            "acceptance": ["contract"], "touched_control_surfaces": ["review.protocol"],
            "control_source": "control", "candidate_source": "candidate", "allowed_scope": ["scripts"],
            "critical_decisions": [], "sample_receipts": [receipt], "revisions": [],
        }

        with self.assertRaisesRegex(ValueError, "outside the candidate repository"):
            evaluate(secure(request), ROOT)

    def test_worker_tree_receipt_order_does_not_change_evaluation_identity(self):
        request = secure({
            "acceptance": ["contract"], "touched_control_surfaces": ["review.protocol"],
            "control_source": "control", "candidate_source": "candidate", "allowed_scope": ["scripts"],
            "critical_decisions": [], "sample_receipts": [sample("contract", "known_acceptance")],
            "revisions": [],
        })
        state_path = Path(request["worker_state_source"])
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["worker_tree_receipt"]["registered_refs"] = list(reversed(WORKER_REFS))
        state_path.write_text(json.dumps(state), encoding="utf-8")

        self.assertEqual("complete", evaluate(request, ROOT)["stop_reason"])

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
            evaluate(secure(request), ROOT)

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

        result = evaluate(secure(request), ROOT)

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

        result = evaluate(secure(request), ROOT)

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
            }), ROOT)

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
            }), ROOT)

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

        result = evaluate(secure(request), ROOT)

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
            evaluate(secure(request), ROOT)

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
            evaluate(request, ROOT)

    def test_sources_may_be_frozen_git_trees(self):
        control_tree = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", f"{CONTROL_COMMIT}^{{tree}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        candidate_tree = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", f"{CANDIDATE_COMMIT}^{{tree}}"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        receipt = sample(
            "contract", "known_acceptance",
            control_source=control_tree, candidate_source=candidate_tree,
        )
        request = secure({
            "acceptance": ["contract"],
            "touched_control_surfaces": ["review.protocol"],
            "control_source": control_tree,
            "candidate_source": candidate_tree,
            "allowed_scope": ["scripts"],
            "critical_decisions": [],
            "sample_receipts": [receipt],
            "revisions": [],
        })

        result = evaluate(request, ROOT)

        self.assertEqual(candidate_tree, result["candidate_identity"]["tree"])
        self.assertIsNone(result["candidate_identity"]["commit"])

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
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        Path(request["worker_state_source"]).write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "worker|schema_version"):
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        state = json.loads(Path(request["worker_state_source"]).read_text(encoding="utf-8"))
        state.pop("controller")
        Path(request["worker_state_source"]).write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "controller"):
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        state = json.loads(Path(request["worker_state_source"]).read_text(encoding="utf-8"))
        state["workspace"] = "/another/workspace"
        Path(request["worker_state_source"]).write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "workspace"):
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        state = json.loads(Path(request["worker_state_source"]).read_text(encoding="utf-8"))
        state["workers"][0]["role"] = "implementer"
        Path(request["worker_state_source"]).write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "evaluator"):
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        request["worker_state_source"] = str(JUDGE_SOURCE)
        with self.assertRaisesRegex(ValueError, "outside the candidate repository"):
            evaluate(request, ROOT)

        request = secure({**request, "sample_receipts": [sample("contract", "known_acceptance")]})
        request["judge_source"] = str(ROOT / "README.md")
        with self.assertRaisesRegex(ValueError, "judge"):
            evaluate(request, ROOT)

    def test_touched_paths_cannot_escape_even_when_repository_root_is_allowed(self):
        for touched in (["../outside.py"], ["/outside.py"], ["scripts\\inside.py"]):
            with self.subTest(touched=touched):
                receipt = sample(
                    "contract", "known_acceptance", touched_paths=touched
                )
                request = secure({
                    "acceptance": ["contract"],
                    "touched_control_surfaces": ["review.protocol"],
                    "control_source": "control",
                    "candidate_source": "candidate",
                    "allowed_scope": ["."],
                    "critical_decisions": [],
                    "sample_receipts": [receipt],
                    "revisions": [],
                })
                with self.assertRaisesRegex(ValueError, "touched_paths|allowed_scope"):
                    evaluate(request, ROOT)

    def test_frozen_eval_requires_the_default_managed_state_path(self):
        payload = {
            "repo_id": str(ROOT / ".git"),
            "workspace": str(ROOT),
            "task_key": "task-eval",
            "run_id": "run-eval",
        }
        with self.assertRaisesRegex(ValueError, "managed state"):
            eval_contract._require_managed_state_path(
                payload, Path(ARTIFACTS.name) / "parallel-state.json", True
            )


if __name__ == "__main__":
    unittest.main()
