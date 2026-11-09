import tempfile
import json
import subprocess
import shlex
import unittest
import sys
from unittest.mock import MagicMock, patch
from pathlib import Path

import interaction_replay as replay


GOOD = 'def normalize_status(value):\n    return "" if value is None else value.strip().lower()\n'
LOCAL_TESTS = '''import unittest
from status_normalizer import normalize_status as normalize
class Behavior(unittest.TestCase):
    def test_none(self): self.assertEqual('', normalize(None))
    def test_text(self): self.assertEqual('active', normalize(' Active '))
    def test_empty(self): self.assertEqual('', normalize('  '))
    def test_invalid(self):
        with self.assertRaises(AttributeError): normalize(1)
'''
DECISION_RESPONSES = {
    "known-decision": [(), ()],
    "new-decision": [(), ("number_handling",)],
    "independent-decisions": [("none_result", "whitespace"), ()],
    "dependent-decisions": [("support_numbers",), ("decimal_format",)],
}


class Session:
    def __init__(self, workspace, *, repair=True, questions=0, status="completed", responses=None,
                 tdd=False, unittest_flags=()):
        self.workspace = workspace
        self.repair = repair
        self.questions = questions
        self.status = status
        self.prompts = []
        self.closed = False
        self.responses = responses or []
        self.last_text = ""
        self.tdd, self.last_items = tdd, []
        self.unittest_flags = unittest_flags

    def turn(self, prompt):
        self.prompts.append(prompt)
        self.last_text = self.responses[len(self.prompts)-1] if len(self.prompts) <= len(self.responses) else ""
        def check():
            argv = [sys.executable, '-m', 'unittest', 'test_status_normalizer', *self.unittest_flags]
            result = subprocess.run(argv, cwd=self.workspace, capture_output=True, text=True, timeout=5)
            return {'type': 'commandExecution', 'command': shlex.join(argv), 'cwd': str(self.workspace),
                    'status': 'completed', 'exitCode': result.returncode,
                    'aggregatedOutput': result.stdout + result.stderr}
        if self.tdd:
            (self.workspace / 'test_status_normalizer.py').write_text(LOCAL_TESTS)
            self.last_items = [check()]
        if self.repair[len(self.prompts)-1] if isinstance(self.repair, list) else self.repair:
            (self.workspace / "status_normalizer.py").write_text(GOOD)
        if self.tdd:
            self.last_items += [{'type': 'fileChange', 'status': 'completed',
                                 'changes': [{'path': str(self.workspace / 'status_normalizer.py')}]}, check()]
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
            session_options = options.pop("session_options", {})
            session_options.setdefault("responses", [json.dumps({"decision_requests": [
                {"id": key, "recommendation": "synthetic recommendation"} for key in keys
            ]}) for keys in DECISION_RESPONSES.get(case, [])])
            session = Session(workspace, **session_options)
            result = replay.replay(case, workspace, session, **options)
            return result, session

    def test_injected_review_defect_requires_repair_in_the_same_thread(self):
        result, session = self.run_case()
        self.assertEqual("pass", result["result"])
        self.assertEqual([0, 1], [turn["injected_defect"] for turn in result["turns"]])
        self.assertEqual(1, len({turn["task_id"] for turn in result["turns"]}))
        self.assertTrue(result["turns"][1]["writes"])
        self.assertTrue(session.closed)

    def test_verifier_preflight_rejects_a_broken_environment_before_host_calls(self):
        with patch.object(replay, "judge", return_value={"exit_code": 2, "outcome": "uncovered"}):
            result, session = self.run_case(controlled=True)
        self.assertEqual("uncovered", result["result"])
        self.assertEqual("environment_invalid", result["failure_kind"])
        self.assertEqual([], session.prompts)
        self.assertEqual(0, result["automatic_repairs"])
        self.assertTrue(session.closed)

    def test_judge_cleans_up_candidate_children_on_success_and_timeout(self):
        import os
        import signal
        import time
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                workspace = root / 'workspace'
                workspace.mkdir()
                pid_file = root / 'child.pid'
                source = ('import subprocess,sys,time\nfrom pathlib import Path\n'
                    'child=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"],'
                    'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n'
                    f'Path({str(pid_file)!r}).write_text(str(child.pid))\n'
                    + ('time.sleep(30)\n' if timeout else '') + GOOD)
                (workspace / 'status_normalizer.py').write_text(source)
                child_pid = None
                try:
                    try:
                        result = replay.judge(workspace, deadline=time.monotonic() + 1 if timeout else None)
                    except subprocess.TimeoutExpired:
                        result = {'outcome': 'uncovered'}
                    child_pid = int(pid_file.read_text())
                    self.assertEqual('uncovered' if timeout else 'pass', result['outcome'])
                    deadline = time.monotonic() + 2
                    while True:
                        status = subprocess.run(['ps', '-p', str(child_pid), '-o', 'stat='],
                                                capture_output=True, text=True, timeout=2).stdout.strip()
                        if not status or status.startswith('Z') or time.monotonic() >= deadline:
                            break
                        time.sleep(.02)
                    self.assertTrue(not status or status.startswith('Z'), f'candidate child still running: {status}')
                finally:
                    if child_pid is not None:
                        try: os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError: pass

    def test_verifier_preflight_requires_both_positive_and_negative_controls(self):
        for outcome, code in (("pass", 0), ("fail", 1)):
            with self.subTest(outcome=outcome), patch.object(
                replay, "judge", return_value={"exit_code": code, "outcome": outcome}
            ):
                result, session = self.run_case(controlled=True)
                self.assertEqual("uncovered", result["result"])
                self.assertEqual([], session.prompts)

    def test_product_judge_accepts_a_relative_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace'
            workspace.mkdir()
            (workspace / 'product-decisions.json').write_text(replay.PRODUCT_GOOD)
            (workspace / 'product-inputs.json').write_text(json.dumps(replay.PRODUCT_INPUTS))
            code = (f'import sys; sys.path.insert(0, {str(Path(replay.__file__).parent)!r}); '
                    'import json,interaction_replay as r; from pathlib import Path; '
                    'print(json.dumps(r.judge(Path("workspace"),product=True)))')
            result = subprocess.run([sys.executable, '-B', '-c', code], cwd=root,
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual('pass', json.loads(result.stdout)['outcome'])

    def test_verifier_execution_error_does_not_consume_a_business_repair(self):
        original = replay.judge
        calls = 0

        def unavailable_after_preflight(*args, **kwargs):
            nonlocal calls
            calls += 1
            return original(*args, **kwargs) if calls <= 2 else {
                "exit_code": 2, "outcome": "uncovered",
            }

        with patch.object(replay, "judge", side_effect=unavailable_after_preflight):
            result, session = self.run_case(controlled=True)
        self.assertEqual("uncovered", result["result"])
        self.assertEqual("evidence_unavailable", result["failure_kind"])
        self.assertEqual(0, result["automatic_repairs"])
        self.assertEqual(1, len(session.prompts))

    def test_verification_uses_only_the_session_remaining_budget(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, tdd=True)
            session.deadline = time.monotonic() + 5
            with patch.object(replay, "_run_command", wraps=replay._run_command) as run:
                result = replay.replay("simple-local-fix", workspace, session)
            self.assertEqual("pass", result["result"])
            self.assertEqual(5, run.call_count)
            self.assertTrue(all(0 < call.args[2] <= 5 for call in run.call_args_list))

    def test_expired_budget_stops_before_verification_or_a_model_call(self):
        import time
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace)
            session.deadline = time.monotonic() - 1
            with patch.object(replay.subprocess, "run", wraps=replay.subprocess.run) as run:
                result = replay.replay("simple-local-fix", workspace, session, controlled=True)
            self.assertEqual("uncovered", result["result"])
            self.assertEqual(0, result["automatic_repairs"])
            self.assertEqual([], session.prompts)
            run.assert_not_called()
            self.assertTrue(session.closed)

    def test_product_case_repairs_without_an_additional_user_message(self):
        self.assertIn("product-decisions", replay.CASES)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, repair=False)
            turn = session.turn

            def repair_product(prompt):
                observed = turn(prompt)
                if len(session.prompts) == 2:
                    (workspace / "product-decisions.json").write_text(replay.PRODUCT_GOOD)
                return observed

            session.turn = repair_product
            result = replay.replay("product-decisions", workspace, session, controlled=True)
        self.assertEqual("pass", result["result"])
        self.assertEqual(1, result["automatic_repairs"])
        self.assertEqual(["execute-inline"], [item["action"] for item in result["controller_actions"]])
        self.assertEqual(["user", "controller"], [item["prompt_origin"] for item in result["turns"]])
        self.assertEqual(1, len({item["task_id"] for item in result["turns"]}))
        self.assertEqual(2, len(session.prompts))
        self.assertNotIn("user_reminders", result)
        self.assertTrue(session.closed)

    def test_product_case_checks_unasked_questions_and_unsupported_decisions_together(self):
        self.assertIn("product-decisions", replay.CASES)
        import json
        good = json.loads(replay.PRODUCT_GOOD)
        mutations = (
            ("unresolved", "questions", ["approval-threshold", "retry-approval", "manager-missing"]),
            ("unresolved", "retry_approval", "waived"),
            ("explicit-manager-missing", "questions", []),
            ("sufficient", "questions", ["approval-threshold"]),
        )
        for case, field, value in mutations:
            with self.subTest(case=case, field=field), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                (workspace / "product-inputs.json").write_text(json.dumps(replay.PRODUCT_INPUTS))
                (workspace / "product-decisions.json").write_text(replay.PRODUCT_GOOD)
                self.assertEqual("pass", replay.judge(workspace, product=True)["outcome"])
                content = json.loads(json.dumps(good))
                content[case][field] = value
                (workspace / "product-decisions.json").write_text(json.dumps(content))
                result = replay.judge(workspace, product=True)
                self.assertEqual("fail", result["outcome"])

    def test_product_failed_experiment_stops_without_resetting_its_single_repair_budget(self):
        self.assertIn("product-decisions", replay.CASES)
        result, session = self.run_case("product-decisions", controlled=True,
                                        session_options={"repair": False})
        self.assertEqual("blocked", result["result"])
        self.assertEqual("behavior_failed", result["failure_kind"])
        self.assertEqual(["execute-inline", "block"],
                         [item["action"] for item in result["controller_actions"]])
        self.assertEqual(2, len(session.prompts))
        self.assertTrue(session.closed)

    def test_product_case_rejects_extra_business_rules(self):
        import json
        for case in replay.PRODUCT_INPUTS:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                (workspace / "product-inputs.json").write_text(json.dumps(replay.PRODUCT_INPUTS))
                (workspace / "product-decisions.json").write_text(replay.PRODUCT_GOOD)
                self.assertEqual("pass", replay.judge(workspace, product=True)["outcome"])
                draft = json.loads(replay.PRODUCT_GOOD)
                draft[case]["retry_requires_approval"] = False
                (workspace / "product-decisions.json").write_text(json.dumps(draft))
                self.assertEqual("fail", replay.judge(workspace, product=True)["outcome"])

    def test_product_mutation_checks_detect_a_removed_business_guard(self):
        self.assertTrue(hasattr(replay, "PRODUCT_JUDGE"))
        guards = (
            '    assert draft["retry_approval"] == source["retry_approval"], key\n',
            '    assert sorted(draft["questions"]) == sorted(expected), key\n',
        )
        for guard in guards:
            with self.subTest(guard=guard), patch.object(
                replay, "PRODUCT_JUDGE", replay.PRODUCT_JUDGE.replace(guard, "")
            ):
                result = unittest.TestResult()
                InteractionReplayTest(
                    "test_product_case_checks_unasked_questions_and_unsupported_decisions_together"
                ).run(result)
                self.assertFalse(result.wasSuccessful(), "a missing guard escaped the mutation checks")

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

    def test_full_flow_review_rejects_a_scan_only_fix_despite_a_success_claim(self):
        self.assertIn("full-flow-review", replay.CASES)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, repair=False)
            session.last_text = "完整流程已审查，扫描正常，全部无问题。"
            result = replay.replay("full-flow-review", workspace, session)
        self.assertEqual("fail", result["result"])
        self.assertNotEqual(0, result["turns"][-1]["verification"]["exit_code"])
        self.assertEqual(0, result["automatic_repairs"])
        self.assertTrue(session.closed)

    def test_full_flow_review_passes_only_after_the_shared_rule_is_fixed(self):
        self.assertIn("full-flow-review", replay.CASES)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, repair=False)
            original_turn = session.turn

            def repair_shared_rule(prompt):
                path = workspace / "configuration.py"
                path.write_text(path.read_text().replace("return config\n", "return validate(config)\n"))
                return original_turn(prompt)

            session.turn = repair_shared_rule
            result = replay.replay("full-flow-review", workspace, session)
        self.assertEqual("pass", result["result"])
        self.assertEqual(0, result["turns"][-1]["verification"]["exit_code"])
        self.assertEqual(1, len(session.prompts))
        self.assertTrue(session.closed)

    def test_full_flow_judge_catches_each_unchecked_sibling_and_switch_boundary(self):
        self.assertIn("full-flow-review", replay.CASES)
        bypasses = (
            "def scan(configs): return configs\n",
            "def probe(config): return config\n",
            "def manual(config): return config\n",
            "def save(config, path): path.write_text(json.dumps(config))\n",
            "def restore(path): return json.loads(path.read_text())\n",
            "def start(config): return config['command']\n",
            "def select(current, candidate): return candidate\n",
        )
        for bypass in bypasses:
            with self.subTest(bypass=bypass), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, repair=False)

                def partial_repair(prompt):
                    path = workspace / "configuration.py"
                    source = path.read_text().replace("return config\n", "return validate(config)\n")
                    path.write_text(source + "\n" + bypass)
                    return {"status": "completed", "task_id": "same-thread"}

                session.turn = partial_repair
                result = replay.replay("full-flow-review", workspace, session)
                self.assertEqual("fail", result["result"])
                self.assertTrue(session.closed)

    def test_full_flow_review_host_failure_is_uncovered_without_a_retry(self):
        self.assertIn("full-flow-review", replay.CASES)
        result, session = self.run_case("full-flow-review", controlled=True,
                                        session_options={"repair": False, "status": "failed"})
        self.assertEqual("uncovered", result["result"])
        self.assertEqual(0, result["automatic_repairs"])
        self.assertEqual(1, len(session.prompts))
        self.assertTrue(session.closed)

    def test_full_flow_controlled_repair_keeps_its_rule_and_single_attempt(self):
        for repair, expected in ((True, "pass"), (False, "blocked")):
            with self.subTest(repair=repair), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, repair=False)
                original_turn = session.turn

                def repair_once(prompt):
                    observed = original_turn(prompt)
                    if repair and len(session.prompts) == 2:
                        path = workspace / "configuration.py"
                        path.write_text(path.read_text().replace("return config\n", "return validate(config)\n"))
                    return observed

                session.turn = repair_once
                result = replay.replay("full-flow-review", workspace, session, controlled=True)
                self.assertEqual(expected, result["result"])
                self.assertEqual(1, result["automatic_repairs"])
                self.assertEqual(2, len(session.prompts))
                self.assertIn("command", session.prompts[-1])
                self.assertNotIn("None must return", session.prompts[-1])
                self.assertTrue(session.closed)

    def test_simple_local_fix_keeps_one_turn_and_the_existing_small_fixture(self):
        self.assertIn("simple-local-fix", replay.CASES)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, tdd=True)
            result = replay.replay("simple-local-fix", workspace, session)
            self.assertEqual({"status_normalizer.py", "test_status_normalizer.py"},
                             {path.name for path in workspace.iterdir() if path.is_file()})
        self.assertEqual("pass", result["result"])
        self.assertEqual(1, len(result["turns"]))
        self.assertEqual(0, result["automatic_repairs"])
        self.assertTrue(session.closed)

    def test_simple_local_fix_rejects_unrequested_flow_files(self):
        self.assertIn("simple-local-fix", replay.CASES)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace)
            original_turn = session.turn

            def expand_scope(prompt):
                (workspace / "flow-checklist.md").write_text("unrequested workflow inventory")
                return original_turn(prompt)

            session.turn = expand_scope
            result = replay.replay("simple-local-fix", workspace, session, controlled=True)
        self.assertEqual("fail", result["result"])
        self.assertEqual("unexpected_local_artifacts", result["reason"])
        self.assertEqual(0, result["automatic_repairs"])
        self.assertEqual(1, len(session.prompts))

    def test_local_fix_rejects_missing_tests_and_unobserved_tdd(self):
        for tests in (None, "# empty test\n", "import unittest\n"):
            with self.subTest(tests=tests), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace)
                original = session.turn

                def fix_without_tdd(prompt):
                    if tests is not None:
                        (workspace / "test_status_normalizer.py").write_text(tests)
                    return original(prompt)

                session.turn = fix_without_tdd
                result = replay.replay("simple-local-fix", workspace, session)
                self.assertNotEqual("pass", result["result"])
                self.assertEqual(0, result["automatic_repairs"])

    def test_simple_local_fix_allows_its_regression_test_and_runner_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, tdd=True)
            original_turn = session.turn

            def fix_with_test(prompt):
                (workspace / "test_status_normalizer.py").write_text(LOCAL_TESTS)
                cache = workspace / ".pytest_cache"
                cache.mkdir()
                (cache / "README.md").write_text("runner cache")
                return original_turn(prompt)

            session.turn = fix_with_test
            result = replay.replay("simple-local-fix", workspace, session)
        self.assertEqual("pass", result["result"])
        self.assertEqual(1, len(session.prompts))

    def test_local_tdd_rejects_reordered_missing_and_wrong_workspace_events(self):
        for fault in ('no-red', 'no-green', 'green-first', 'no-change', 'wrong-cwd', 'zero-tests',
                      'test-after-green', 'late-failure', 'malformed', 'nonstring-output', 'changed-after-events'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, tdd=True)
                turn = session.turn

                def damaged(prompt):
                    result = turn(prompt)
                    items = session.last_items
                    if fault == 'no-red': items.pop(0)
                    elif fault == 'no-green': items.pop()
                    elif fault == 'green-first': items[:] = list(reversed(items))
                    elif fault == 'no-change': items.pop(1)
                    elif fault == 'wrong-cwd': items[0]['cwd'] = '/'
                    elif fault == 'zero-tests': items[-1]['aggregatedOutput'] = 'Ran 0 tests in 0.001s\n\nOK\n'
                    elif fault == 'test-after-green':
                        items.append({'type': 'fileChange', 'status': 'completed',
                                      'changes': [{'path': str(workspace / 'test_status_normalizer.py')}]})
                    elif fault == 'late-failure': items.append(dict(items[0]))
                    elif fault == 'malformed': items.append(None)
                    elif fault == 'nonstring-output': items[0]['aggregatedOutput'] = {'unexpected': True}
                    else:
                        (workspace / 'status_normalizer.py').write_text(GOOD.replace(
                            'else value.strip().lower()', 'else value.strip().lower() if isinstance(value, str) else str(value)'))
                    return result

                session.turn = damaged
                self.assertNotEqual('pass', replay.replay('simple-local-fix', workspace, session)['result'])

    def test_local_tdd_rejects_a_candidate_test_that_cannot_detect_the_original_bug(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            session = Session(workspace, tdd=True)
            turn = session.turn

            def vacuous(prompt):
                result = turn(prompt)
                (workspace / 'test_status_normalizer.py').write_text(
                    'import unittest\nclass Empty(unittest.TestCase):\n def test_empty(self): self.assertTrue(True)\n')
                return result

            session.turn = vacuous
            self.assertEqual('fail', replay.replay('simple-local-fix', workspace, session)['result'])

    def test_local_tdd_accepts_verbosity_and_preserves_unknown_observation_budget(self):
        for flags, expected in ((('-v',), 'pass'), (('-q',), 'pass'), (('--buffer',), 'uncovered')):
            with self.subTest(flags=flags), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, tdd=True, unittest_flags=flags)
                result = replay.replay('simple-local-fix', workspace, session, controlled=True)
                self.assertEqual(expected, result['result'])
                self.assertEqual(0, result['automatic_repairs'])

    def test_malformed_host_command_fields_are_uncovered_without_repair(self):
        for key, value in (('command', {'bad': True}), ('command', None),
                           ('command', ''), ('command', '   '), ('command', "'unclosed"), ('command', '\x00'),
                           ('status', {'bad': True}), ('status', 'declined'),
                           ('cwd', {'bad': True}), ('cwd', 1),
                           ('aggregatedOutput', None), ('aggregatedOutput', {'bad': True}),
                           ('exitCode', True), ('exitCode', '1')):
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, tdd=True)
                turn = session.turn

                def damaged(prompt):
                    result = turn(prompt)
                    session.last_items[0][key] = value
                    if key == 'cwd': session.last_items[0]['command'] += ' --buffer'
                    return result

                session.turn = damaged
                result = replay.replay('simple-local-fix', workspace, session, controlled=True)
                self.assertEqual('uncovered', result['result'])
                self.assertEqual(0, result['automatic_repairs'])
                self.assertTrue(session.closed)

    def test_local_test_exit_code_collision_does_not_claim_tool_unavailability(self):
        for code in (124, 127):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                session = Session(workspace, tdd=True)
                turn = session.turn

                def bad_test(prompt):
                    result = turn(prompt)
                    (workspace / 'test_status_normalizer.py').write_text(f'raise SystemExit({code})\n')
                    return result

                session.turn = bad_test
                result = replay.replay('simple-local-fix', workspace, session)
                self.assertEqual('fail', result['result'])
                self.assertEqual('behavior_failed', result['failure_kind'])

    def test_question_punctuation_does_not_reject_a_verified_implementation(self):
        result, _ = self.run_case("known-decision", session_options={
            "repair": [False, True], "questions": [1, 2],
        })
        self.assertEqual("pass", result["result"])

    def test_new_business_decision_requires_no_write_regardless_of_punctuation(self):
        for questions in ([0, 0], [0, 1], [2, 3]):
            with self.subTest(questions=questions):
                result, _ = self.run_case("new-decision", session_options={
                    "repair": False, "questions": questions,
                })
                self.assertEqual("pass", result["result"])

    def test_discussion_rejects_empty_missing_extra_and_unrecommended_decisions(self):
        cases = {
            "new-decision": {"repair": False},
            "dependent-decisions": {"repair": False},
            "independent-decisions": {"repair": [False, True]},
        }
        for case, options in cases.items():
            with self.subTest(case=case):
                result, session = self.run_case(case, controlled=True,
                    session_options={**options, "responses": ["", ""]})
                self.assertEqual("fail", result["result"])
                self.assertEqual(0, result["automatic_repairs"])
                self.assertTrue(session.closed)
        for requests in ([], [{"id": "decimal_format", "recommendation": "fixed"}],
                         [{"id": "support_numbers", "recommendation": ""}],
                         [{"id": "support_numbers", "recommendation": "yes"}] * 2,
                         [{"id": "support_numbers", "recommendation": "yes"},
                          {"id": "decimal_format", "recommendation": "fixed"}]):
            with self.subTest(requests=requests):
                result, _ = self.run_case("dependent-decisions", session_options={
                    "repair": False, "responses": [json.dumps({"decision_requests": requests})],
                })
                self.assertEqual("fail", result["result"])

    def test_discussion_requires_each_checkpoint_and_accepts_plain_recommendations(self):
        for response in ("not-json", "[]", "null", '{"decision_requests": null}',
                         '{"decision_requests": [{"id": "decimal_format", "recommendation": 1}]}'):
            with self.subTest(response=response):
                result, _ = self.run_case("dependent-decisions", session_options={
                    "repair": False, "responses": [json.dumps({"decision_requests": [
                        {"id": "support_numbers", "recommendation": "支持数字"}]}), response],
                })
                self.assertEqual("fail", result["result"])
                self.assertEqual(2, len(result["turns"]))

    def test_implementation_does_not_reopen_resolved_decisions(self):
        for case, first in (('known-decision', []), ('independent-decisions', [
                {'id': 'none_result', 'recommendation': '空字符串'},
                {'id': 'whitespace', 'recommendation': '保留 strip/lower'}])):
            with self.subTest(case=case):
                result, _ = self.run_case(case, session_options={
                    'repair': [False, True], 'responses': [json.dumps({'decision_requests': first}),
                        json.dumps({'decision_requests': [{'id': 'none_result', 'recommendation': '再次确认'}]})],
                })
                self.assertEqual('fail', result['result'])

    def test_decision_receipt_uses_final_host_answer_with_legacy_phase_compatibility(self):
        import time
        from host_bridge import CodexSession
        for phase, expected in (('final_answer', 'pass'), (None, 'pass'), ('commentary', 'fail')):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                server = MagicMock()
                server.request.side_effect = [{'thread': {'id': 'same'}},
                                              {'turn': {'id': 'one'}}, {'turn': {'id': 'two'}}]
                server.turn_statuses = {'one': 'completed', 'two': 'completed'}
                server.turn_items = {turn: [
                    {'type': 'agentMessage', 'phase': 'commentary', 'text': '正在核对已决定事项。'},
                    {'type': 'agentMessage', 'phase': 'partial_answer', 'text': '核对中。'},
                    {'type': 'agentMessage', 'phase': phase,
                     'text': json.dumps({'decision_requests': requests})},
                ] for turn, requests in [('one', []), ('two', [
                    {'id': 'number_handling', 'recommendation': '拒绝数字，保留字符串接口'}])]}
                with patch('host_bridge._CodexAppServer', return_value=server):
                    session = CodexSession(workspace, 'synthetic policy', deadline=time.monotonic() + 10)
                    result = replay.replay('new-decision', workspace, session)
                self.assertEqual(expected, result['result'])
                server.close.assert_called_once()

    def test_clarification_then_implementation_keeps_writes_within_authorization(self):
        result, session = self.run_case("independent-decisions", session_options={
            "repair": [False, True], "questions": [2, 0],
        })
        self.assertEqual("pass", result["result"])
        self.assertEqual(2, len(session.prompts))
        for questions in ([0, 0], [1, 0], [2, 1]):
            with self.subTest(questions=questions):
                result, _ = self.run_case("independent-decisions", session_options={
                    "repair": [False, True], "questions": questions,
                })
                self.assertEqual("pass", result["result"])

    def test_discussion_checkpoints_remain_read_only_regardless_of_punctuation(self):
        result, _ = self.run_case("dependent-decisions", session_options={
            "repair": False, "questions": [1, 1],
        })
        self.assertEqual("pass", result["result"])
        for questions in ([0, 0], [2, 1], [1, 0]):
            with self.subTest(questions=questions):
                result, _ = self.run_case("dependent-decisions", session_options={
                    "repair": False, "questions": questions,
                })
                self.assertEqual("pass", result["result"])

    def test_read_only_checkpoints_reject_writes_and_stop_without_repair(self):
        for case in ("clean-review", "new-decision", "known-decision",
                     "independent-decisions", "dependent-decisions"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as directory:
                session = Session(Path(directory), repair=False)
                turn = session.turn
                def write_during_discussion(prompt):
                    observed = turn(prompt)
                    (Path(directory) / "unauthorized.py").write_text("changed\n")
                    return observed
                with patch.object(session, "turn", side_effect=write_during_discussion):
                    result = replay.replay(case, Path(directory), session, controlled=True)
                self.assertEqual("fail", result["result"])
                self.assertEqual(0, result["automatic_repairs"])
                self.assertEqual(1, len(session.prompts))
                self.assertTrue(session.closed)

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
