"""Regression checks for format failures across the runner/state boundary."""
import copy
import contextlib
import io
import json
import unittest
from unittest.mock import Mock, patch

from delivery_state import _validate_runner_record
from role_dispatch import plan_dispatch
from role_result import result_from_output
from runner_contract import bind_role_result, fingerprint, freeze_launch, role_results_complete
from runner_lifecycle import _execute_and_complete, review_request_binding, run_dispatch
import test_runner_lifecycle as fixtures
from test_runner_lifecycle import flow_state, managed_state, review_fingerprint, review_request, review_response
from test_runner_contract import profile as api_profile
from runner_launch import plan_dispatch_launch


def receipt(launch):
    value = {
        'schema_version': 1, 'runner_id': launch['runner_id'],
        'launch_fingerprint': launch['launch_fingerprint'], 'status': 'completed', 'exit_code': 0,
        'stdout_fingerprint': 'a' * 64, 'stderr_fingerprint': 'b' * 64,
        'requested_model': launch['profile']['effective']['model'],
        'requested_reasoning_effort': launch['profile']['effective']['reasoning_effort'],
    }
    return {**value, 'receipt_fingerprint': fingerprint(value)}


def conclusion(launch, text):
    return bind_role_result(launch, receipt(launch), result_from_output(
        launch, {'status': 'available', 'content': text},
    ))


class MultiModelRecoveryTest(unittest.TestCase):
    setUp = fixtures.RunnerLifecycleTest.setUp
    tearDown = fixtures.RunnerLifecycleTest.tearDown

    def launches(self):
        dispatch = plan_dispatch(self.profiles, flow_state())
        old = plan_dispatch_launch(dispatch, 'Original prompt', workspace=self.workspace)
        failed = conclusion(old, '{"findings":[],"next_action":"bad"}')
        new = freeze_launch(old['profile'], 'Corrected format instruction', {
            **old['configuration'], 'recovery_of': old['launch_fingerprint'],
        })
        return old, failed, new

    def test_typed_reviewer_errors_preserve_completed_transport_and_diagnostics(self):
        dispatch = plan_dispatch(self.profiles, {
            **flow_state(), 'evidence': 'sufficient', 'implementation': 'complete',
            'verification': 'passed', 'review': 'pending',
        })
        request = review_request()
        launch = plan_dispatch_launch(dispatch, 'Review', workspace=self.workspace,
                                      review_request=request,
                                      review_request_fingerprint=review_fingerprint(request))
        original = receipt(launch)
        for field, value in [('axis', []), ('phase', []), ('mode', {}), ('status', [])]:
            with self.subTest(field=field):
                payload = json.loads(review_response(request)); payload[field] = value
                def execute(*_args, **_kwargs):
                    return {'receipt': original, 'output': {
                        'status': 'available', 'content': json.dumps(payload),
                    }}
                observed, result = _execute_and_complete(launch, 'Review', request, execute, False)
                self.assertEqual('completed', observed['status'])
                self.assertEqual(original['stdout_fingerprint'], observed['stdout_fingerprint'])
                self.assertEqual('invalid', result['status'])
                self.assertIn(field, result['diagnostic'])

    def test_lifecycle_reports_invalid_result_as_blocked_without_losing_receipt(self):
        dispatch = plan_dispatch(self.profiles, flow_state())
        def execute(launch, *_args, **_kwargs):
            return {'receipt': receipt(launch), 'output': {'status': 'available', 'content': 'not json'}}
        result = run_dispatch(self.arguments, dispatch, 'Collect',
                              load=lambda _: {'revision': 7, 'workspace': str(self.workspace)},
                              append=lambda args, *_: args.expected_revision + 1, execute=execute)
        self.assertEqual('blocked', result['status'])
        self.assertEqual('completed', result['result']['status'])
        self.assertEqual('invalid_json', result['role_result']['reason'])

    def test_decoder_resource_and_unicode_errors_keep_the_completed_receipt(self):
        dispatch = plan_dispatch(self.profiles, flow_state())
        payloads = ['{"findings":[],"next_action":' + '1' * 5000 + '}',
                    '[' * 2000 + '0' + ']' * 2000,
                    '{"findings":[{"summary":"\\ud800","evidence":[{"kind":"file",'
                    '"reference":"app.py:1","content_fingerprint":"' + 'a' * 64 +
                    '"}]}],"next_action":"continue"}']
        for payload in payloads:
            with self.subTest(payload_size=len(payload)):
                records = []
                def execute(launch, *_args, **_kwargs):
                    return {'receipt': receipt(launch), 'output': {'status': 'available', 'content': payload}}
                result = run_dispatch(self.arguments, dispatch, 'Collect',
                    load=lambda _: {'revision': 7, 'workspace': str(self.workspace)},
                    append=lambda args, field, value: (records.append((field, value)) or args.expected_revision + 1),
                    execute=execute)
                self.assertEqual('blocked', result['status'])
                self.assertEqual('completed', records[-1][1]['status'])
                self.assertEqual('invalid', result['role_result']['status'])

    def test_one_explicit_format_recovery_preserves_history_and_can_complete(self):
        old, failed, new = self.launches()
        state = {'workspace': str(self.workspace), 'ledger': {
            'runner_launches': [old], 'runner_results': [failed],
        }}
        before = copy.deepcopy(state)
        _validate_runner_record(state, 'runner_launches', new)
        self.assertEqual(before, state)
        passed = conclusion(new, '{"findings":[],"next_action":"continue"}')
        self.assertTrue(role_results_complete([old, new], [failed, passed]))
        self.assertFalse(role_results_complete([old, new], [failed]))

    def test_recovery_rejects_unchanged_prompt_drift_unknown_and_second_retry(self):
        old, failed, new = self.launches()
        for change in ('prompt', 'configuration', 'unknown', 'second'):
            with self.subTest(change=change):
                launches, results, candidate = [old], [failed], new
                if change == 'prompt':
                    candidate = freeze_launch(old['profile'], 'Original prompt', new['configuration'])
                elif change == 'configuration':
                    candidate = freeze_launch(old['profile'], 'Changed', {
                        **new['configuration'], 'workspace': '/different',
                    })
                elif change == 'unknown':
                    value = {k: v for k, v in failed.items() if k not in ('receipt_fingerprint', 'role_result')}
                    value.update(status='unknown', exit_code=127, error_type='TimeoutError')
                    results = [{**value, 'receipt_fingerprint': fingerprint(value)}]
                else:
                    launches.append(new)
                    results.append(conclusion(new, 'invalid again'))
                    candidate = freeze_launch(new['profile'], 'Third try', {
                        **new['configuration'], 'recovery_of': new['launch_fingerprint'],
                    })
                with self.assertRaises(ValueError):
                    _validate_runner_record({'workspace': str(self.workspace), 'ledger': {
                        'runner_launches': launches, 'runner_results': results,
                    }}, 'runner_launches', candidate)

    def test_api_reviewer_without_source_tools_is_rejected_before_launch(self):
        from multi_model import resolve
        profiles = resolve(None, workspace=self.workspace, home=self.workspace / 'home',
                           role_overrides={'reviewer': {'model': 'glm-5.2', 'reasoning_effort': 'high'}})
        dispatch = plan_dispatch(profiles, {
            **flow_state(), 'evidence': 'sufficient', 'implementation': 'complete',
            'verification': 'passed', 'review': 'pending',
        })
        self.arguments.allow_network = True
        self.arguments.review_request = review_request(); self.arguments.review_request['axis'] = 'spec'
        append, execute = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, 'source.*capability'):
            run_dispatch(self.arguments, dispatch, 'Review',
                         load=lambda _: managed_state(self.workspace), append=append, execute=execute)
        append.assert_not_called(); execute.assert_not_called()

    def test_missing_api_credential_is_rejected_before_persisting_a_scout_launch(self):
        profiles = {**self.profiles, 'roles': {**self.profiles['roles'], 'scout': api_profile()}}
        dispatch = plan_dispatch(profiles, flow_state())
        self.arguments.allow_network = True
        append, execute = Mock(), Mock()
        with patch.dict('os.environ', {'GLM_API_KEY': ''}):
            with self.assertRaisesRegex(ValueError, 'credential'):
                run_dispatch(self.arguments, dispatch, 'Collect',
                             load=lambda _: managed_state(self.workspace), append=append, execute=execute)
        append.assert_not_called(); execute.assert_not_called()

    def test_quality_dispatch_requires_a_fresh_spec_pass_before_any_launch(self):
        dispatch = plan_dispatch(self.profiles, {
            **flow_state(), 'evidence': 'sufficient', 'implementation': 'complete',
            'verification': 'passed', 'review': 'pending',
        })
        state = managed_state(self.workspace)
        state['execution_control']['review'] = {'rounds': []}
        self.arguments.review_request = review_request()
        self.arguments.review_request['axis'] = 'quality'
        append, execute = Mock(), Mock()
        with self.assertRaisesRegex(ValueError, 'spec.*pass'):
            run_dispatch(self.arguments, dispatch, 'Review', load=lambda _: state,
                         append=append, execute=execute)
        append.assert_not_called(); execute.assert_not_called()

    def test_quality_uses_the_latest_current_source_spec_result(self):
        dispatch = plan_dispatch(self.profiles, {
            **flow_state(), 'evidence': 'sufficient', 'implementation': 'complete',
            'verification': 'passed', 'review': 'pending',
        })
        state = managed_state(self.workspace)
        request = review_request(); request['axis'] = 'quality'
        spec = {'axis': 'spec', 'status': 'pass', 'source_fingerprint': state['source_fingerprint']}
        state['execution_control']['review'] = {'rounds': [{'requests': [spec]}]}
        with self.assertRaisesRegex(ValueError, 'completed.*receipt'):
            review_request_binding(state, dispatch, request)
        for replacement in ({**spec, 'status': 'findings'}, {**spec, 'source_fingerprint': 'f' * 64}):
            with self.subTest(replacement=replacement):
                state['execution_control']['review']['rounds'][-1]['requests'] = [spec, replacement]
                with self.assertRaisesRegex(ValueError, 'spec.*pass'):
                    review_request_binding(state, dispatch, request)

    def test_quality_prerequisite_requires_the_same_completed_bound_reviewer(self):
        dispatch = plan_dispatch(self.profiles, {
            **flow_state(), 'evidence': 'sufficient', 'implementation': 'complete',
            'verification': 'passed', 'review': 'pending',
        })
        state = managed_state(self.workspace)
        spec = review_request()
        launch = plan_dispatch_launch(dispatch, 'Review', workspace=self.workspace,
            review_request=spec, review_request_fingerprint=review_fingerprint(spec))
        observed, result = _execute_and_complete(launch, 'Review', spec,
            lambda *_args, **_kwargs: {'receipt': receipt(launch), 'output': {
                'status': 'available', 'content': review_response(spec)}}, False)
        record = result['review_record']
        state['execution_control']['review'] = {'rounds': [{'requests': [record]}]}
        state['ledger'].update(runner_launches=[launch], runner_results=[observed])
        request = {**spec, 'axis': 'quality'}
        self.assertEqual(request, review_request_binding(state, dispatch, request)[0])
        quality_launch = plan_dispatch_launch(dispatch, 'Quality review', workspace=self.workspace,
            review_request=request, review_request_fingerprint=review_fingerprint(request))
        quality_receipt, quality_result = _execute_and_complete(quality_launch, 'Quality review', request,
            lambda *_args, **_kwargs: {'receipt': receipt(quality_launch), 'output': {
                'status': 'available', 'content': review_response(request)}}, False)
        integrated = copy.deepcopy(state)
        integrated['execution_control']['review']['rounds'][0]['requests'].append(quality_result['review_record'])
        integrated['ledger']['runner_launches'].append(quality_launch)
        integrated['ledger']['runner_results'].append(quality_receipt)
        integration_request = {**request, 'axis': 'integration'}
        self.assertEqual(integration_request, review_request_binding(integrated, dispatch, integration_request)[0])
        for problem in ('missing', 'record', 'profile', 'receipt'):
            with self.subTest(problem=problem):
                candidate = copy.deepcopy(state)
                candidate_dispatch = dispatch
                if problem == 'missing':
                    candidate['ledger']['runner_results'] = []
                elif problem == 'record':
                    candidate['execution_control']['review']['rounds'][0]['requests'][0]['reviewer_ref'] = 'other'
                elif problem == 'profile':
                    candidate_dispatch = {**dispatch, 'profile': {**dispatch['profile'], 'worker_id': 'other'}}
                else:
                    candidate['ledger']['runner_results'][0]['receipt_fingerprint'] = '0' * 64
                with self.assertRaises(ValueError):
                    review_request_binding(candidate, candidate_dispatch, request)

    def test_cli_uses_a_nonzero_exit_for_a_blocked_lifecycle(self):
        from runner_lifecycle import main
        dispatch, prompt = self.workspace / 'dispatch.json', self.workspace / 'prompt.txt'
        dispatch.write_text('{}'); prompt.write_text('Review')
        argv = ['runner_lifecycle.py', '--dispatch', str(dispatch), '--input', str(prompt),
                '--run-id', 'run', '--writer-id', 'writer', '--repo-id', 'repo',
                '--task-key', 'task', '--expected-revision', '0']
        with patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()), \
                patch('runner_lifecycle.run_dispatch', return_value={'status': 'blocked', 'revision': 9}):
            self.assertEqual(2, main())


if __name__ == '__main__':
    unittest.main()
