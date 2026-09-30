import tempfile
import unittest
import sys
from unittest.mock import patch
from pathlib import Path

import interaction_replay as replay


GOOD = 'def normalize_status(value):\n    return "" if value is None else value.strip().lower()\n'


class Session:
    def __init__(self, workspace, *, repair=True, questions=0, status="completed"):
        self.workspace = workspace
        self.repair = repair
        self.questions = questions
        self.status = status
        self.prompts = []
        self.closed = False

    def turn(self, prompt):
        self.prompts.append(prompt)
        if self.repair[len(self.prompts)-1] if isinstance(self.repair, list) else self.repair:
            (self.workspace / "status_normalizer.py").write_text(GOOD)
        return {"task_id": "same-thread", "turn_id": str(len(self.prompts)),
                "status": self.status, "questions": self.questions[len(self.prompts)-1]
                if isinstance(self.questions, list) else self.questions,
                "transcript_fingerprint": "a" * 64}

    def close(self):
        self.closed = True


class InteractionReplayTest(unittest.TestCase):
    def run_case(self, case="review-defect", **options):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, **options.pop("session_options", {}))
            result = replay.replay(case, workspace, session, **options)
            return result, session

    def test_injected_review_defect_requires_repair_in_the_same_thread(self):
        result, session = self.run_case()
        self.assertEqual("pass", result["result"])
        self.assertEqual([0, 1], [turn["injected_defect"] for turn in result["turns"]])
        self.assertEqual(1, len({turn["task_id"] for turn in result["turns"]}))
        self.assertTrue(result["turns"][1]["writes"])
        self.assertTrue(session.closed)

    def test_guided_findings_only_fails_but_controlled_path_repairs_once(self):
        result, _ = self.run_case(session_options={"repair": [True, False]})
        self.assertEqual("fail", result["result"])
        result, session = self.run_case(controlled=True, session_options={"repair": [True, False, True]})
        self.assertEqual("pass", result["result"])
        self.assertEqual(1, result["automatic_repairs"])
        self.assertLessEqual(len(session.prompts), 3)

    def test_clean_review_needs_no_write(self):
        result, _ = self.run_case("clean-review", session_options={"repair": False})
        self.assertEqual("pass", result["result"])
        self.assertFalse(any(turn["writes"] for turn in result["turns"]))

    def test_resolved_decision_cannot_be_reasked(self):
        result, _ = self.run_case("known-decision", session_options={"questions": 1})
        self.assertEqual("fail", result["result"])

    def test_new_business_decision_requires_a_question_and_no_write(self):
        result, _ = self.run_case("new-decision", session_options={"repair": False, "questions": [0, 1]})
        self.assertEqual("pass", result["result"])
        result, _ = self.run_case("new-decision", session_options={"repair": False})
        self.assertEqual("fail", result["result"])

    def test_host_failure_is_uncovered_and_always_closes(self):
        result, session = self.run_case(session_options={"status": "failed"})
        self.assertEqual("uncovered", result["result"])
        self.assertTrue(session.closed)

    def test_changed_host_identity_is_not_a_same_thread_result(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(Path(directory))
            original = session.turn
            def turn(prompt):
                value = original(prompt)
                value["task_id"] = value["turn_id"]
                return value
            session.turn = turn
            result = replay.replay("review-defect", Path(directory), session)
        self.assertEqual("uncovered", result["result"])

    def test_no_progress_stops_instead_of_reopening_budget(self):
        result, session = self.run_case("no-progress", controlled=True,
                                        session_options={"repair": False})
        self.assertEqual("blocked", result["result"])
        self.assertEqual(1, result["automatic_repairs"])
        self.assertEqual(2, len(session.prompts))

    def test_no_progress_frozen_verifier_cannot_be_fixed_by_candidate(self):
        result, session = self.run_case("no-progress", controlled=True)
        self.assertEqual("blocked", result["result"])
        self.assertEqual(2, len(session.prompts))

    def test_invalid_case_is_rejected_before_host_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(Path(directory))
            with self.assertRaises(ValueError):
                replay.replay("unknown", Path(directory), session)
            self.assertEqual([], session.prompts)

    def test_capture_is_explicit_and_host_exception_is_uncovered(self):
        result, _ = self.run_case(capture_synthetic=True)
        self.assertEqual(4, len(result["synthetic_trajectory"]))
        with tempfile.TemporaryDirectory() as directory:
            session = Session(Path(directory))
            with patch.object(session, "turn", side_effect=ValueError("timeout")):
                result = replay.replay("review-defect", Path(directory), session)
            self.assertEqual("uncovered", result["result"])
            self.assertTrue(session.closed)

    def test_nonempty_workspace_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            (workspace / "existing").touch()
            with self.assertRaisesRegex(ValueError, "empty"):
                replay.replay("clean-review", workspace, Session(workspace))

    def test_cli_is_opt_in_and_has_bounded_samples(self):
        for options in ([], ["--allow-execute", "--samples", "4"],
                        ["--allow-execute", "--timeout-seconds", "nan"]):
            with patch.object(sys, "argv", ["replay", "--policy", "unused", *options]), \
                    patch.object(replay, "CodexSession") as session, \
                    patch("sys.stderr"), self.assertRaises(SystemExit):
                replay.main()
            session.assert_not_called()

    def test_cli_scores_expected_stop_and_does_not_retry_uncovered(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = Path(directory) / "policy"
            policy.write_text("policy")
            for outcome, expected_calls, exit_code in (("blocked", 3, 0), ("uncovered", 1, 1)):
                with patch.object(sys, "argv", ["replay", "--policy", str(policy), "--case",
                                  "no-progress", "--controlled", "--allow-execute"]), \
                        patch.object(replay, "CodexSession") as session, \
                        patch.object(replay, "replay", return_value={"result": outcome}) as run, \
                        patch("builtins.print"):
                    self.assertEqual(exit_code, replay.main())
                    self.assertEqual(expected_calls, run.call_count)


if __name__ == "__main__":
    unittest.main()
