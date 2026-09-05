#!/usr/bin/env python3
"""Behavior checks for visible step ordering; fixtures are not host observations."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

from step_trace_eval import evaluate


def step_events(step):
    return [
        {"step": step, "kind": "start", "visible": True, "plan": {
            "capability": "unavailable", "result": "not_called", "receipt_ref": None,
            "fallback_disclosed": True}},
        {"step": step, "kind": "edit"},
        {"step": step, "kind": "verify", "result": "pass"},
        {"step": step, "kind": "report", "visible": True, "result": "done", "plan": {
            "capability": "unavailable", "result": "not_called", "receipt_ref": None,
            "fallback_disclosed": True}},
    ]


def trace():
    return {"schema_version": 1, "evidence_level": "fixture", "steps": ["T1", "T2"],
            "completed_before": [], "events": step_events("T1") + step_events("T2")}


def native_trace():
    value = trace()
    projections = [("in_progress", "pending"), ("completed", "pending"),
                   ("completed", "in_progress"), ("completed", "completed")]
    for index, statuses in zip((0, 3, 4, 7), projections):
        value["events"][index]["plan"] = {
            "capability": "available", "result": "success", "receipt_ref": f"call-{index}",
            "fallback_disclosed": False,
            "projection": [{"step": step, "status": status}
                           for step, status in zip(value["steps"], statuses)],
        }
    return value


class StepTraceEvalTest(unittest.TestCase):
    def test_text_only_trace_without_plan_observations_is_uncovered(self):
        value = trace()
        for event in value["events"]:
            event.pop("plan", None)
        self.assertEqual("uncovered", evaluate(value)["status"])

    def test_native_sync_requires_actual_success_references_at_each_step(self):
        value = native_trace()
        result = evaluate(value)
        self.assertEqual("pass", result["status"])
        self.assertEqual("native", result["display_mode"])
        self.assertEqual("uncovered", result["native_ui_status"])
        value["events"][3]["plan"]["receipt_ref"] = None
        self.assertEqual("uncovered", evaluate(value)["status"])

    def test_native_receipt_cannot_describe_different_projections(self):
        value = native_trace()
        for event in value["events"]:
            if "plan" in event:
                event["plan"]["receipt_ref"] = "same-first-call"
        self.assertEqual("fail", evaluate(value)["status"])

    def test_native_projection_must_match_step_and_completion_status(self):
        for event_index, item_index, status in ((3, 0, "in_progress"), (4, 1, "pending"),
                                              (0, 1, "completed"), (4, 0, "pending")):
            value = native_trace()
            value["events"][event_index]["plan"]["projection"][item_index]["status"] = status
            with self.subTest(event=event_index, item=item_index):
                self.assertEqual("fail", evaluate(value)["status"])

    def test_one_native_call_can_complete_previous_and_start_next_step(self):
        value = native_trace()
        value["events"][3]["plan"] = copy.deepcopy(value["events"][4]["plan"])
        self.assertEqual("pass", evaluate(value)["status"])

    def test_missing_projection_is_uncovered_and_malformed_projection_is_rejected(self):
        value = native_trace()
        value["events"][0]["plan"].pop("projection")
        self.assertEqual("uncovered", evaluate(value)["status"])
        for projection in (None, [], [{"step": "T1", "status": "completed"}] * 2,
                           [{"step": "T1", "status": "invalid"}, {"step": "T2", "status": "pending"}]):
            value = native_trace()
            value["events"][0]["plan"]["projection"] = projection
            with self.subTest(projection=projection), self.assertRaises(ValueError):
                evaluate(value)

    def test_native_blocked_report_has_no_running_step(self):
        value = native_trace()
        value["events"] = value["events"][:4]
        value["events"][2]["result"] = "fail"
        value["events"][3]["result"] = "blocked"
        value["events"][3]["plan"]["projection"][0]["status"] = "pending"
        self.assertEqual("pass", evaluate(value)["status"])
        value["events"][3]["plan"]["projection"][0]["status"] = "in_progress"
        self.assertEqual("fail", evaluate(value)["status"])

    def test_available_tool_cannot_be_silently_skipped(self):
        value = trace()
        value["events"][0]["plan"]["capability"] = "available"
        self.assertEqual("fail", evaluate(value)["status"])

    def test_persisted_fallback_survives_reconnection_and_trace_resume(self):
        from delivery_next import upgrade_state, next_runtime_action
        from delivery_state import validate_transition
        from test_delivery_state import state

        for reason in ("unavailable", "unknown", "failed"):
            with self.subTest(reason=reason):
                previous = upgrade_state(state())
                previous["host_sync"]["mode"] = "native"
                candidate = copy.deepcopy(previous)
                candidate["revision"] += 1
                candidate["host_sync"] = {
                    "mode": "text", "acknowledged_fingerprint": None,
                    "evidence_level": "controller_attested",
                    "fallback": {"reason": reason, "evidence_ref": "observation-1",
                                 "disclosure_ref": "message-1"},
                }
                validate_transition(previous, candidate)
                resumed = upgrade_state(json.loads(json.dumps(candidate)))
                self.assertNotEqual("sync-plan", next_runtime_action(resumed, "verify-final")["action"])
                for completed in ([], ["T1"]):
                    value = trace()
                    value["completed_before"] = completed
                    if completed:
                        value["events"] = step_events("T2")
                    for event in value["events"]:
                        if "plan" in event:
                            event["plan"]["capability"] = "available"
                    value["events"][0]["plan"]["fallback"] = resumed["host_sync"]["fallback"]
                    self.assertEqual("pass", evaluate(value)["status"])
                    value["events"][0]["plan"].pop("fallback")
                    self.assertEqual("fail", evaluate(value)["status"])

    def test_persisted_fallback_cannot_be_rewritten_or_upgraded_to_native(self):
        value = trace()
        fallback = {"reason": "unavailable", "evidence_ref": "tool-list", "disclosure_ref": "notice"}
        value["events"][0]["plan"]["fallback"] = fallback
        bad = copy.deepcopy(value)
        bad["events"][0]["plan"]["fallback"]["disclosure_ref"] = ""
        with self.assertRaises(ValueError):
            evaluate(bad)
        bad = copy.deepcopy(value)
        bad["events"][3]["plan"]["fallback"] = {**fallback, "evidence_ref": "rewritten"}
        self.assertEqual("fail", evaluate(bad)["status"])
        bad = copy.deepcopy(value)
        bad["events"][3]["plan"].update(capability="available", result="success", receipt_ref="new-call")
        self.assertEqual("fail", evaluate(bad)["status"])

    def test_failed_sync_can_remain_text_in_state_and_trace_without_retry(self):
        from delivery_next import upgrade_state, next_runtime_action
        from delivery_state import validate_transition
        from test_delivery_state import state

        for failure in ("failed", "unknown"):
            with self.subTest(failure=failure):
                value = trace()
                for event in value["events"]:
                    if "plan" in event:
                        event["plan"]["capability"] = "available"
                first = value["events"][0]["plan"]
                first.update(result=failure, receipt_ref="sync-call-1")
                previous = upgrade_state(state())
                previous["host_sync"]["mode"] = "native"
                candidate = copy.deepcopy(previous)
                candidate["revision"] += 1
                candidate["host_sync"] = {
                    "mode": "text", "acknowledged_fingerprint": None,
                    "evidence_level": "controller_attested",
                    "fallback": {"reason": first["result"], "evidence_ref": first["receipt_ref"],
                                 "disclosure_ref": "start-T1"},
                }
                validate_transition(previous, candidate)
                resumed = upgrade_state(json.loads(json.dumps(candidate)))
                self.assertNotEqual("sync-plan", next_runtime_action(resumed, "verify-final")["action"])
                result = evaluate(value)
                self.assertEqual("pass", result["status"], result["violations"])
                self.assertEqual("text", result["display_mode"])
                self.assertEqual("uncovered", result["native_ui_status"])
                self.assertEqual("uncovered", result["release_status"])
                first["receipt_ref"] = None
                self.assertEqual("uncovered", evaluate(value)["status"])
                first["receipt_ref"] = "sync-call-1"
                value["events"][3]["plan"]["fallback_disclosed"] = False
                self.assertEqual("fail", evaluate(value)["status"])

    def test_missing_tool_or_a_success_does_not_authorize_skipping_an_available_tool(self):
        value = trace()
        value["events"][3]["plan"]["capability"] = "available"
        self.assertEqual("fail", evaluate(value)["status"])
        value["events"][0]["plan"].update(capability="available", result="success", receipt_ref="call-1")
        self.assertEqual("fail", evaluate(value)["status"])
        value["events"][0]["plan"].update(result="failed")
        value["events"][3]["plan"].update(result="success", receipt_ref="call-2")
        value["events"][4]["plan"]["capability"] = "available"
        self.assertEqual("fail", evaluate(value)["status"])

    def test_fallback_must_be_disclosed_for_missing_failed_or_unknown_tools(self):
        for capability, status in (("unavailable", "not_called"), ("unknown", "not_called"),
                                   ("available", "failed"), ("available", "unknown")):
            with self.subTest(capability=capability, status=status):
                value = trace()
                plan = value["events"][0]["plan"]
                plan.update(capability=capability, result=status, fallback_disclosed=False)
                if status in ("failed", "unknown"):
                    plan["receipt_ref"] = "sync-call-1"
                self.assertEqual("fail", evaluate(value)["status"])
                plan["fallback_disclosed"] = True
                result = evaluate(value)
                self.assertEqual("pass", result["status"])
                self.assertEqual("text", result["display_mode"])

    def test_contradictory_plan_observations_are_rejected(self):
        value = trace()
        value["events"][0]["plan"]["result"] = "success"
        with self.assertRaises(ValueError):
            evaluate(value)

    def test_regression_scenarios_and_cli_exit_status(self):
        root = Path(__file__).resolve().parents[1]
        cases = json.loads((root / "evals/step-visibility.json").read_text())["cases"]
        for case in cases:
            with self.subTest(case=case["id"]):
                observed = subprocess.run(
                    [sys.executable, str(root / "scripts/step_trace_eval.py"), "--input", "-"],
                    input=json.dumps(case["trace"]), capture_output=True, text=True, timeout=5,
                )
                self.assertEqual(0 if case["expected_status"] == "pass" else 1, observed.returncode)
                result = json.loads(observed.stdout)
                self.assertEqual(case["expected_status"], result["status"])
                self.assertEqual("uncovered", result["release_status"])

    def test_cli_rejects_invalid_or_oversized_input(self):
        script = str(Path(__file__).with_name("step_trace_eval.py"))
        for raw in ("not json", "{}", " " * 1_048_577):
            observed = subprocess.run([sys.executable, script], input=raw, capture_output=True,
                                      text=True, timeout=5)
            self.assertEqual(2, observed.returncode)
            self.assertFalse(observed.stdout)

    def test_visible_steps_pass_without_a_host_plan_tool(self):
        result = evaluate(trace())
        self.assertEqual("pass", result["status"])
        self.assertEqual([], result["violations"])
        self.assertEqual("uncovered", result["release_status"])
        self.assertEqual("fixture", result["evidence_level"])

    def test_hidden_reports_and_next_step_edits_before_report_fail(self):
        hidden = trace()
        hidden["events"][3]["visible"] = False
        early = trace()
        early["events"][3:5] = early["events"][4:5] + early["events"][3:4]
        skipped_start = trace()
        skipped_start["events"].pop(0)
        for value in (hidden, early, skipped_start):
            with self.subTest(events=value["events"]):
                self.assertEqual("fail", evaluate(value)["status"])

    def test_failed_verification_cannot_be_reported_done_or_advance(self):
        failed = trace()
        failed["events"][2]["result"] = "fail"
        self.assertEqual("fail", evaluate(failed)["status"])
        failed["events"][3]["result"] = "blocked"
        self.assertEqual("fail", evaluate(failed)["status"])
        failed["events"] = failed["events"][:4]
        self.assertEqual("pass", evaluate(failed)["status"])

    def test_verification_must_follow_the_last_edit(self):
        value = trace()
        value["events"].insert(3, {"step": "T1", "kind": "edit"})
        self.assertEqual("fail", evaluate(value)["status"])
        value["events"].insert(4, {"step": "T1", "kind": "verify", "result": "pass"})
        self.assertEqual("pass", evaluate(value)["status"])

    def test_resume_skips_completed_work_but_rejects_reexecution(self):
        value = trace()
        value["completed_before"] = ["T1"]
        value["events"] = step_events("T2")
        self.assertEqual("pass", evaluate(value)["status"])
        value["events"].insert(0, {"step": "T1", "kind": "edit"})
        self.assertEqual("fail", evaluate(value)["status"])

    def test_missing_observations_do_not_pass(self):
        for events in ([], step_events("T1")[:3]):
            value = trace()
            value["events"] = events
            self.assertEqual("uncovered", evaluate(value)["status"])

    def test_rejects_invalid_events_and_host_provenance_claims(self):
        for key, item in (("steps", ["T1", "T1"]), ("completed_before", ["T2"]),
                          ("schema_version", True), ("evidence_level", "host_observed"),
                          ("events", [{"step": "T1", "kind": "execute", "command": "never run"}])):
            value = trace()
            value[key] = item
            with self.subTest(key=key), self.assertRaises(ValueError):
                evaluate(value)

    def test_observed_trace_keeps_its_evidence_level_and_input_binding(self):
        value = trace()
        value["evidence_level"] = "evaluator_attested"
        before = copy.deepcopy(value)
        first = evaluate(value)
        self.assertEqual(before, value)
        self.assertEqual("evaluator_attested", first["evidence_level"])
        self.assertEqual("uncovered", first["release_status"])
        value["events"][3]["visible"] = False
        self.assertNotEqual(first["trace_fingerprint"], evaluate(value)["trace_fingerprint"])


if __name__ == "__main__":
    unittest.main()
