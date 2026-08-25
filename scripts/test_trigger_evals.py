#!/usr/bin/env python3
"""Validate the Suite trigger and role-isolation evaluation dataset."""

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from trigger_eval import run_evals
SKILLS = {"converge", "converge-plan", "converge-review", "converge-batch", "converge-eval"}


class TriggerEvalTest(unittest.TestCase):
    def test_dataset_has_valid_balanced_role_isolation_cases(self):
        payload = json.loads((ROOT / "evals/evals.json").read_text(encoding="utf-8"))
        self.assertEqual({"schema_version", "suite", "evals"}, set(payload))
        self.assertEqual(1, payload["schema_version"])
        self.assertEqual("converge", payload["suite"])
        cases = payload["evals"]
        self.assertGreaterEqual(len(cases), 12)
        self.assertEqual(len(cases), len({case["id"] for case in cases}))

        counts = {skill: 0 for skill in SKILLS}
        negatives = 0
        for case in cases:
            self.assertEqual(
                {"id", "prompt", "expected_skill", "should_trigger"}, set(case)
            )
            self.assertTrue(case["id"].strip())
            self.assertTrue(case["prompt"].strip())
            expected = case["expected_skill"]
            self.assertIn(expected, {*SKILLS, None})
            self.assertIs(case["should_trigger"], expected is not None)
            if expected is None:
                negatives += 1
            else:
                counts[expected] += 1

        self.assertTrue(all(count >= 2 for count in counts.values()))
        self.assertGreaterEqual(negatives, 2)

    def test_runner_executes_a_selector_and_reports_confusion_and_f1(self):
        dataset = {
            "schema_version": 1,
            "suite": "converge",
            "evals": [
                {"id": "implement", "prompt": "implement it", "expected_skill": "converge", "should_trigger": True},
                {"id": "review", "prompt": "review it", "expected_skill": "converge-review", "should_trigger": True},
                {"id": "negative", "prompt": "explain it", "expected_skill": None, "should_trigger": False},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selector.py"
            source.write_text(
                "import json,sys\n"
                "p=sys.argv[1]\n"
                "s='converge-review' if 'review' in p else ('converge' if 'implement' in p else None)\n"
                "print(json.dumps({'selected_skill':s}))\n",
                encoding="utf-8",
            )
            selector = {"argv": [sys.executable, str(source)], "artifacts": [str(source)]}
            result = run_evals(dataset, selector)
            original_fingerprint = result["selector_fingerprint"]
            source.write_text("raise SystemExit(99)\n", encoding="utf-8")
            changed = run_evals(dataset, selector)

        self.assertEqual(3, result["executed_cases"])
        self.assertEqual(1.0, result["f1"])
        self.assertEqual(3, result["exact_matches"])
        self.assertEqual(1, result["confusion_matrix"]["converge"]["converge"])
        self.assertEqual(64, len(result["dataset_fingerprint"]))
        self.assertEqual(64, len(result["selector_fingerprint"]))
        self.assertEqual(64, len(result["runner_fingerprint"]))
        self.assertNotEqual(original_fingerprint, changed["selector_fingerprint"])

    def test_runner_rejects_malformed_dataset_before_execution(self):
        selector = {"argv": [sys.executable, "-c", "raise SystemExit(99)"], "artifacts": [str(__file__)]}
        with self.assertRaisesRegex(ValueError, "dataset"):
            run_evals([], selector)
        with self.assertRaisesRegex(ValueError, "case"):
            run_evals({
                "schema_version": 1,
                "suite": "converge",
                "evals": [{"id": "broken", "expected_skill": None, "should_trigger": False}],
            }, selector)

    def test_selector_errors_are_not_reported_as_no_selection_or_perfect_f1(self):
        dataset = {
            "schema_version": 1,
            "suite": "converge",
            "evals": [
                {"id": "implement", "prompt": "implement", "expected_skill": "converge", "should_trigger": True},
                {"id": "negative", "prompt": "explain", "expected_skill": None, "should_trigger": False},
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "selector.py"
            source.write_text(
                "import json,sys\n"
                "if sys.argv[1] == 'explain': raise SystemExit(7)\n"
                "print(json.dumps({'selected_skill':'converge'}))\n",
                encoding="utf-8",
            )
            result = run_evals(
                dataset, {"argv": [sys.executable, str(source)], "artifacts": [str(source)]}
            )

        self.assertEqual(1, result["error_count"])
        self.assertLess(result["f1"], 1.0)
        self.assertEqual(1, result["confusion_matrix"]["<none>"]["<error>"])

    def test_runner_rejects_untracked_or_missing_selector_artifacts(self):
        dataset = {
            "schema_version": 1,
            "suite": "converge",
            "evals": [{"id": "negative", "prompt": "explain", "expected_skill": None, "should_trigger": False}],
        }
        with self.assertRaisesRegex(ValueError, "selector"):
            run_evals(dataset, [sys.executable, "-c", "print('{}')"])
        with self.assertRaisesRegex(ValueError, "artifact"):
            run_evals(
                dataset,
                {"argv": [sys.executable, "-c", "print('{}')"], "artifacts": ["/missing-selector"]},
            )


if __name__ == "__main__":
    unittest.main()
