import json
import subprocess
import sys
import tempfile
import unittest
import os
import time
from pathlib import Path
from unittest.mock import Mock, patch

import evidence_contract
from test_delivery_next import graph_index


def pit_output(generated=2, killed=2, outcome='SURVIVED'):
    statuses = {key: 0 for key in ('SURVIVED', 'TIMED_OUT', 'NON_VIABLE', 'MEMORY_ERROR',
                                  'NOT_STARTED', 'STARTED', 'RUN_ERROR', 'NO_COVERAGE')}
    statuses[outcome] = generated - killed
    return (f'>> KILLED {killed} ' + ' '.join(f'{key} {count}' for key, count in statuses.items()) +
            f'\n>> Generated {generated} mutations Killed {killed} (100%)\n>> Ran 3 tests (1.5 tests per mutation)\n')



class EvidenceContractTest(unittest.TestCase):
    def test_real_mutmut_campaigns_are_fresh_scoped_and_fail_closed(self):
        import importlib.util
        if importlib.util.find_spec('mutmut') is None:
            self.skipTest('install requirements-dev.txt with Python 3.10+ for real mutmut')
        (self.workspace / 'calc.py').write_text('def value(x):\n    return x + 1\n')
        (self.workspace / 'alias').symlink_to('calc.py')
        helper = self.workspace / 'helper.sh'
        helper.write_text('#!/bin/sh\necho ready\n')
        helper.chmod(0o755)
        selector = 'test_calc.py::test_value'
        argv = [sys.executable, str(Path(evidence_contract.__file__).resolve()),
                'mutmut', '--source-file', 'calc.py', '--selector', selector]
        for assertion, passing in [('calc.value(3) == 4', True),
                                   ('calc.value(3) is not None', False), ('False', False)]:
            with self.subTest(assertion=assertion):
                (self.workspace / 'test_calc.py').write_text(
                    'import calc, subprocess\ndef test_value():\n'
                    '    assert subprocess.check_output(["./helper.sh"]).strip() == b"ready"\n'
                    '    assert ' + assertion + '\n')
                observations = []
                execute = evidence_contract._run_command
                def record(*arguments):
                    result = execute(*arguments)
                    observations.append(result)
                    return result
                with patch.object(evidence_contract, '_run_command', side_effect=record):
                    receipt = evidence_contract.run_evidence(self.workspace, self.baseline, argv, 90)
                self.assertEqual(passing, receipt['exit_code'] == 0, observations)
                self.assertEqual(passing, 'mutation_check' in receipt)
                if passing:
                    cli = subprocess.run(argv, cwd=self.workspace, capture_output=True, text=True, timeout=90)
                    self.assertEqual(0, cli.returncode, cli.stderr)
                    self.assertEqual(receipt['mutation_check'], json.loads(cli.stdout))
                    self.assertEqual(selector, receipt['mutation_check']['selector'])
                    self.assertGreater(receipt['mutation_check']['generated'], 0)
                    evidence_contract.validate_observed_evidence_receipt(receipt)
                    from tdd_impact_guard import mutation_receipt
                    self.assertTrue(mutation_receipt({'tool': Path(sys.executable).name, 'receipt': receipt},
                                                     receipt['source'], selector))
                self.assertFalse((self.workspace / 'mutants').exists())

    def test_mutmut_rejects_invalid_scope_and_version_before_launch(self):
        (self.workspace / 'calc.py').write_text('def value(): return 2\n')
        (self.workspace / 'test_calc.py').write_text('def test_value(): assert True\n')
        with patch('importlib.metadata.version', return_value='3.7.0'), \
             patch.object(evidence_contract, '_run_command', side_effect=AssertionError('unexpected launch')):
            for source, selector in [('../calc.py', 'test_calc.py'), ('missing.py', 'test_calc.py'),
                                     ('calc.py', 'calc.py'), ('calc.py', 'test_calc.py::two names')]:
                with self.subTest(source=source, selector=selector), self.assertRaises(ValueError):
                    evidence_contract.run_mutmut(self.workspace, source, selector)
            (self.workspace / 'outside').symlink_to('/tmp')
            with self.assertRaisesRegex(ValueError, 'outside'):
                evidence_contract.run_mutmut(self.workspace, 'calc.py', 'test_calc.py')
        with patch('importlib.metadata.version', return_value='0'):
            with self.assertRaisesRegex(ValueError, 'version'):
                evidence_contract.run_mutmut(self.workspace, 'calc.py', 'test_calc.py')

    def test_mutmut_cli_reports_missing_dependency_without_traceback(self):
        import io
        from importlib.metadata import PackageNotFoundError
        stderr = io.StringIO()
        with patch('importlib.metadata.version', side_effect=PackageNotFoundError('mutmut')), \
             patch.object(sys, 'argv', ['evidence_contract.py', 'mutmut', '--source-file', 'calc.py',
                                        '--selector', 'test_calc.py']), patch.object(sys, 'stderr', stderr):
            self.assertEqual(2, evidence_contract.main())
        self.assertIn('evidence run blocked', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_mutmut_selector_cannot_be_spoofed_by_an_unrelated_script(self):
        helper = str(Path(evidence_contract.__file__).resolve())
        argv = [sys.executable, helper, 'mutmut', '--source-file', 'calc.py',
                '--selector', 'test_calc.py::test_value']
        good = {'selector': argv[-1], 'generated': 2, 'killed': 2, 'tests': 1}
        self.assertEqual(good, evidence_contract.mutation_execution_result(argv, json.dumps(good).encode()))
        for changed in ([*argv[:1], '/tmp/fake.py', *argv[2:]], [*argv, '--help'],
                        ['echo', *argv[1:]]):
            self.assertIsNone(evidence_contract.mutation_execution_result(changed, json.dumps(good).encode()))
        for payload in ({**good, 'generated': 0}, {**good, 'killed': 1}, {**good, 'tests': True},
                        {**good, 'selector': 'another_test'}, []):
            self.assertIsNone(evidence_contract.mutation_execution_result(argv, json.dumps(payload).encode()))
        self.assertIsNone(evidence_contract.mutation_execution_result(argv, b'invalid json'))

    def test_real_expected_failure_is_not_green(self):
        from tdd_impact_guard import green_receipts
        (self.workspace / 'pending.py').write_text(
            'import unittest\nclass Pending(unittest.TestCase):\n'
            ' @unittest.expectedFailure\n def test_missing(self): self.assertEqual(1, 2)\n')
        selector = 'pending.Pending.test_missing'
        receipts = [evidence_contract.run_evidence(self.workspace, self.baseline,
                    [sys.executable, '-m', 'unittest', selector]) for _ in range(2)]
        self.assertEqual(0, receipts[0]['exit_code'])
        with self.assertRaisesRegex(ValueError, 'pass|executed'):
            green_receipts({'receipts': receipts}, receipts[0]['source'], selector, 2)

    def test_success_exit_cannot_hide_failed_runner_outcomes(self):
        from tdd_impact_guard import green_receipts
        cases = [
            ('mvn', ['test', '-Dtest=PaymentTest', '-Dmaven.test.failure.ignore=true'],
             'Tests run: 1, Failures: 1, Errors: 0, Skipped: 0'),
            ('mvn', ['test', '-Dtest=PaymentTest'],
             'Tests run: 1, Failures: 0, Errors: 1, Skipped: 0'),
            ('mvn', ['test', '-Dtest=PaymentTest'],
             'Tests run: 1, Failures: 1, Errors: 0, Skipped: 0\n'
             'Tests run: 1, Failures: 0, Errors: 0, Skipped: 0'),
            ('gradle', ['test', '--tests', 'PaymentTest'], '2 tests completed, 1 failed'),
            ('pytest', ['-k', 'PaymentTest'], '1 passed, 1 failed in 0.01s'),
            ('pytest', ['-k', 'PaymentTest'], '1 passed, 1 error in 0.01s'),
            ('pytest', ['-k', 'PaymentTest'], '1 passed, 1 xfailed in 0.01s'),
            ('jest', ['-t', 'PaymentTest'], 'Tests: 1 failed, 1 passed, 2 total'),
            ('vitest', ['-t', 'PaymentTest'], ' Tests  1 failed | 1 passed (2)'),
        ]
        for runner, arguments, output in cases:
            with self.subTest(runner=runner, output=output):
                tool = self.workspace / runner
                tool.write_text(f'#!{sys.executable}\nprint({output!r})\n')
                tool.chmod(0o700)
                receipt = evidence_contract.run_evidence(self.workspace, self.baseline, [str(tool), *arguments])
                self.assertEqual(0, receipt['exit_code'])
                with self.assertRaisesRegex(ValueError, 'pass|executed'):
                    green_receipts({'receipts': [receipt, receipt]}, receipt['source'], 'PaymentTest', 2)

    def test_outcome_counts_preserve_normal_and_failure_results(self):
        cases = [
            ([sys.executable, '-m', 'unittest'], 'Ran 2 tests in 0.01s\nOK (skipped=1)',
             dict(executed=1, passed=1, skipped=1)),
            ([sys.executable, '-m', 'unittest'], 'Ran 2 tests in 0.01s\nOK (expected failures=1)',
             dict(executed=2, passed=1, xfailed=1)),
            ([sys.executable, '-m', 'unittest'], 'Ran 2 tests in 0.01s\nFAILED (failures=1)',
             dict(executed=2, passed=1, failed=1)),
            (['mvn'], 'Tests run: 3, Failures: 0, Errors: 1, Skipped: 1',
             dict(executed=2, passed=1, errors=1, skipped=1)),
            (['gradle'], '2 tests completed, 1 skipped', dict(executed=1, passed=1, skipped=1)),
            (['pytest'], '1 passed, 1 xpassed in 0.01s', dict(executed=2, passed=1, xpassed=1)),
            (['vitest'], ' Tests  2 passed (2)', dict(executed=2, passed=2)),
        ]
        for argv, output, outcomes in cases:
            with self.subTest(argv=argv, output=output):
                expected = dict(passed=0, failed=0, errors=0, skipped=0, xfailed=0, xpassed=0)
                expected.update(outcomes)
                self.assertEqual(expected, evidence_contract.test_execution_result(argv, output.encode(), b''))

    def test_legacy_or_inconsistent_outcomes_cannot_be_resealed_as_evidence(self):
        tool = self.workspace / 'pytest'
        tool.write_text(f'#!{sys.executable}\nprint("1 passed in 0.01s")\n')
        tool.chmod(0o700)
        receipt = evidence_contract.run_evidence(self.workspace, self.baseline, [str(tool), '-k', 'test_case'])
        evidence_contract.validate_observed_evidence_receipt(receipt)
        for check in ({'executed': 1}, {**receipt['test_check'], 'failed': -1},
                      {**receipt['test_check'], 'passed': True}, {**receipt['test_check'], 'passed': 2}):
            with self.subTest(check=check):
                value = {**receipt, 'test_check': check}
                value['receipt_fingerprint'] = evidence_contract._fingerprint(
                    {key: item for key, item in value.items() if key != 'receipt_fingerprint'})
                with self.assertRaisesRegex(ValueError, 'test result'):
                    evidence_contract.validate_observed_evidence_receipt(value)

    def test_clean_status_cannot_hide_stale_index_contents(self):
        # Keep CLI status clean for every variant; only the real SQLite/content binding changes.
        tool = self.workspace / 'codegraph'
        tool.write_text(f'#!{sys.executable}\n' + """import json, sys, os, sqlite3
from pathlib import Path
command = sys.argv[1]
if command in ('query', 'files') and os.environ.get('GRAPH_MUTATE') == '1':
 with sqlite3.connect('.codegraph/codegraph.db') as db: db.execute("UPDATE files SET errors = '[]'")
if command == 'status':
 print(json.dumps({'initialized': True, 'lastIndexed': 'now', 'projectPath': str(Path.cwd()),
  'pendingChanges': {'added': 0, 'modified': 0, 'removed': 0},
  'worktreeMismatch': None, 'index': {'reindexRecommended': False}}))
elif command == 'files': print(json.dumps([{'path': 'entry.py'}]))
elif command == 'query': print(json.dumps([{'node': {'id': 'entry', 'name': 'entry', 'filePath': 'entry.py'}}]))
elif command == 'callers': print(json.dumps({'callers': []}))
else: print('explore succeeded')
""")
        tool.chmod(0o700)
        queries = ['CodeGraph impact chains: entrypoint:entry', evidence_contract.closure_graph_request(
            [{'id': 'chain', 'entrypoints': ['entry.py'], 'callers': ['external']}])]
        for mode in ('good', 'same-size-edit', 'new-committed-caller', 'deleted', 'missing-db', 'corrupt-db', 'changing-index'):
            for query in queries:
                with self.subTest(mode=mode, query=query):
                    (self.workspace / 'entry.py').write_text('def entry(): return 1\n')
                    (self.workspace / 'caller.py').unlink(missing_ok=True)
                    graph_index(self.workspace, ['entry.py'])
                    if mode == 'same-size-edit':
                        stat = (self.workspace / 'entry.py').stat()
                        (self.workspace / 'entry.py').write_text('def entry(): return 2\n')
                        os.utime(self.workspace / 'entry.py', ns=(stat.st_atime_ns, stat.st_mtime_ns))
                    elif mode == 'new-committed-caller':
                        (self.workspace / 'caller.py').write_text('from entry import entry\nentry()\n')
                    elif mode == 'deleted': (self.workspace / 'entry.py').unlink()
                    elif mode == 'missing-db': (self.workspace / '.codegraph/codegraph.db').unlink()
                    elif mode == 'corrupt-db': (self.workspace / '.codegraph/codegraph.db').write_bytes(b'broken')
                    subprocess.run(['git', '-C', str(self.workspace), 'add', '-A'], check=True)
                    subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', 'fixture', '--allow-empty'], check=True)
                    with patch.dict(os.environ, GRAPH_MUTATE='1' if mode == 'changing-index' else '0'):
                        receipt = evidence_contract.run_evidence(self.workspace, self.baseline, [str(tool), 'explore', query])
                    if mode == 'corrupt-db': (self.workspace / '.codegraph/codegraph.db').unlink()
                    self.assertEqual(mode == 'good', bool(receipt.get('graph_check')))

    def test_pit_requires_a_scoped_nonempty_executed_campaign(self):
        from tdd_impact_guard import mutation_receipt
        tool = self.workspace / 'mvn'
        argv = [str(tool), 'org.pitest:pitest-maven:mutationCoverage', '-DtargetTests=PaymentTest']
        cases = [(pit_output(), [], True), ('', [], False), (pit_output(0, 0), [], False),
                 (pit_output().replace('Ran 3', 'Ran 0'), [], False),
                 (pit_output(), ['-Dpit.dryRun=true'], False), (pit_output(), ['-DwithHistory'], False),
                 (pit_output(), ['-DtargetTests=OtherTest'], False)]
        cases += [(pit_output(2, 1, outcome), [], False) for outcome in
                  ('SURVIVED', 'TIMED_OUT', 'NON_VIABLE', 'RUN_ERROR', 'NO_COVERAGE', 'NOT_STARTED')]
        for output, extra, expected in cases:
            with self.subTest(output=output, extra=extra):
                tool.write_text(f'#!{sys.executable}\nprint({output!r})\n')
                tool.chmod(0o700)
                receipt = evidence_contract.run_evidence(self.workspace, self.baseline, argv + extra)
                value = {'tool': 'mvn', 'receipt': receipt}
                if expected:
                    self.assertTrue(mutation_receipt(value, receipt['source'], 'PaymentTest'))
                    with self.assertRaisesRegex(ValueError, 'mutation'):
                        mutation_receipt(value, receipt['source'], 'OtherTest')
                else:
                    with self.assertRaisesRegex(ValueError, 'mutation'):
                        mutation_receipt(value, receipt['source'], 'PaymentTest')

    def test_test_summary_counts_execution_not_collection_or_skips(self):
        cases = [('unittest', 'Ran 0 tests in 0.01s\nOK', False),
                 ('unittest', 'Ran 2 tests in 0.01s\nOK (skipped=2)', False),
                 ('unittest', 'Ran 2 tests in 0.01s\nOK (skipped=1)', True),
                 ('pytest', 'collected 2 items\n2 skipped in 0.01s', False),
                 ('pytest', '1 passed, 1 skipped in 0.01s', True),
                 ('mvn', 'Tests run: 0, Failures: 0, Errors: 0, Skipped: 0', False),
                 ('mvn', 'Tests run: 2, Failures: 0, Errors: 0, Skipped: 1', True),
                 ('jest', 'Tests: 2 skipped, 2 total', False),
                 ('vitest', ' Tests  2 passed (2)', True),
                 ('gradle', '2 tests completed, 2 skipped', False)]
        for runner, output, expected in cases:
            with self.subTest(runner=runner, output=output):
                argv = [sys.executable, '-m', runner] if runner == 'unittest' else [runner]
                result = evidence_contract.test_execution_result(argv, output.encode(), b'')
                self.assertEqual(expected, bool(result))

    def test_closure_graph_uses_indexed_files_and_caller_edges(self):
        tool = self.workspace / 'codegraph'
        (self.workspace / 'caller.py').write_text('pass\n')
        chains = [{'id': 'chain', 'entrypoints': ['seed.txt'], 'callers': ['caller.py']}]
        graph_index(self.workspace, ['seed.txt', 'caller.py'])
        for mode in ('good', 'unrelated', 'missing', 'stale', 'malformed', 'bad-edge'):
            with self.subTest(mode=mode):
                tool.write_text(f'#!{sys.executable}\n' + f'mode = {mode!r}\n' + '''import json, sys
from pathlib import Path
command = sys.argv[1]
if command == 'status':
    print(json.dumps({'initialized': True, 'lastIndexed': 'now', 'projectPath': str(Path.cwd()),
        'pendingChanges': {'added': 0, 'modified': int(mode == 'stale'), 'removed': 0},
        'worktreeMismatch': None, 'index': {'reindexRecommended': False}}))
elif command == 'files':
    print(json.dumps(None if mode == 'malformed' else [] if mode == 'missing' else
                     [{'path': 'seed.txt'}, {'path': 'caller.py'}]))
elif command == 'callers':
    print(json.dumps({'callers': [None] if mode == 'bad-edge' else [] if mode == 'unrelated' else
                     [{'filePath': 'caller.py', 'kind': 'file', 'name': 'caller.py', 'startLine': 1}]}))
else: print('unrelated successful explore output')
''')
                tool.chmod(0o700)
                query = evidence_contract.closure_graph_request(chains)
                receipt = evidence_contract.run_evidence(self.workspace, self.baseline,
                                                         [str(tool), 'explore', query])
                self.assertEqual(mode == 'good', bool(receipt.get('graph_check')))
                if mode == 'good':
                    self.assertEqual(receipt, evidence_contract.require_graph_execution(receipt, query))

    def test_graph_json_shapes_fail_closed_without_raw_exceptions(self):
        tool = self.workspace / 'codegraph'
        for status in ([], None, 1, 'status', {'index': []}):
            with self.subTest(status=status):
                tool.write_text(f'#!{sys.executable}\nimport json, sys\n'
                                f'print("ok" if sys.argv[1] == "explore" else json.dumps({status!r}))\n')
                tool.chmod(0o700)
                receipt = evidence_contract.run_evidence(self.workspace, self.baseline,
                    [str(tool), 'explore', 'CodeGraph impact chains: entrypoint:demo'])
                self.assertNotIn('graph_check', receipt)

    def test_impact_graph_requires_all_observed_entrypoint_callers(self):
        tool = self.workspace / 'codegraph'
        (self.workspace / 'entry.py').write_text('def entry(): pass\n')
        (self.workspace / 'caller.py').write_text('from entry import entry\nentry()\n')
        graph_index(self.workspace, ['entry.py', 'caller.py'])
        tool.write_text(f'#!{sys.executable}\n' + '''import json, sys
from pathlib import Path
command = sys.argv[1]
node = lambda value: {'id': value, 'name': value, 'filePath': value + '.py', 'startLine': 1}
if command == 'status':
    print(json.dumps({'initialized': True, 'lastIndexed': 'now', 'projectPath': str(Path.cwd()),
        'pendingChanges': {'added': 0, 'modified': 0, 'removed': 0},
        'worktreeMismatch': None, 'index': {'reindexRecommended': False}}))
elif command == 'query': print(json.dumps([{'node': node(sys.argv[2])}]))
elif command == 'callers': print(json.dumps({'callers': [node('caller')] if sys.argv[2] == 'entry' else []}))
elif command == 'callees': print(json.dumps({'callees': [node('entry')] if sys.argv[2] == 'caller' else []}))
else: print('explore succeeded')
''')
        tool.chmod(0o700)

        omitted = evidence_contract.run_evidence(
            self.workspace, self.baseline, [str(tool), 'explore', 'CodeGraph impact chains: entrypoint:entry'])
        complete = evidence_contract.run_evidence(
            self.workspace, self.baseline,
            [str(tool), 'explore', 'CodeGraph impact chains: entrypoint:entry; caller:caller'])

        self.assertNotIn('graph_check', omitted)
        self.assertIn('graph_check', complete)

    def test_evidence_run_uses_a_bounded_default_timeout(self):
        with patch.object(evidence_contract, '_run_command', return_value=(0, b'', b'')) as execute:
            evidence_contract.run_evidence(self.workspace, self.baseline, [sys.executable, '-c', 'pass'])

        self.assertEqual(evidence_contract.DEFAULT_TIMEOUT_SECONDS, execute.call_args.args[2])

    def test_evidence_cli_accepts_an_explicit_timeout(self):
        result = subprocess.run([
            sys.executable, str(Path(evidence_contract.__file__).resolve()), 'run',
            '--workspace', str(self.workspace), '--baseline', self.baseline,
            '--timeout-seconds', '0.5', '--', sys.executable, '-c', 'pass',
        ], capture_output=True, text=True)

        self.assertEqual(0, result.returncode, result.stderr)

    def test_secondary_graph_timeout_cleans_up_descendants(self):
        tool = self.workspace / 'codegraph'
        marker = self.workspace / 'late-write.txt'
        child = f'import time;from pathlib import Path;time.sleep(1.4);Path({str(marker)!r}).write_text("late")'
        tool.write_text(f'#!{sys.executable}\nimport subprocess, sys, time\n'
                        'if sys.argv[1] == "explore": print("ok")\n'
                        f'else:\n subprocess.Popen([sys.executable, "-c", {child!r}])\n time.sleep(10)\n')
        tool.chmod(0o700)
        receipt = evidence_contract.run_evidence(self.workspace, self.baseline,
            [str(tool), 'explore', 'CodeGraph impact chains: entrypoint:demo'], timeout_seconds=.5)
        self.assertNotIn('graph_check', receipt)
        time.sleep(1.6)
        self.assertFalse(marker.exists(), 'secondary query left a background writer')
        self.assertEqual(receipt['source'], evidence_contract.workspace_source(self.workspace, self.baseline))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"],
            check=True,
        )
        self.baseline = subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def test_jacoco_warning_on_stderr_cannot_pass_with_exit_zero(self):
        from tdd_impact_guard import coverage_receipt
        executable = self.workspace / 'gradle'
        stdout = "> Task :jacocoTestCoverageVerification\n[ant:jacocoReport] Loading execution data file build/test.exec\n[ant:jacocoReport] Writing bundle 'demo' with 1 classes\nBUILD SUCCESSFUL\n"
        stderr = "[ant:jacocoReport] Rule violated for bundle demo: lines covered ratio is 0.66, but expected minimum is 0.85"
        executable.write_text(f'#!{sys.executable}\nimport sys\nprint({stdout!r})\nprint({stderr!r}, file=sys.stderr)\n')
        executable.chmod(0o700)
        observed = evidence_contract.run_evidence(self.workspace, self.baseline,
                                                 [str(executable), 'jacocoTestCoverageVerification'])
        self.assertEqual(0, observed['exit_code'])
        with self.assertRaisesRegex(ValueError, 'coverage'):
            coverage_receipt({'status': 'covered', 'threshold': 85, 'receipt': observed}, observed['source'])

    def test_jacoco_coverage_requires_an_executed_nonempty_check(self):
        from tdd_impact_guard import coverage_receipt
        gradle_good = "> Task :jacocoTestCoverageVerification\n[ant:jacocoReport] Loading execution data file build/test.exec\n[ant:jacocoReport] Writing bundle 'demo' with 1 classes\nBUILD SUCCESSFUL\n"
        maven_good = "[INFO] --- jacoco:0.8.13:check (default-cli) @ demo ---\n[INFO] Loading execution data file target/jacoco.exec\n[INFO] Analyzed bundle 'demo' with 1 classes\n[INFO] All coverage checks have been met.\n[INFO] BUILD SUCCESS\n"
        cases = [
            ('gradle', gradle_good, 0, True), ('mvn', maven_good, 0, True),
            ('gradle', '> Task :jacocoTestCoverageVerification SKIPPED\nBUILD SUCCESSFUL\n', 0, False),
            ('gradle', gradle_good.replace('Verification\n', 'Verification UP-TO-DATE\n'), 0, False),
            ('gradle', gradle_good.replace('Verification', 'Report'), 0, False),
            ('gradle', gradle_good + '> Task :other:jacocoTestCoverageVerification SKIPPED\n', 0, False),
            ('mvn', maven_good.replace('check (', 'report ('), 0, False),
            ('mvn', maven_good.replace('Loading execution data file target/jacoco.exec', 'Skipping JaCoCo execution due to missing execution data file.'), 0, False),
            ('mvn', maven_good.replace('1 classes', '0 classes'), 0, False),
            ('mvn', maven_good.replace('All coverage checks have been met.', 'Coverage checks have not been met.'), 0, False),
            ('gradle', gradle_good, 1, False), ('mvn', '[INFO] BUILD SUCCESS\n', 0, False),
        ]
        for runner, output, exit_code, expected in cases:
            with self.subTest(runner=runner, output=output, exit_code=exit_code):
                executable = self.workspace / runner
                # Real process receipt; output is a protocol fixture, not a real Java coverage claim.
                executable.write_text(f'#!{sys.executable}\nprint({output!r})\nraise SystemExit({exit_code})\n')
                executable.chmod(0o700)
                argv = [str(executable), 'jacoco:check' if runner == 'mvn' else 'jacocoTestCoverageVerification']
                observed = evidence_contract.run_evidence(self.workspace, self.baseline, argv)
                coverage = {'status': 'covered', 'threshold': 85, 'receipt': observed}
                if expected:
                    self.assertTrue(coverage_receipt(coverage, observed['source']))
                    self.assertEqual({'checks': 1, 'classes': 1}, observed['jacoco_check'])
                else:
                    with self.assertRaisesRegex(ValueError, 'coverage'):
                        coverage_receipt(coverage, observed['source'])

    def test_source_receipt_is_versioned_and_uses_the_frozen_baseline(self):
        (self.workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "committed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "task"],
            check=True,
        )
        (self.workspace / "working.txt").write_text("working\n", encoding="utf-8")

        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertEqual(2, source["schema_version"])
        self.assertEqual(self.baseline, source["baseline_commit"])
        self.assertEqual(["committed.txt", "working.txt"], source["changed_paths"])
        self.assertEqual(
            ["committed.txt", "working.txt"],
            [entry["path"] for entry in source["changed_entries"]],
        )

    def test_source_identity_includes_file_type_and_mode(self):
        path = self.workspace / "tool.sh"
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        before = evidence_contract.workspace_source(self.workspace, self.baseline)

        os.chmod(path, 0o755)
        after = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertNotEqual(before["source_fingerprint"], after["source_fingerprint"])
        self.assertEqual("100755", after["changed_entries"][0]["mode"])

    def test_pass_receipt_is_created_by_running_argv_and_matches_the_exact_source(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "print('verified')"]
        )

        self.assertEqual(receipt, evidence_contract.validate_observed_evidence_receipt(receipt))
        self.assertTrue(evidence_contract.valid_evidence_receipts([receipt], source))
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual([sys.executable, "-c", "print('verified')"], receipt["argv"])
        self.assertFalse(
            evidence_contract.valid_evidence_receipts(
                [{**receipt, "receipt_fingerprint": "0" * 64}], source
            )
        )

    def test_observed_receipt_keeps_a_real_failure_for_tdd_red_evidence(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "raise SystemExit(1)"]
        )

        self.assertEqual(1, evidence_contract.validate_observed_evidence_receipt(receipt)["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], receipt["source"]))

    def test_source_changed_after_assertion_cannot_receive_a_fresh_receipt(self):
        command = [sys.executable, "-c", (
            "from pathlib import Path; p=Path('seed.txt'); "
            "assert p.read_text() == 'seed\\n'; p.write_text('broken\\n')"
        )]
        with self.assertRaisesRegex(ValueError, "changed.*source"):
            evidence_contract.run_evidence(self.workspace, self.baseline, command)
        self.assertEqual("broken\n", (self.workspace / "seed.txt").read_text())

    def test_cli_rejects_source_drift_instead_of_returning_a_pass_receipt(self):
        result = subprocess.run(
            [sys.executable, str(Path(evidence_contract.__file__)), "run",
             "--workspace", str(self.workspace), "--baseline", self.baseline, "--",
             sys.executable, "-c", "from pathlib import Path; Path('seed.txt').unlink()"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("source", result.stderr)

    def test_nonexistent_command_cannot_be_turned_into_a_passing_receipt(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, ["definitely-not-a-real-command"]
        )

        self.assertEqual(127, receipt["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], source))

    def test_timeout_becomes_a_non_passing_receipt(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_seconds=0.01,
        )

        self.assertEqual(124, receipt["exit_code"])

    def test_timeout_cleans_up_descendants_before_returning(self):
        child = "import time;from pathlib import Path;time.sleep(.7);Path('late.txt').write_text('late')"
        parent = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
            "print('started',flush=True);time.sleep(5)"
        )
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, '-c', parent], timeout_seconds=.3,
        )
        self.assertEqual(124, receipt['exit_code'])
        import hashlib
        self.assertEqual(hashlib.sha256(b'started\n').hexdigest(), receipt['stdout_fingerprint'])
        time.sleep(.8)
        self.assertFalse((self.workspace / 'late.txt').exists())

    def test_timeout_terminates_the_process_group_once(self):
        process = Mock()
        process.stdout = Mock()
        process.stderr = Mock()
        process.communicate.side_effect = [
            subprocess.TimeoutExpired('probe', .1),
            (b'', b''),
        ]

        with patch.object(evidence_contract.subprocess, 'Popen', return_value=process), \
                patch.object(evidence_contract, '_terminate_process') as terminate:
            exit_code, _stdout, _stderr = evidence_contract._run_command(
                self.workspace, ['probe'], .1,
            )

        self.assertEqual(124, exit_code)
        terminate.assert_called_once_with(process)
        process.wait.assert_called_once_with(timeout=1)

    def test_secondary_drain_timeout_cannot_escape_as_a_subprocess_error(self):
        escaped = "import time; time.sleep(5)"
        parent = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{escaped!r}],start_new_session=True);"
            "time.sleep(5)"
        )
        with self.assertRaises(evidence_contract.EvidenceCleanupError) as failure:
            evidence_contract.run_evidence(self.workspace, self.baseline,
                [sys.executable, '-c', parent], timeout_seconds=.3)

        self.assertIsInstance(failure.exception, ValueError)
        self.assertNotIsInstance(failure.exception, subprocess.TimeoutExpired)
        self.assertIsInstance(failure.exception.__cause__, subprocess.TimeoutExpired)

    def test_exited_command_cannot_leave_a_background_writer(self):
        child = "import time;from pathlib import Path;time.sleep(.4);Path('late.txt').write_text('late')"
        for exit_code in (0, 1):
            parent = (
                'import subprocess,sys;'
                f'subprocess.Popen([sys.executable,"-c",{child!r}],'
                'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
                f'raise SystemExit({exit_code})'
            )
            receipt = evidence_contract.run_evidence(self.workspace, self.baseline, [sys.executable, '-c', parent])
            self.assertEqual(exit_code, receipt['exit_code'])
            time.sleep(.5)
            self.assertFalse((self.workspace / 'late.txt').exists())

    def test_cleanup_failure_cannot_issue_an_evidence_receipt(self):
        with patch.object(evidence_contract, '_terminate_process', side_effect=PermissionError('cleanup denied')):
            with self.assertRaises(evidence_contract.EvidenceCleanupError) as failure:
                evidence_contract.run_evidence(self.workspace, self.baseline, [sys.executable, '-c', 'pass'])
            self.assertIsInstance(failure.exception.__cause__, PermissionError)

    def test_secondary_cleanup_failure_cannot_be_downgraded_to_missing_graph(self):
        with patch.object(evidence_contract, '_run_command', side_effect=[
                (0, b'ok', b''), evidence_contract.EvidenceCleanupError('cleanup unknown')]):
            with self.assertRaisesRegex(evidence_contract.EvidenceCleanupError, 'cleanup unknown'):
                evidence_contract.run_evidence(self.workspace, self.baseline,
                    ['codegraph', 'explore', 'CodeGraph impact chains: entrypoint:demo'])


    def test_cli_executes_the_command_without_a_shell(self):
        marker = self.workspace / ".git" / "marker.txt"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(evidence_contract.__file__)),
                "run",
                "--workspace",
                str(self.workspace),
                "--baseline",
                self.baseline,
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ran", marker.read_text(encoding="utf-8"))
        self.assertEqual(0, json.loads(result.stdout)["exit_code"])

    def test_sensitive_command_arguments_are_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["tool", "--api-key=secret-value"]
            )

        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["curl", "Authorization: Bearer secret-value"]
            )

    def test_receipts_reject_oversized_argv_values(self):
        with self.assertRaisesRegex(ValueError, "argv"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, [sys.executable, "-c", "x" * 4097]
            )

    def test_source_receipt_validator_rejects_tampered_metadata(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        source["changed_paths"] = ["invented.txt"]

        with self.assertRaisesRegex(ValueError, "paths|fingerprint"):
            evidence_contract.validate_source_receipt(source)


if __name__ == "__main__":
    unittest.main()
