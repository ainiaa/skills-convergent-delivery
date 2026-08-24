#!/usr/bin/env python3
"""Run skill-selection prompts through an external selector command."""

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def run_evals(dataset, command, timeout=60):
    if not isinstance(command, list) or not command or any(
        not isinstance(item, str) or not item for item in command
    ):
        raise ValueError("command must be a non-empty argv list")
    if not isinstance(timeout, int) or isinstance(timeout, bool) or timeout <= 0:
        raise ValueError("timeout must be a positive integer")
    if not isinstance(dataset, dict) or set(dataset) != {"schema_version", "suite", "evals"}:
        raise ValueError("trigger evaluation dataset is invalid")
    cases = dataset["evals"]
    if dataset["schema_version"] != 1 or not isinstance(dataset["suite"], str) \
            or not dataset["suite"].strip() or not isinstance(cases, list) or not cases:
        raise ValueError("trigger evaluation dataset is invalid")
    seen_ids = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != {
            "id", "prompt", "expected_skill", "should_trigger"
        } or not isinstance(case["id"], str) or not case["id"].strip() \
                or not isinstance(case["prompt"], str) or not case["prompt"].strip() \
                or (case["expected_skill"] is not None and (
                    not isinstance(case["expected_skill"], str)
                    or not case["expected_skill"].strip()
                )) or not isinstance(case["should_trigger"], bool) \
                or case["should_trigger"] is not (case["expected_skill"] is not None) \
                or case["id"] in seen_ids:
            raise ValueError("trigger evaluation case is invalid")
        seen_ids.add(case["id"])
    dataset_fingerprint = hashlib.sha256(json.dumps(
        dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    selector_fingerprint = hashlib.sha256(json.dumps(
        command, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    results = []
    confusion = {}
    true_positive = true_negative = false_positive = false_negative = 0
    for case in cases:
        completed = subprocess.run(
            [*command, case["prompt"]], text=True, capture_output=True,
            check=False, timeout=timeout,
        )
        selected = None
        error = None
        if completed.returncode == 0:
            try:
                payload = json.loads(completed.stdout)
                if not isinstance(payload, dict) or set(payload) != {"selected_skill"}:
                    raise TypeError
                selected = payload["selected_skill"]
            except (KeyError, TypeError, json.JSONDecodeError):
                error = "selector output is invalid"
        else:
            error = f"selector exited {completed.returncode}"
        if selected is not None and (not isinstance(selected, str) or not selected.strip()):
            error, selected = "selected_skill is invalid", None
        expected = case["expected_skill"]
        exact = error is None and selected == expected
        if expected is None and selected is None and error is None:
            true_negative += 1
        elif expected is not None and selected == expected and error is None:
            true_positive += 1
        else:
            false_negative += int(expected is not None)
            false_positive += int(selected is not None)
        expected_label = expected or "<none>"
        actual_label = "<error>" if error is not None else selected or "<none>"
        confusion.setdefault(expected_label, {})[actual_label] = (
            confusion.setdefault(expected_label, {}).get(actual_label, 0) + 1
        )
        results.append({
            "id": case["id"], "expected_skill": expected, "selected_skill": selected,
            "exact": exact, "error": error,
        })
    error_count = sum(item["error"] is not None for item in results)
    precision = true_positive / (true_positive + false_positive) \
        if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) \
        if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    if error_count:
        f1 = 0.0
    return {
        "dataset_fingerprint": dataset_fingerprint,
        "selector_fingerprint": selector_fingerprint,
        "runner_fingerprint": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "executed_cases": len(results),
        "exact_matches": sum(item["exact"] for item in results),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "true_positive": true_positive,
        "true_negative": true_negative,
        "false_positive": false_positive,
        "false_negative": false_negative,
        "error_count": error_count,
        "confusion_matrix": confusion,
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--command", required=True, help="JSON argv; prompt is appended")
    parser.add_argument("--timeout", type=int, default=60)
    arguments = parser.parse_args()
    try:
        with open(arguments.dataset, encoding="utf-8") as file:
            dataset = json.load(file)
        result = run_evals(dataset, json.loads(arguments.command), arguments.timeout)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0 if result["exact_matches"] == result["executed_cases"] else 1
    except (OSError, ValueError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        print(f"trigger evaluation blocked: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
