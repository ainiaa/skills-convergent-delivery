"""Regression tests for dirty task baselines and native Node/Rust evidence."""

import copy
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from autonomy_begin import initial_state
from delivery_next import validate_state
from delivery_state import validate_transition
from evidence_contract import workspace_source


class DirtyBaselineTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        for name in ('owned.txt', 'outside.txt', 'permissions.txt'):
            (self.root / name).write_text('committed\n')
        self.git('init', '-q')
        self.git('add', '.')
        self.git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'fixture')
        (self.root / 'outside.txt').write_text('preexisting\n')
        (self.root / 'permissions.txt').write_text('preexisting\n')
        (self.root / 'untracked.txt').write_text('preexisting\n')
        (self.root / 'link').symlink_to('outside.txt')

    def git(self, *argv):
        return subprocess.run(['git', '-C', str(self.root), *argv],
                              check=True, capture_output=True, text=True).stdout.strip()

    def state(self, scope=('owned.txt',), risks=()):
        return initial_state(self.root, ['fix owned'], ['owned correct'], list(scope),
                             'run-dirty', 'writer-dirty', list(risks), mode='native', extensions=())

    def refresh(self, state):
        source = workspace_source(self.root, state['baseline']['commit'])
        state.update(source_receipt=source, source_fingerprint=source['source_fingerprint'])
        state['execution_control']['review']['rounds'] = [
            {'source_fingerprint': source['source_fingerprint'], 'requests': []}]
        return state

    def test_unchanged_dirty_paths_are_not_task_scope_or_risk(self):
        state = self.state()
        self.assertEqual(state['source_receipt'], state['baseline']['source'])
        self.assertIsNot(state['source_receipt'], state['baseline']['source'])
        self.assertEqual([], state['execution_control']['routing']['profile']['risk_flags'])
        self.assertEqual('round-1-build', validate_state(state, SimpleNamespace()))
        (self.root / 'owned.txt').write_text('fixed\n')
        self.assertEqual('round-1-build', validate_state(self.refresh(state), SimpleNamespace()))

    def test_dirty_paths_changed_after_start_cannot_escape_scope(self):
        changes = (
            lambda: (self.root / 'outside.txt').write_text('changed again\n'),
            lambda: (self.root / 'outside.txt').write_text('committed\n'),
            lambda: (self.root / 'untracked.txt').unlink(),
            lambda: (self.root / 'outside.txt').chmod(0o755),
            lambda: ((self.root / 'link').unlink(), (self.root / 'link').symlink_to('owned.txt')),
        )
        for change in changes:
            with self.subTest(change=changes.index(change)):
                # Every probe starts with the currently observed dirty workspace frozen.
                state = self.state()
                change()
                with self.assertRaisesRegex(ValueError, 'source scope drift'):
                    validate_state(self.refresh(state), SimpleNamespace())

    def test_new_risky_path_inside_wide_scope_still_requires_declared_risk(self):
        state = self.state(('.',))
        self.assertEqual([], state['execution_control']['routing']['profile']['risk_flags'])
        (self.root / 'permissions.txt').write_text('new authorization behavior\n')
        with self.assertRaisesRegex(ValueError, 'source risk exceeds'):
            validate_state(self.refresh(state), SimpleNamespace())

    def test_explicit_scope_and_semantic_risks_are_preserved(self):
        state = self.state(('permissions.txt',), ('public-api',))
        self.assertEqual(['permission', 'public-api', 'security'],
                         state['execution_control']['routing']['profile']['risk_flags'])
        self.assertEqual('round-1-build', validate_state(state, SimpleNamespace()))

    def test_legacy_baseline_is_not_silently_exempted(self):
        state = self.state()
        state['baseline'].pop('source', None)
        with self.assertRaisesRegex(ValueError, 'source scope drift'):
            validate_state(state, SimpleNamespace())

    def test_start_receipt_is_validated_and_bound_to_baseline(self):
        for field, value in (('diff_fingerprint', 'f' * 64), ('commit', 'f' * 40)):
            state = self.state(('.',), ('permission', 'security'))
            state['baseline'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'baseline'):
                validate_state(state, SimpleNamespace())
        state = self.state(('.',), ('permission', 'security'))
        state['baseline']['source']['source_fingerprint'] = 'f' * 64
        with self.assertRaisesRegex(ValueError, 'fingerprint'):
            validate_state(state, SimpleNamespace())

    def test_task_start_cannot_be_replaced_during_transition(self):
        previous = self.state(('.',), ('permission', 'security'))
        candidate = copy.deepcopy(previous)
        (self.root / 'outside.txt').write_text('new start\n')
        start = workspace_source(self.root, previous['baseline']['commit'])
        candidate['baseline'].update(source=start, diff_fingerprint=start['diff_fingerprint'])
        candidate['revision'] += 1
        with self.assertRaisesRegex(ValueError, 'baseline'):
            validate_transition(previous, candidate)

    def test_staged_rename_source_restoration_is_a_task_change(self):
        (self.root / 'permissions.txt').write_text('committed\n')
        self.git('mv', 'permissions.txt', 'moved.txt')
        state = self.state()
        (self.root / 'permissions.txt').write_text('committed\n')
        self.git('add', 'permissions.txt')
        from evidence_contract import source_delta
        current = self.refresh(state)
        self.assertIn('permissions.txt', source_delta(state['baseline']['source'],
                                                     current['source_receipt']))
        with self.assertRaisesRegex(ValueError, 'source scope drift'):
            validate_state(current, SimpleNamespace())

    def test_current_workspace_freshness_is_not_relaxed(self):
        state = self.state()
        (self.root / 'owned.txt').write_text('new bytes\n')
        with self.assertRaisesRegex(ValueError, 'current workspace'):
            validate_state(state, SimpleNamespace())


class NativeTestEvidenceTest(unittest.TestCase):
    def result(self, argv, output):
        from evidence_contract import test_execution_result
        return test_execution_result(argv, output.encode(), b'')

    def node_summary(self, *, passed=2, failed=0, cancelled=0, skipped=0, todo=0, prefix='#'):
        counts = {'tests': passed + failed + cancelled + skipped + todo, 'suites': 0,
                  'pass': passed, 'fail': failed, 'cancelled': cancelled, 'skipped': skipped, 'todo': todo}
        return ''.join(f'{prefix} {key} {value}\n' for key, value in counts.items())

    def cargo_summary(self, passed=2, failed=0, ignored=0, status='ok'):
        return (f'test result: {status}. {passed} passed; {failed} failed; {ignored} ignored; '
                '0 measured; 0 filtered out; finished in 0.01s\n')

    def test_node_tap_and_spec_summaries_preserve_all_outcomes(self):
        for prefix in ('#', 'ℹ'):
            result = self.result(['node', '--test', 'case.test.mjs'], self.node_summary(
                prefix=prefix, passed=3, failed=1, cancelled=2, skipped=4, todo=5))
            self.assertIsNotNone(result)
            self.assertEqual({'executed': 11, 'passed': 3, 'failed': 1, 'errors': 2,
                              'skipped': 4, 'xfailed': 5, 'xpassed': 0}, result)

    def test_node_zero_skipped_malformed_and_non_test_launches_do_not_prove_tests(self):
        for argv, text in (
            (['node', '--test'], self.node_summary(passed=0)),
            (['node', '--test'], self.node_summary(passed=0, skipped=3)),
            (['node', '--test'], self.node_summary().replace('# tests 2', '# tests 9')),
            (['node', '--test'], self.node_summary().replace('# fail 0\n', '')),
            (['node', '-e', 'console.log(1)'], self.node_summary()),
        ):
            with self.subTest(argv=argv, text=text):
                self.assertIsNone(self.result(argv, text))

    def test_cargo_combines_all_binaries_without_hiding_an_earlier_failure(self):
        text = self.cargo_summary(2, 1, 3, 'FAILED') + self.cargo_summary(4) + self.cargo_summary(0)
        for command in ('test', 'llvm-cov'):
            result = self.result(['cargo', command, 'target_case'], text)
            self.assertIsNotNone(result)
            self.assertEqual(6, result['passed'])
            self.assertEqual(1, result['failed'])
            self.assertEqual(3, result['skipped'])
            self.assertEqual(7, result['executed'])

    def test_cargo_zero_ignored_malformed_and_non_test_commands_are_rejected(self):
        for argv, text in (
            (['cargo', 'test'], self.cargo_summary(0)),
            (['cargo', 'test'], self.cargo_summary(0, ignored=3)),
            (['cargo', 'test'], self.cargo_summary(status='FAILED')),
            (['cargo', 'test'], self.cargo_summary() + 'test result: invalid\n'),
            (['cargo', 'build'], self.cargo_summary()),
        ):
            with self.subTest(argv=argv, text=text):
                self.assertIsNone(self.result(argv, text))

    def test_existing_tarpaulin_coverage_is_not_subject_to_the_new_runner_gate(self):
        from evidence_contract import require_jacoco_execution
        require_jacoco_execution({'argv': ['cargo', 'tarpaulin', '--fail-under=85']})
        require_jacoco_execution({'argv': ['cargo-tarpaulin', '--fail-under=85']})

    def test_cargo_red_accepts_assertion_exit_101_without_accepting_unknown_failures(self):
        from unittest.mock import patch
        import evidence_contract as evidence
        from tdd_impact_guard import red_receipt
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fixture').write_text('before')
            for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Test', '-c',
                          'user.email=test@example.invalid', 'commit', '-qm', 'fixture']):
                subprocess.run(['git', '-C', directory, *args], check=True, capture_output=True)
            for index, (argv, code, output, accepted) in enumerate((
                (['cargo', 'test', 'target_case'], 101, self.cargo_summary(0, 1, status='FAILED'), True),
                (['cargo', 'llvm-cov', 'test', 'target_case'], 101, self.cargo_summary(0, 1, status='FAILED'), True),
                (['cargo', 'test', 'target_case'], 101, 'error: could not compile crate', False),
                (['cargo', 'test', 'target_case'], 2, self.cargo_summary(0, 1, status='FAILED'), False),
                (['node', '--test', 'case.test.mjs'], 101, self.node_summary(passed=0, failed=1), False),
            )):
                with self.subTest(argv=argv, code=code), patch.object(evidence, '_run_command',
                        return_value=(code, output.encode(), b'')):
                    receipt = evidence.run_evidence(root, 'HEAD', argv)
                    (root / 'fixture').write_text(f'after-{index}')
                    source = evidence.workspace_source(root, 'HEAD')
                    value = {'receipt': receipt, 'failure_class': 'assertion'}
                    selector = 'case.test.mjs' if argv[0] == 'node' else 'target_case'
                    if accepted:
                        red_receipt(value, source, selector)
                    else:
                        with self.assertRaisesRegex(ValueError, 'target behavior failure'):
                            red_receipt(value, source, selector)

    def test_native_selectors_use_the_runner_syntax(self):
        from tdd_impact_guard import runner_selector_matches
        good = (
            (['node', '--test', 'tests/case.test.mjs'], 'tests/case.test.mjs'),
            (['node', '--test', '--test-reporter=tap', '--test-name-pattern', '^target$',
              'case.test.mjs'], '^target$'),
            (['node', '--test', '--test-name-pattern=target', 'case.test.mjs'], 'target'),
            (['cargo', 'test', '--lib', 'target_case', '--', '--exact'], 'target_case'),
            (['cargo', 'test', 'report'], 'report'),
            (['cargo', 'llvm-cov', 'test', 'report'], 'report'),
            (['cargo', 'test', '--manifest-path', 'Cargo.toml', 'target_case'], 'target_case'),
            (['cargo', 'llvm-cov', 'test', '--fail-under-lines=90', 'target_case'], 'target_case'),
        )
        for argv, selector in good:
            with self.subTest(argv=argv):
                self.assertTrue(runner_selector_matches(argv, selector))

    def test_native_selector_values_and_disabled_execution_do_not_match(self):
        from tdd_impact_guard import runner_selector_matches
        bad = (
            (['node', '--test', '--test-reporter', 'target'], 'target'),
            (['node', '--test', '--import', 'target'], 'target'),
            (['node', '--test', '--test-name-pattern=other', 'target'], 'target'),
            (['node', '--test', '--test-name-pattern=target', '--test-name-pattern=other'], 'target'),
            (['node', '-e', 'target'], 'target'),
            (['cargo', 'test', '--package', 'target'], 'target'),
            (['cargo', 'test', '--test', 'target'], 'target'),
            (['cargo', 'test', '--manifest-path', 'target'], 'target'),
            (['cargo', 'test', 'target', '--no-run'], 'target'),
            (['cargo', 'test', 'target', '--', '--list'], 'target'),
            (['cargo', 'llvm-cov', 'report', 'target'], 'target'),
            (['cargo', 'llvm-cov', 'target'], 'target'),
        )
        for argv, selector in bad:
            with self.subTest(argv=argv):
                self.assertFalse(runner_selector_matches(argv, selector))

    def test_observed_native_receipts_validate_and_failed_outcomes_cannot_be_green(self):
        from unittest.mock import patch
        import evidence_contract as evidence
        from tdd_impact_guard import coverage_receipt, green_receipts
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'fixture').write_text('fixture')
            for args in (['init', '-q'], ['add', '.'], ['-c', 'user.name=Test', '-c',
                          'user.email=test@example.invalid', 'commit', '-qm', 'fixture']):
                subprocess.run(['git', '-C', directory, *args], check=True, capture_output=True)
            for argv, output, selector in (
                (['node', '--test', 'case.test.mjs'], self.node_summary(), 'case.test.mjs'),
                (['cargo', 'test', 'target_case'], self.cargo_summary(), 'target_case'),
            ):
                with self.subTest(argv=argv), patch.object(evidence, '_run_command',
                        return_value=(0, output.encode(), b'')):
                    receipt = evidence.run_evidence(root, 'HEAD', argv)
                    self.assertEqual(2, evidence.validate_observed_evidence_receipt(receipt)['test_check']['passed'])
                    green_receipts({'receipts': [receipt]}, receipt['source'], selector, 1)
                    self.assertTrue(coverage_receipt({'status': 'covered', 'threshold': 85,
                                                     'receipt': receipt}, receipt['source']))
            for argv, output, selector in (
                (['node', '--test', 'case.test.mjs'], self.node_summary(passed=0), 'case.test.mjs'),
                (['cargo', 'test', 'target_case'], self.cargo_summary(0), 'target_case'),
                (['node', '--test', 'case.test.mjs'], self.node_summary(failed=1), 'case.test.mjs'),
                (['node', '--test', 'case.test.mjs'], self.node_summary(todo=1), 'case.test.mjs'),
                (['cargo', 'test', 'target_case'], self.cargo_summary(failed=1, status='FAILED'), 'target_case'),
            ):
                with self.subTest(output=output), patch.object(evidence, '_run_command',
                        return_value=(0, output.encode(), b'')):
                    receipt = evidence.run_evidence(root, 'HEAD', argv)
                    with self.assertRaisesRegex(ValueError, 'passing|failed|outcome|nonempty'):
                        green_receipts({'receipts': [receipt]}, receipt['source'], selector, 1)
                    with self.assertRaisesRegex(ValueError, 'coverage.*tests'):
                        coverage_receipt({'status': 'covered', 'threshold': 85,
                                          'receipt': receipt}, receipt['source'])


class NativeCoveragePolicyTest(unittest.TestCase):
    def resolve(self, command, target=None):
        import native_tdd_policy as policy
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / policy.COMMAND_FILE
            config.parent.mkdir(parents=True)
            config.write_text('coverage: ' + command + '\n')
            if target is not None:
                (root / policy.TARGET_FILE).write_text(f'coverage: {target}\n')
            return policy.resolve(root)

    def test_native_line_thresholds_are_recognized_without_rewriting_other_metrics(self):
        for command in (
            'node --test --experimental-test-coverage --test-coverage-lines=95 '
            '--test-coverage-branches=90 --test-coverage-functions=95 case.test.mjs',
            'cargo llvm-cov --fail-under-lines=95',
            'cargo llvm-cov test --lib --fail-under-lines 95',
            'cargo llvm-cov --manifest-path report --fail-under-lines=95',
            'cargo llvm-cov test report --fail-under-lines=95',
            'cargo llvm-cov --exclude report --fail-under-lines=95',
            'cargo llvm-cov --exclude-from-test report --fail-under-lines=95',
            'cargo llvm-cov --exclude-from-report report --fail-under-lines=95',
            'cargo llvm-cov --dep-coverage report --fail-under-lines=95',
            'cargo llvm-cov --color always --failure-mode any --fail-under-lines=95',
            'cargo llvm-cov --fail-uncovered-lines 10 --fail-under-lines=95',
        ):
            with self.subTest(command=command):
                result = self.resolve(command)
                self.assertEqual('ready', result['status'])
                self.assertEqual(95, result['threshold'])
                self.assertEqual('argv', result['threshold_source'])
                import shlex
                self.assertEqual(shlex.split(command), result['argv'])

    def test_native_missing_gate_uses_the_frozen_project_or_default_threshold(self):
        for target, expected in ((None, 85), (94, 94)):
            for command, option in (
                ('node --test --experimental-test-coverage case.test.mjs', '--test-coverage-lines'),
                ('cargo llvm-cov --lib', '--fail-under-lines'),
            ):
                with self.subTest(command=command, target=target):
                    result = self.resolve(command, target)
                    self.assertEqual('ready', result['status'])
                    self.assertEqual(expected, result['threshold'])
                    self.assertIn(f'{option}={expected}', result['argv'])
                    self.assertEqual('adapter', result['threshold_source'])
                    if result['argv'][0] == 'node':
                        self.assertLess(result['argv'].index(f'{option}={expected}'),
                                        result['argv'].index('case.test.mjs'))

    def test_rust_threads_separator_preserves_explicit_or_injected_line_gate(self):
        import native_tdd_policy as policy
        for gate, threshold in ((" --fail-under-lines=95", 95), ("", 91)):
            command = "cargo llvm-cov --locked" + gate + " -- --test-threads=2"
            result = self.resolve(command, 91)
            self.assertEqual("ready", result["status"])
            self.assertEqual(threshold, result["threshold"])
            self.assertEqual(["--", "--test-threads=2"], result["argv"][-2:])
            self.assertLess(result["argv"].index(f"--fail-under-lines={threshold}"),
                            result["argv"].index("--"))
        self.assertIsNone(policy.explicit_threshold(
            ["cargo", "llvm-cov", "--", "--fail-under-lines=95"]))

    def test_rust_threads_separator_does_not_accept_other_trailing_test_modes(self):
        for suffix in ("", "--ignored", "--help", "--test-threads=0", "--test-threads=-1",
                       "--test-threads=bad", "--test-threads=2 --", "--test-threads=2 --ignored",
                       "--fail-under-lines=95"):
            self.assertEqual("uncovered", self.resolve(
                "cargo llvm-cov --fail-under-lines=85 -- " + suffix)["status"])
        self.assertEqual("uncovered", self.resolve(
            "node --test --experimental-test-coverage --test-coverage-lines=85 -- --test-threads=2")["status"])

    def test_rust_threads_separator_keeps_disabled_collection_and_duplicate_gates_rejected(self):
        for option in ("report", "--no-run", "--no-report", "--no-clean", "--ignore-run-fail",
                       "--fail-under-lines=90"):
            self.assertEqual("uncovered", self.resolve(
                f"cargo llvm-cov {option} --fail-under-lines=85 -- --test-threads=2")["status"])

    def test_node_requires_actual_test_coverage_collection(self):
        for command in (
            'node --test --test-coverage-lines=85',
            'node --experimental-test-coverage --test-coverage-lines=85 case.mjs',
            'node --test --experimental-test-coverage --no-experimental-test-coverage --test-coverage-lines=85',
            'node --test --no-test --experimental-test-coverage --test-coverage-lines=85',
            'node --test --experimental-test-coverage --eval print --test-coverage-lines=85',
            'node --test --experimental-test-coverage --check --test-coverage-lines=85',
            'node -v --test --experimental-test-coverage --test-coverage-lines=85',
        ):
            with self.subTest(command=command):
                self.assertEqual('uncovered', self.resolve(command)['status'])

    def test_cargo_llvm_cov_report_reuse_and_masked_failures_are_not_fresh_coverage(self):
        for mode in ('report', 'show-env', 'clean', 'run', 'nextest', '--no-run', '--no-clean',
                     '--no-report', '--ignore-run-fail', '--no-run=true', '--help', '--version', '-V'):
            for prefix in ('', '--quiet '):
                command = f'cargo llvm-cov {prefix}{mode} --fail-under-lines=85'
                with self.subTest(command=command):
                    self.assertEqual('uncovered', self.resolve(command)['status'])

    def test_native_line_gate_must_be_one_unambiguous_literal(self):
        for prefix, option in (
            ('node --test --experimental-test-coverage', '--test-coverage-lines'),
            ('cargo llvm-cov', '--fail-under-lines'),
        ):
            for value in ('0', '101', '-1', 'invalid', '85.5', ''):
                with self.subTest(prefix=prefix, value=value):
                    self.assertEqual('uncovered', self.resolve(f'{prefix} {option}={value}')['status'])
            self.assertEqual('uncovered', self.resolve(f'{prefix} {option}=85 {option}=90')['status'])

    def test_native_runner_cannot_be_spoofed_by_an_argument(self):
        for command in ('echo node --test --experimental-test-coverage --test-coverage-lines=95',
                        'echo cargo llvm-cov --fail-under-lines=95',
                        'cargo test --fail-under-lines=95',
                        'cargo llvm-cov --fail-under=95',
                        'cargo llvm-cov --dep-coverage test report --fail-under-lines=95'):
            with self.subTest(command=command):
                # llvm-cov's unrelated flag is not accepted as a line gate.
                self.assertEqual('uncovered', self.resolve(command)['status'])


if __name__ == '__main__':
    unittest.main()
