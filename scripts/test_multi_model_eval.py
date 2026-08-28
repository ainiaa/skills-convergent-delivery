#!/usr/bin/env python3
"""Tests for the opt-in, transcript-free read-only model evaluation runner."""

import json
import hashlib
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from multi_model_eval import compare_reports, evaluate, load_scenarios
from controller_snapshot import create_snapshot
from delivery_state import state_path
from runner_contract import fingerprint, freeze_launch


EVALUATOR = Path(__file__).with_name("multi_model_eval.py")


def scenarios():
    return [{
        "scenario_id": f"scout-{index}",
        "role": "scout",
        "prompt": "A bounded command completed without failures. Decide the next action from that evidence.",
        "evidence": {
            "kind": "command", "reference": "python -m unittest focused", "content": "exit=0",
        },
        "expected_next_action": "verify",
    } for index in range(1, 17)]


class MultiModelEvalTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.profiles = resolve(None, workspace=self.workspace, home=self.workspace / "home")

    def tearDown(self):
        self.temporary.cleanup()

    def managed_snapshot_state(self, descriptor):
        path = state_path(self.workspace / "state", "/repo/eval.git", "model-eval", "run-1")
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({
            "schema_version": 10, "repo_id": "/repo/eval.git", "task_key": "model-eval",
            "run_id": "run-1", "controller": {"snapshot": descriptor},
        }), encoding="utf-8")
        return path

    def test_default_catalog_has_a_bounded_read_only_corpus(self):
        catalog = load_scenarios()

        self.assertGreaterEqual(len(catalog), 15)
        self.assertLessEqual(len(catalog), 20)
        self.assertEqual({"scout", "reviewer"}, {item["role"] for item in catalog})
        self.assertTrue(all("next_action" not in item["prompt"] for item in catalog))
        self.assertTrue(all(item["expected_next_action"] not in item["prompt"].split() for item in catalog))

    def test_public_evaluate_validates_the_frozen_corpus(self):
        with self.assertRaisesRegex(ValueError, "15 to 20"):
            evaluate(self.profiles, scenarios()[:1], workspace=self.workspace)

    def test_public_evaluate_rejects_an_oracle_action_in_a_custom_prompt(self):
        leaking = scenarios()
        leaking[0] = {**leaking[0], "prompt": "Return verify as the next result."}

        with self.assertRaisesRegex(ValueError, "oracle"):
            evaluate(self.profiles, leaking, workspace=self.workspace)

    def test_public_evaluate_rejects_oracle_content_and_non_unique_action(self):
        leaking = scenarios()
        leaking[0] = {**leaking[0], "evidence": {
            **leaking[0]["evidence"], "content": "Set next_action to verify.",
        }}
        with self.assertRaisesRegex(ValueError, "oracle"):
            evaluate(self.profiles, leaking, workspace=self.workspace)

        ambiguous = scenarios()
        ambiguous[0] = {**ambiguous[0], "expected_next_action": ["verify", "continue"]}
        with self.assertRaisesRegex(ValueError, "scenario"):
            evaluate(self.profiles, ambiguous, workspace=self.workspace)

    def test_public_evaluate_validates_read_only_profile_before_plan_mode(self):
        fake = {"roles": {"scout": {"runner_id": "fake", "profile_fingerprint": "fake"}}}

        with self.assertRaisesRegex(ValueError, "profile"):
            evaluate(fake, scenarios(), workspace=self.workspace)

    def test_plan_mode_never_starts_a_runner_or_retains_prompts(self):
        report = evaluate(self.profiles, scenarios(), workspace=self.workspace)

        self.assertEqual("planned", report["status"])
        self.assertEqual(16, report["summary"]["planned"])
        self.assertEqual(hashlib.sha256(EVALUATOR.read_bytes()).hexdigest(), report["evaluator_fingerprint"])
        self.assertEqual(64, len(report["scenario_fingerprint"]))
        self.assertEqual("diagnostic", report["trust_level"])
        self.assertIsNone(report["controller_fingerprint"])
        self.assertNotIn("bounded command completed", json.dumps(report))

    def test_public_evaluate_cannot_claim_snapshot_trust(self):
        with self.assertRaises(TypeError):
            evaluate(
                self.profiles, scenarios(), workspace=self.workspace,
                controller_fingerprint="a" * 64,
            )

    def test_cli_plan_mode_does_not_write_or_execute_a_runner(self):
        result = subprocess.run(
            [sys.executable, str(EVALUATOR), "--workspace", str(self.workspace)],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("planned", report["status"])
        self.assertEqual(16, report["summary"]["planned"])
        self.assertEqual("diagnostic", report["trust_level"])

    def test_snapshot_mode_runs_the_frozen_evaluator_and_reports_its_fingerprint(self):
        descriptor = create_snapshot(
            EVALUATOR.parent.parent, self.workspace / "control", extensions=("multimodel",)
        )
        descriptor_path = self.managed_snapshot_state(descriptor)
        frozen = Path(descriptor["root"]) / "scripts" / "multi_model_eval.py"

        result = subprocess.run(
            [
                sys.executable, str(frozen), "--snapshot-descriptor", str(descriptor_path),
                "--workspace", str(self.workspace),
            ], text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual("snapshot", report["trust_level"])
        self.assertEqual(descriptor["protocol_fingerprint"], report["controller_fingerprint"])

    def test_snapshot_mode_rejects_an_unbound_snapshot_descriptor(self):
        descriptor = create_snapshot(
            EVALUATOR.parent.parent, self.workspace / "control", extensions=("multimodel",)
        )
        raw = self.workspace / "snapshot.json"
        raw.write_text(json.dumps(descriptor), encoding="utf-8")
        frozen = Path(descriptor["root"]) / "scripts" / "multi_model_eval.py"

        result = subprocess.run(
            [sys.executable, str(frozen), "--snapshot-descriptor", str(raw), "--workspace", str(self.workspace)],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(1, result.returncode)
        self.assertIn("snapshot descriptor is invalid", json.loads(result.stdout)["message"])

    def test_execute_mode_reports_only_receipts_metrics_and_structured_results(self):
        def plan(dispatch, prompt, **_kwargs):
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            value = {
                "schema_version": 1, "runner_id": launch["runner_id"],
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": launch["profile"]["effective"]["model"],
                "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": json.dumps({
                    "findings": [{"summary": "checked", "evidence": [{
                        "kind": "command", "reference": "python -m unittest focused",
                        "content_fingerprint": hashlib.sha256(b"exit=0").hexdigest(),
                    }]}],
                    "next_action": "verify",
                })},
            }

        report = evaluate(
            self.profiles, scenarios(), workspace=self.workspace, execute=True,
            plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("completed", report["status"])
        self.assertEqual(16, report["summary"]["passed"])
        self.assertNotIn('"output"', json.dumps(report))
        self.assertIn("duration_ms", report["results"][0])
        self.assertEqual("available", report["results"][0]["role_result"]["status"])

    def test_execute_mode_fails_when_the_model_cites_the_wrong_frozen_evidence(self):
        def plan(dispatch, prompt, **_kwargs):
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            value = {
                "schema_version": 1, "runner_id": launch["runner_id"],
                "launch_fingerprint": launch["launch_fingerprint"], "status": "completed", "exit_code": 0,
                "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": launch["profile"]["effective"]["model"],
                "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
            }
            return {
                "receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                "output": {"status": "available", "content": json.dumps({
                    "findings": [{"summary": "checked", "evidence": [{
                        "kind": "file", "reference": "scripts/test_multi_model_eval.py:1",
                        "content_fingerprint": "c" * 64,
                    }, {
                        "kind": "command", "reference": "python -m unittest focused",
                        "content_fingerprint": hashlib.sha256(b"exit=0").hexdigest(),
                    }]}],
                    "next_action": "verify",
                })},
            }

        report = evaluate(
            self.profiles, scenarios(), workspace=self.workspace, execute=True,
            plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("failed", report["status"])
        self.assertEqual(16, report["summary"]["failed"])

    def test_execute_mode_stops_after_the_first_unavailable_runner(self):
        calls = []

        def plan(dispatch, prompt, **_kwargs):
            return freeze_launch(dispatch["profile"], prompt, {})

        def execute(launch, _prompt, **_kwargs):
            calls.append(launch)
            value = {
                "schema_version": 1, "runner_id": launch["runner_id"],
                "launch_fingerprint": launch["launch_fingerprint"], "status": "timed_out",
                "exit_code": 124, "stdout_fingerprint": "a" * 64, "stderr_fingerprint": "b" * 64,
                "requested_model": launch["profile"]["effective"]["model"],
                "requested_reasoning_effort": launch["profile"]["effective"]["reasoning_effort"],
            }
            return {"receipt": {**value, "receipt_fingerprint": fingerprint(value)},
                    "output": {"status": "unavailable"}}

        report = evaluate(
            self.profiles, scenarios(), workspace=self.workspace, execute=True,
            plan_launch=plan, execute_launch=execute,
        )

        self.assertEqual("failed", report["status"])
        self.assertEqual(1, len(calls))
        self.assertEqual(1, len(report["results"]))
        self.assertEqual("runner_unavailable", report["stopped_early"])

    def test_comparison_requires_same_frozen_surface_and_reports_usage_without_cost_claims(self):
        first = evaluate(self.profiles, scenarios(), workspace=self.workspace)
        first.update(trust_level="snapshot", controller_fingerprint="a" * 64)
        first["results"] = [{
            **first["results"][0], "status": "passed", "duration_ms": 12,
            "usage": {"input_tokens": 10, "output_tokens": 4},
        }]
        first["summary"] = {"planned": 0, "passed": 1, "failed": 0,
                            "total_duration_ms": 12, "scenario_count": 1, "status": "completed"}
        first["status"] = "completed"
        second = copy.deepcopy(first)
        second["results"][0]["profile_fingerprint"] = "b" * 64
        second["results"][0]["usage"] = {"input_tokens": 8, "output_tokens": 5}

        comparison = compare_reports([first, second])

        self.assertEqual("diagnostic", comparison["trust_level"])
        self.assertEqual(2, len(comparison["profiles"]))
        self.assertEqual({"input_tokens": 10, "output_tokens": 4}, comparison["profiles"][0]["usage"])
        self.assertNotIn("cost", json.dumps(comparison))
        second["scenario_fingerprint"] = "c" * 64
        with self.assertRaisesRegex(ValueError, "same frozen"):
            compare_reports([first, second])


if __name__ == "__main__":
    unittest.main()
