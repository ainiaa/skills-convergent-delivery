#!/usr/bin/env python3
"""Regression tests for execution after a planned-task validation result."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plan_execution import decide, classify_validation_failure


class PlanExecutionTest(unittest.TestCase):
    def runtime(self, envelope, workspace):
        from test_delivery_next import autonomous_state, upgrade_state
        from delivery_state import project_state_root, project_lease_root, state_path
        from evidence_contract import workspace_source
        root = Path(workspace).resolve()
        source = workspace_source(root, envelope['plan']['baseline']['commit'])
        runtime = upgrade_state(autonomous_state(workspace=str(root), repo_id=str(root/'.git'),
            task_key=envelope['plan']['plan_id'], run_id='plan-runtime', writer_id='plan-writer',
            baseline={'commit':source['baseline_commit'],'diff_fingerprint':'clean'}))
        runtime.update(source_receipt=source,source_fingerprint=source['source_fingerprint'])
        runtime['ledger']['tdd_trace']=None
        runtime['execution_control']['review']['rounds']=[]
        final_entries = [entry for entry in envelope['final_acceptance'] if isinstance(entry.get('evidence'), dict)]
        if final_entries:
            runtime['ledger']['acceptance'] = [{'criterion':entry['criterion'], 'evidence':'observed plan final acceptance',
                'result':entry['result'], 'freshness':entry['freshness'],
                'source_fingerprint':entry['evidence']['source']['source_fingerprint'],
                'evidence_receipts':[entry['evidence']]} for entry in final_entries]
        path=state_path(project_state_root(root),runtime['repo_id'],runtime['task_key'],runtime['run_id'])
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(runtime))
        command=[sys.executable,str(Path(__file__).with_name('delivery_lease.py')),'acquire',
                 '--root',str(project_lease_root(root)),'--repo',runtime['repo_id'],'--workspace',str(root),
                 '--task-key',runtime['task_key'],'--run-id',runtime['run_id'],'--writer-id',runtime['writer_id']]
        result=subprocess.run(command,capture_output=True,text=True)
        if result.returncode == 2:
            observed = json.loads(result.stdout)
            holder = observed.get('holder', {})
            if observed.get('status') in {'blocked_workspace_expired', 'blocked_task_expired'} and all(
                holder.get(field) == runtime[field]
                for field in ('repo_id', 'workspace', 'task_key', 'run_id', 'writer_id')
            ):
                result = subprocess.run([*command, '--takeover'], capture_output=True, text=True)
        self.assertEqual(0,result.returncode,result.stdout+result.stderr)
        from delivery_lease import lease_paths, remove_if_owned
        self.addCleanup(path.unlink, missing_ok=True)
        for lease in lease_paths(project_lease_root(root), runtime['repo_id'], root, runtime['task_key']).values():
            self.addCleanup(remove_if_owned, lease, runtime['run_id'], runtime['writer_id'])
        envelope['runtime_state_path']=str(path)
        return path

    def next_plan(self, envelope, workspace):
        from plan_execution import next_plan_action
        self.runtime(envelope,workspace)
        return next_plan_action(envelope,workspace,implementation_authorized=True)
    def schedule(self, results, **options):
        from plan_execution import select_task
        tasks = [
            {"task_id": "T1", "depends_on": [], "owned_paths": ["a"]},
            {"task_id": "T2", "depends_on": ["T1"], "owned_paths": ["b"]},
            {"task_id": "T3", "depends_on": ["T2"], "owned_paths": ["c"]},
            {"task_id": "T4", "depends_on": [], "owned_paths": ["d"]},
        ]
        return select_task(tasks, results, **options)

    def test_local_block_skips_dependents_and_selects_independent_work(self):
        result = self.schedule({"T1": "blocked"})
        self.assertEqual("ready", result["status"])
        self.assertEqual("T4", result["task_id"])
        self.assertEqual(["T1"], result["blocked"])
        self.assertEqual(["T2", "T3"], result["waiting"])
        self.assertEqual(result, self.schedule(json.loads(json.dumps({"T1": "blocked"}))))

    def test_all_remaining_work_blocked_is_not_complete_or_retried(self):
        result = self.schedule({"T1": "blocked", "T4": "completed"})
        self.assertEqual("blocked", result["status"])
        self.assertIsNone(result["task_id"])
        self.assertEqual(["T1"], result["blocked"])
        self.assertEqual(["T2", "T3"], result["waiting"])
        self.assertEqual("verify", self.schedule(dict.fromkeys(["T1", "T2", "T3", "T4"], "completed"))["status"])

    def test_completed_dependencies_unlock_work_but_global_stop_and_budget_win(self):
        self.assertEqual("T2", self.schedule({"T1": "completed"})["task_id"])
        for options in ({"global_block": "user stopped"}, {"budget_exhausted": True}):
            with self.subTest(options=options):
                self.assertEqual("blocked", self.schedule({"T1": "blocked"}, **options)["status"])

    def test_shared_paths_and_running_work_are_not_bypassed(self):
        from plan_execution import select_task
        tasks = [{"task_id": "T1", "depends_on": [], "owned_paths": ["src"]},
                 {"task_id": "T2", "depends_on": [], "owned_paths": ["src/a.py"]}]
        self.assertEqual("blocked", select_task(tasks, {"T1": "blocked"})["status"])
        result = select_task(tasks, {'T2': 'blocked'})
        self.assertEqual('blocked', result['status'])
        self.assertEqual(['T1'], result['waiting'])
        independent = {'task_id': 'T3', 'depends_on': [], 'owned_paths': ['src-other']}
        self.assertEqual('T3', select_task([*tasks, independent], {'T2': 'blocked'})['task_id'])
        with self.assertRaises(ValueError):
            select_task(tasks, {'T1': 'running', 'T2': 'blocked'})
        self.assertEqual("T1", self.schedule({"T1": "running"})["task_id"])
        reversed_tasks = [{**tasks[0], 'depends_on': ['T2']}, tasks[1]]
        self.assertEqual('T2', select_task(reversed_tasks, {})['task_id'])

    def test_scheduler_rejects_invalid_dependency_graph_or_results(self):
        from plan_execution import select_task
        task = {"task_id": "T1", "depends_on": [], "owned_paths": ["src"]}
        for tasks, results in (([], {}), ([task, task], {}),
                               ([{**task, "depends_on": ["unknown"]}], {}),
                               ([{**task, "depends_on": ["T1"]}], {}),
                               ([task], {"T1": "uncovered"}), ([task], {"unknown": "completed"})):
            with self.subTest(tasks=tasks, results=results), self.assertRaises(ValueError):
                select_task(tasks, results)

    def test_final_tool_completion_requires_all_frozen_current_proofs(self):
        import copy
        from plan_execution import tooling_acceptance_recovered
        from evidence_contract import run_evidence
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            marker=Path(directory)/'ready'
            argv=[sys.executable,'-c',f'from pathlib import Path; import time; time.sleep(0 if Path({str(marker)!r}).exists() else 5)']
            failed=run_evidence(root,'HEAD',argv,.05);marker.touch()
            passed=run_evidence(root,'HEAD',argv);source=passed['source']
            old=[{'criterion':'behavior','result':'unknown','freshness':'unavailable','evidence':failed}]
            current=[{'criterion':'behavior','result':'pass','freshness':'fresh','evidence':passed}]
            self.assertTrue(tooling_acceptance_recovered(old,[],current,source))
            self.assertFalse(tooling_acceptance_recovered(old,[],current,None))
            self.assertFalse(tooling_acceptance_recovered(current,[],current,source))
            for field,value in [('criterion','different'),('result','unknown'),('freshness','stale'),('source_fingerprint','0'*64)]:
                invalid=copy.deepcopy(current);invalid[0][field]=value
                self.assertFalse(tooling_acceptance_recovered(old,[],invalid,source))
            unrelated=copy.deepcopy(current);unrelated[0]['evidence']=run_evidence(root,'HEAD',[sys.executable,'-c','pass'])
            self.assertFalse(tooling_acceptance_recovered(old,[],unrelated,source))
            real_failure=copy.deepcopy(old);real_failure[0]['evidence']=run_evidence(root,'HEAD',[sys.executable,'-c','raise SystemExit(1)'])
            self.assertFalse(tooling_acceptance_recovered(real_failure,[],current,source))

    def test_final_tool_completion_must_also_resolve_archived_actual_failures(self):
        from plan_execution import tooling_acceptance_recovered
        from evidence_contract import run_evidence
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'ready'
            argv = [sys.executable, '-c', f'from pathlib import Path; import time; time.sleep(0 if Path({str(marker)!r}).exists() else 5)']
            gap = run_evidence(root, 'HEAD', argv, .05)
            actual_marker = Path(directory) / 'actual-ready'
            actual_argv = [sys.executable, '-c', f'from pathlib import Path; assert Path({str(actual_marker)!r}).exists()']
            failed = run_evidence(root, 'HEAD', actual_argv)
            history = [{'criterion': 'behavior', 'result': 'fail', 'freshness': 'fresh',
                        'evidence_receipts': [failed]}]
            marker.touch()
            passed = run_evidence(root, 'HEAD', argv)
            previous = [{'criterion': 'behavior', 'result': 'unknown', 'freshness': 'unavailable', 'evidence': gap}]
            current = [{'criterion': 'behavior', 'result': 'pass', 'freshness': 'fresh', 'evidence_receipts': [passed]}]
            self.assertFalse(tooling_acceptance_recovered(previous, history, current, passed['source']))
            actual_marker.touch()
            current[0]['evidence_receipts'].append(run_evidence(root, 'HEAD', actual_argv))
            self.assertTrue(tooling_acceptance_recovered(previous, history, current, passed['source']))

    def test_ordinary_plan_waits_for_a_later_overlapping_tooling_blocker(self):
        from evidence_contract import run_evidence
        fixture_dir = Path(__file__).resolve().parents[1] / 'skills/converge-plan/scripts'
        sys.path.insert(0, str(fixture_dir))
        try:
            from test_plan_check import plan, task, ROOT
            frozen = plan([task('T1', ['a']), task('T2', ['a/child']), task('T3', ['b'])])
            frozen.pop('closure_matrix')
            failed = run_evidence(ROOT, 'HEAD', [sys.executable, '-c', 'import time; time.sleep(5)'], .05)
            envelope = {'plan': frozen, 'task_results': {'T2': {'status': 'PARTIAL',
                'blocker': {'reason': 'native acceptance tool timed out', 'evidence': failed}}},
                'final_acceptance': []}
            result = self.next_plan(envelope, ROOT)
            self.assertEqual('execute', result['status'])
            self.assertEqual('T3', result['next_action']['task_id'])
            self.assertEqual(['T1'], result['progress']['waiting'])
            self.assertEqual(['T2'], result['progress']['blocked'])
        finally:
            sys.path.remove(str(fixture_dir))

    def test_ordinary_plan_cli_uses_audited_results_and_reports_remaining_blockers(self):
        from delivery_next import plan_check_module
        from evidence_contract import run_evidence
        fixture_dir = Path(__file__).resolve().parents[1] / "skills/converge-plan/scripts"
        sys.path.insert(0, str(fixture_dir))
        try:
            from test_plan_check import plan, task, PROJECT_SOURCE, ROOT
            frozen = plan([task("T1", ["a"]), task("T2", ["b"])])
            frozen.pop("closure_matrix")
            evidence = run_evidence(ROOT, "HEAD", [sys.executable, "-c", "import time; time.sleep(5)"], .05)
            envelope = {"plan": frozen, "task_results": {"T1": {
                "status": "PARTIAL", "blocker": {"reason": "native acceptance tool timed out", "evidence": evidence},
            }}, "final_acceptance": []}
            runtime_path=self.runtime(envelope,ROOT)
            envelope['final_acceptance']=[{'criterion':frozen['final_acceptance'][0], 'result':'unknown',
                'freshness':'unavailable','evidence':evidence}]
            self.runtime(envelope,ROOT)
            argv = [sys.executable, str(Path(__file__).with_name("plan_execution.py")),
                    "--input", "-", "--workspace", str(ROOT), "--implementation-authorized"]
            result = subprocess.run(argv, input=json.dumps(envelope), capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)
            decision = json.loads(result.stdout)
            self.assertEqual("T2", decision["next_action"]["task_id"])
            self.assertEqual(["T1"], decision["progress"]["blocked"])
            self.assertFalse(plan_check_module().audit(envelope, ROOT)["complete"])
            from plan_execution import next_plan_action
            runtime=json.loads(runtime_path.read_text())
            for entry in runtime['ledger']['acceptance']:
                entry.pop('evidence_receipts', None)
            runtime_path.write_text(json.dumps(runtime))
            unrecorded=next_plan_action(envelope,ROOT,implementation_authorized=True)
            self.assertEqual('blocked',unrecorded['status']);self.assertIn('persist final tooling',unrecorded['reason'])
            self.runtime(envelope,ROOT)
            runtime=json.loads(runtime_path.read_text());runtime.update(status='blocked',blocked_code='no_progress',blocked_reason='writer not cleared')
            runtime_path.write_text(json.dumps(runtime))
            self.assertEqual('blocked',next_plan_action(envelope,ROOT,implementation_authorized=True)['status'])
            self.runtime(envelope,ROOT)
            from runner_contract import freeze_launch
            from multi_model import resolve
            runtime=json.loads(runtime_path.read_text())
            runtime['ledger']['runner_launches']=[freeze_launch(resolve()['roles']['scout'],'observe only',{})]
            runtime_path.write_text(json.dumps(runtime))
            unresolved=next_plan_action(envelope,ROOT,implementation_authorized=True)
            self.assertEqual('blocked',unresolved['status'])
            self.assertIn('runner cleanup',unresolved['reason'])
            self.runtime(envelope,ROOT)
            from test_delivery_next import runtime_binding, cleanup_receipt, delegated_state
            runtime=json.loads(runtime_path.read_text())
            runtime['runtime_binding']=runtime_binding()
            runtime['worker_tree_receipt']=cleanup_receipt(runtime['runtime_binding'],runtime['revision'],[],[],[],'2026-10-08T00:00:00Z')
            runtime_path.write_text(json.dumps(runtime))
            self.assertEqual('execute',next_plan_action(envelope,ROOT,implementation_authorized=True)['status'])
            runtime['execution_control']['routing']=delegated_state()['execution_control']['routing']
            runtime['workers']=[{'ref':'live-writer','role':'implementer','task_id':runtime['task_key'],
                'owner_run_id':runtime['run_id'],'status':'working','parent_ref':None,'depth':1,'may_dispatch':False,'progress':None}]
            runtime['worker_tree_receipt']=cleanup_receipt(runtime['runtime_binding'],runtime['revision'],['live-writer'],['live-writer'],[],'2026-10-08T00:00:00Z')
            runtime_path.write_text(json.dumps(runtime))
            live=next_plan_action(envelope,ROOT,implementation_authorized=True)
            self.assertEqual('blocked',live['status'])
            self.assertRegex(live['reason'], 'worker cleanup|host-observed tree-query')
            self.runtime(envelope,ROOT)
            with tempfile.TemporaryDirectory() as directory:
                copied=Path(directory)/'copied-state.json';copied.write_bytes(runtime_path.read_bytes())
                envelope['runtime_state_path']=str(copied)
                self.assertEqual('blocked',next_plan_action(envelope,ROOT,implementation_authorized=True)['status'])
            self.runtime(envelope,ROOT)
            runtime=json.loads(runtime_path.read_text());runtime['writer_id']='another-writer'
            runtime_path.write_text(json.dumps(runtime))
            self.assertEqual('blocked',next_plan_action(envelope,ROOT,implementation_authorized=True)['status'])
            self.runtime(envelope,ROOT)
            envelope['task_results']['T1']['evidence']=[run_evidence(ROOT,'HEAD',[sys.executable,'-c','raise SystemExit(1)'])]
            self.assertEqual('blocked',next_plan_action(envelope,ROOT,implementation_authorized=True)['status'])
            envelope['task_results']['T1'].pop('evidence')
            self.assertEqual("blocked", next_plan_action(envelope, ROOT, implementation_authorized=False)["status"])
            envelope["task_results"]["T2"] = {"status": "DONE", "fresh_pass": True,
                "source_before": PROJECT_SOURCE, "source_after": PROJECT_SOURCE, "evidence": []}
            self.assertEqual("blocked", next_plan_action(envelope, ROOT, implementation_authorized=True)["status"])
        finally:
            sys.path.remove(str(fixture_dir))

    def test_ordinary_plan_recovery_requires_same_tool_pass_and_does_not_repeat_failed_repair(self):
        from plan_execution import next_plan_action
        from evidence_contract import run_evidence
        fixture_dir = Path(__file__).resolve().parents[1] / "skills/converge-plan/scripts"
        sys.path.insert(0, str(fixture_dir))
        try:
            from test_plan_check import plan, task, ROOT
            with tempfile.TemporaryDirectory() as directory:
                marker = Path(directory) / "ready"
                argv = [sys.executable, "-c", f"from pathlib import Path; import time; time.sleep(0 if Path({str(marker)!r}).exists() else 5)"]
                frozen = plan([task("T1", ["a"]), task("T2", ["b"], depends_on=["T1"])])
                frozen.pop("closure_matrix")
                failed = run_evidence(ROOT, "HEAD", argv, .05)
                result = {"status": "PARTIAL", "blocker": {"reason": "native acceptance tool timed out", "evidence": failed}}
                envelope = {"plan": frozen, "task_results": {"T1": result}, "final_acceptance": []}
                self.assertEqual("blocked", self.next_plan(envelope, ROOT)["status"])
                marker.touch()
                import copy
                original = copy.deepcopy(result)
                result.update(status="NOT_DONE", prior_attempt=original,
                              recovery_evidence=run_evidence(ROOT, "HEAD", argv))
                self.assertEqual("T1", self.next_plan(envelope, ROOT)["next_action"]["task_id"])
                runtime_path=Path(envelope['runtime_state_path'])
                runtime=json.loads(runtime_path.read_text())
                from test_delivery_next import committed_attempt
                attempt=committed_attempt()
                attempt['action']={'action':'execute-inline','task_id':'T1','phase':'implementation-recovery'}
                runtime['execution_control']['autonomy']['action_attempts']=[attempt]
                runtime_path.write_text(json.dumps(runtime))
                replay=next_plan_action(envelope,ROOT,implementation_authorized=True)
                self.assertEqual('blocked',replay['status']);self.assertIn('recovery budget',replay['reason'])
                lost=copy.deepcopy(envelope);lost['task_results'].pop('T1')
                self.assertEqual('blocked',next_plan_action(lost,ROOT,implementation_authorized=True)['status'])
                attempt['action']['phase']='implementation'
                runtime['execution_control']['autonomy']['action_attempts']=[attempt]
                runtime_path.write_text(json.dumps(runtime))
                self.assertEqual('blocked',next_plan_action(lost,ROOT,implementation_authorized=True)['status'])
                result["status"] = "PARTIAL"
                self.assertEqual("blocked", self.next_plan(envelope, ROOT)["status"])
                runtime_path=Path(envelope['runtime_state_path']);runtime=json.loads(runtime_path.read_text())
                attempt['observation']={'outcome':'failed','receipt_fingerprint':failed['receipt_fingerprint']}
                runtime['execution_control']['autonomy']['action_attempts']=[attempt];runtime_path.write_text(json.dumps(runtime))
                check=[sys.executable,'-c','pass'];proof=run_evidence(ROOT,'HEAD',check)
                import shlex
                forged=copy.deepcopy(envelope);forged['plan']['tasks'][0]['verification']=[shlex.join(check)]
                forged['task_results']['T1']={'status':'DONE','fresh_pass':True,'source_before':proof['source'],
                    'source_after':proof['source'],'evidence':[proof]}
                self.assertEqual('blocked',next_plan_action(forged,ROOT,implementation_authorized=True)['status'])
                for item in envelope['plan']['tasks']:item['verification']=[shlex.join(check)]
                result.update(status='DONE',fresh_pass=True,source_before=proof['source'],source_after=proof['source'],evidence=[proof])
                envelope['task_results']['T2']={'status':'DONE','fresh_pass':True,'source_before':proof['source'],
                    'source_after':proof['source'],'evidence':[proof]}
                envelope['final_acceptance']=[{'criterion':frozen['final_acceptance'][0],'result':'pass','freshness':'fresh','evidence':proof}]
                original_action=copy.deepcopy(attempt);original_action['attempt_id']='original-T1'
                early=committed_attempt();early.update(attempt_id='early-T2',action={'action':'execute-inline','task_id':'T2','phase':'implementation'})
                recovered=committed_attempt();recovered.update(attempt_id='recovered-T1',action={'action':'execute-inline','task_id':'T1','phase':'implementation-recovery'})
                runtime['execution_control']['autonomy']['action_attempts']=[original_action,early,recovered]
                runtime_path.write_text(json.dumps(runtime))
                chronological=next_plan_action(envelope,ROOT,implementation_authorized=True)
                self.assertEqual('blocked',chronological['status']);self.assertIn('dependency order',chronological['reason'])
        finally:
            sys.path.remove(str(fixture_dir))

    def test_acceptance_tool_timeout_or_unavailability_does_not_revoke_authorization(self):
        for reason in ("native acceptance tool timed out", "native acceptance tool is unavailable"):
            for authorized in (True, False):
                with self.subTest(reason=reason, authorized=authorized):
                    result = decide("B02b", implementation_authorized=authorized,
                                    validation=classify_validation_failure(reason))
                    self.assertEqual("execute" if authorized else "blocked", result["status"])
                    if authorized:
                        self.assertEqual(reason, result["uncovered_reason"])
                        self.assertEqual("implementation", result["next_action"]["phase"])

    def test_ordinary_plan_source_changes_do_not_erase_recorded_actual_failure(self):
        import copy, shlex
        from evidence_contract import run_evidence, workspace_source
        from plan_execution import next_plan_action
        fixture_dir = Path(__file__).resolve().parents[1] / 'skills/converge-plan/scripts'
        sys.path.insert(0, str(fixture_dir))
        try:
            from test_plan_check import plan, task
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'repo'
                root.mkdir()
                def git(*args):
                    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()
                git('init', '-q'); git('config', 'user.name', 'Jeff.Liu')
                git('config', 'user.email', 'test@example.invalid')
                (root / 'base').write_text('base'); git('add', '.'); git('commit', '-qm', 'baseline')
                baseline = git('rev-parse', 'HEAD')
                initial = workspace_source(root, baseline)
                check = [sys.executable, '-c', 'pass']
                tasks = [task('T1', ['a']), task('T2', ['b'])]
                for item in tasks:
                    item['verification'] = [shlex.join(check)]
                frozen = plan(tasks); frozen.pop('closure_matrix')
                frozen['baseline'].update(commit=baseline, source=initial)
                marker = Path(directory) / 'recovered'
                argv = [sys.executable, '-c', f'from pathlib import Path; assert Path({str(marker)!r}).exists()']
                failed = run_evidence(root, baseline, argv)
                (root / 'a').write_text('independent implementation')
                current = workspace_source(root, baseline)
                envelope = {'plan': frozen, 'task_results': {'T1': {'status': 'DONE', 'fresh_pass': True,
                    'source_before': initial, 'source_after': current, 'evidence': [run_evidence(root, baseline, check)]}},
                    'final_acceptance': []}
                runtime_path = self.runtime(envelope, root)
                runtime = json.loads(runtime_path.read_text())
                runtime['ledger']['acceptance_history'] = [{'revision': 0, 'acceptance': {
                    'criterion': frozen['final_acceptance'][0], 'evidence': 'actual verification failure',
                    'result': 'fail', 'freshness': 'fresh',
                    'source_fingerprint': failed['source']['source_fingerprint'], 'evidence_receipts': [failed]}}]
                runtime_path.write_text(json.dumps(runtime))
                decision = next_plan_action(envelope, root, implementation_authorized=True)
                self.assertEqual('blocked', decision['status'])
                self.assertIn('actual final verification failure', decision['reason'])
                marker.touch()
                envelope['final_acceptance'] = [{'criterion': frozen['final_acceptance'][0], 'result': 'unknown',
                    'freshness': 'fresh', 'evidence': run_evidence(root, baseline, argv)}]
                for field, value in [('freshness', 'stale'), ('source_fingerprint', '0' * 64), ('result', 'fail')]:
                    invalid = copy.deepcopy(envelope)
                    invalid['final_acceptance'][0][field] = value
                    self.assertEqual('blocked', next_plan_action(invalid, root, implementation_authorized=True)['status'])
                resumed = next_plan_action(envelope, root, implementation_authorized=True)
                self.assertEqual('execute', resumed['status'])
                self.assertEqual('T2', resumed['next_action']['task_id'])
        finally:
            sys.path.remove(str(fixture_dir))

    def test_source_cycles_are_reconstructed_and_unjoined_partial_edges_block(self):
        import copy, shlex
        from evidence_contract import run_evidence, workspace_source
        fixture_dir=Path(__file__).resolve().parents[1]/'skills/converge-plan/scripts'
        sys.path.insert(0,str(fixture_dir))
        try:
            from test_plan_check import plan,task
            with tempfile.TemporaryDirectory() as directory:
                root=Path(directory)/'repo';root.mkdir()
                def git(*args):return subprocess.check_output(['git','-C',str(root),*args]).decode().strip()
                git('init','-q');git('config','user.name','Jeff.Liu');git('config','user.email','test@example.invalid')
                (root/'base').write_text('base');git('add','.');git('commit','-qm','baseline')
                baseline=git('rev-parse','HEAD');initial=workspace_source(root,baseline)
                check=[sys.executable,'-c','pass']
                tasks=[task('T3',['c']),task('T1',['a']),task('T2',['a'],depends_on=['T1'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                marker=Path(directory)/'ready'
                argv=[sys.executable,'-c',f'from pathlib import Path; import time; time.sleep(0 if Path({str(marker)!r}).exists() else 5)']
                failed=run_evidence(root,baseline,argv,.05)
                historical_tool_gap=run_evidence(root,baseline,['missing-converge-final-acceptance-tool'])
                original={'status':'PARTIAL','blocker':{'reason':'native acceptance tool timed out','evidence':failed}}
                (root/'a').write_text('temporary');middle=workspace_source(root,baseline)
                first={'status':'DONE','fresh_pass':True,'source_before':initial,'source_after':middle,'evidence':[run_evidence(root,baseline,check)]}
                (root/'a').unlink()
                second={'status':'DONE','fresh_pass':True,'source_before':middle,'source_after':initial,'evidence':[run_evidence(root,baseline,check)]}
                marker.touch();recovery=run_evidence(root,baseline,argv)
                (root/'c').write_text('final');final=workspace_source(root,baseline)
                recovered={'status':'DONE','fresh_pass':True,'prior_attempt':original,'blocker':original['blocker'],
                           'recovery_evidence':recovery,'source_before':initial,'source_after':final,'evidence':[run_evidence(root,baseline,check)]}
                envelope={'plan':frozen,'task_results':{'T3':recovered,'T1':first,'T2':second},'final_acceptance':[]}
                self.assertEqual('verify',self.next_plan(envelope,root)['status'])
                (root/'c').unlink()
                dependent_noop=copy.deepcopy(envelope)
                dependent_noop['plan']['tasks'][0]['depends_on']=['T2']
                dependent_noop['task_results']['T3']={'status':'DONE','fresh_pass':True,
                    'source_before':initial,'source_after':initial,'evidence':[run_evidence(root,baseline,check)]}
                self.assertEqual('verify',self.next_plan(dependent_noop,root)['status'])
                (root/'c').write_text('final')
                envelope['final_acceptance']=[{'criterion':frozen['final_acceptance'][0], 'result':'fail',
                    'freshness':'fresh','evidence':run_evidence(root,baseline,[sys.executable,'-c','raise SystemExit(1)'])}]
                failed_final=self.next_plan(envelope,root)
                self.assertEqual('blocked',failed_final['status']);self.assertIn('final verification failure',failed_final['reason'])
                final_marker=Path(directory)/'final-ready'
                final_check=[sys.executable,'-c',f'from pathlib import Path; assert Path({str(final_marker)!r}).exists()']
                previous_failure=run_evidence(root,baseline,final_check)
                final_marker.touch()
                envelope['final_acceptance'][0].update(result='pass',freshness='fresh',evidence=run_evidence(root,baseline,final_check))
                runtime_path=self.runtime(envelope,root);runtime=json.loads(runtime_path.read_text())
                runtime['ledger']['acceptance_history']=[{'revision':0,'acceptance':{
                    'criterion':frozen['final_acceptance'][0],'evidence':'observed verification failure',
                    'result':'fail','freshness':'fresh',
                    'source_fingerprint':previous_failure['source']['source_fingerprint'],
                    'evidence_receipts':[previous_failure]}}]
                runtime_path.write_text(json.dumps(runtime))
                from plan_execution import next_plan_action
                self.assertEqual('complete',next_plan_action(envelope,root,implementation_authorized=True)['status'])
                envelope['final_acceptance'][0].update(result='unknown',freshness='unavailable',evidence=failed)
                runtime_path=self.runtime(envelope,root);runtime=json.loads(runtime_path.read_text())
                runtime.update(status='blocked',current_stage='verify-final',blocked_code='environment',
                    blocked_reason='final acceptance tooling remains uncovered; no independent task remains')
                runtime_path.write_text(json.dumps(runtime))
                recovered_final=run_evidence(root,baseline,argv)
                envelope['final_acceptance'][0].update(result='pass',freshness='fresh',evidence=recovered_final)
                self.assertEqual('complete',next_plan_action(envelope,root,implementation_authorized=True)['status'])
                from delivery_state import validate_transition
                candidate=copy.deepcopy(runtime)
                candidate.update(status='complete',blocked_code=None,blocked_reason=None,revision=runtime['revision']+1)
                old=candidate['ledger']['acceptance'][0]
                candidate['ledger'].setdefault('acceptance_history',[]).append({'revision':runtime['revision'],'acceptance':copy.deepcopy(old)})
                old.update(result='pass',freshness='fresh',source_fingerprint=recovered_final['source']['source_fingerprint'],
                    evidence_receipts=[recovered_final])
                validate_transition(runtime,candidate)
                actual_failure = run_evidence(root, baseline, [sys.executable, '-c', 'raise SystemExit(1)'])
                archived = {'revision': runtime['revision'], 'acceptance': {
                    'criterion': old['criterion'], 'evidence': 'unresolved actual verification failure',
                    'result': 'fail', 'freshness': 'fresh',
                    'source_fingerprint': actual_failure['source']['source_fingerprint'],
                    'evidence_receipts': [actual_failure]}}
                unresolved = copy.deepcopy(runtime)
                unresolved['ledger'].setdefault('acceptance_history', []).append(archived)
                unresolved_candidate = copy.deepcopy(candidate)
                unresolved_candidate['ledger']['acceptance_history'].insert(0, archived)
                with self.assertRaisesRegex(ValueError, 'blocked status is immutable'):
                    validate_transition(unresolved, unresolved_candidate)
                from delivery_next import validate_state
                from types import SimpleNamespace
                with self.assertRaises(ValueError):
                    validate_state(candidate,SimpleNamespace(),check_workspace=True)
                for code,reason in [('decision',runtime['blocked_reason']),('environment','actual verification failed')]:
                    unsafe=copy.deepcopy(runtime);unsafe.update(blocked_code=code,blocked_reason=reason)
                    runtime_path.write_text(json.dumps(unsafe))
                    self.assertEqual('blocked',next_plan_action(envelope,root,implementation_authorized=True)['status'])
                    with self.assertRaises(ValueError):
                        validate_transition(unsafe,candidate)
                replay=copy.deepcopy(candidate);replay.update(status='active')
                with self.assertRaises(ValueError):
                    validate_transition(runtime,replay)
                envelope['final_acceptance'][0].update(result='unknown',freshness='unavailable',
                    evidence=run_evidence(root,baseline,['missing-converge-final-acceptance-tool']))
                remaining=self.next_plan(envelope,root)
                self.assertEqual('blocked',remaining['status']);self.assertIn('tooling',remaining['reason'])
                envelope['final_acceptance'][0]['evidence']=historical_tool_gap
                remaining=self.next_plan(envelope,root)
                self.assertEqual('blocked',remaining['status']);self.assertIn('tooling',remaining['reason'])
                runtime_path=Path(envelope['runtime_state_path'])
                runtime=json.loads(runtime_path.read_text())
                runtime['ledger']['acceptance_history']=[{'revision':0,'acceptance':{
                    'criterion':frozen['final_acceptance'][0],'evidence':'observed tool failure',
                    'result':'unknown','freshness':'unavailable',
                    'source_fingerprint':historical_tool_gap['source']['source_fingerprint'],
                    'evidence_receipts':[historical_tool_gap]}}]
                runtime_path.write_text(json.dumps(runtime))
                envelope['final_acceptance']=[]
                from plan_execution import next_plan_action
                remaining=next_plan_action(envelope,root,implementation_authorized=True)
                self.assertEqual('blocked',remaining['status']);self.assertIn('tooling',remaining['reason'])
                envelope['final_acceptance']=[{'criterion':frozen['final_acceptance'][0], 'result':'pass',
                    'freshness':'fresh','evidence':run_evidence(root,baseline,check)}]
                remaining=next_plan_action(envelope,root,implementation_authorized=True)
                self.assertEqual('blocked',remaining['status']);self.assertIn('tooling',remaining['reason'])
                envelope['final_acceptance']=[]
                tasks[1]['depends_on']=['T2'];tasks[2]['depends_on']=[]
                violated=self.next_plan(envelope,root)
                self.assertEqual('blocked',violated['status']);self.assertIn('source boundary',violated['reason'])
                tasks=[task('T1',['a']),task('T2',['c']),task('T3',['b'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                partial={**original,'source_before':middle,'source_after':initial}
                envelope={'plan':frozen,'task_results':{'T1':partial,'T2':{'status':'DONE','fresh_pass':True,
                    'source_before':initial,'source_after':final,'evidence':[run_evidence(root,baseline,check)]}},'final_acceptance':[]}
                result=self.next_plan(envelope,root)
                self.assertEqual('blocked',result['status']);self.assertIn('source boundary',result['reason'])
                (root/'c').unlink()
                tasks=[task('T1',['a']),task('T2',['a'],depends_on=['T4']),
                       task('T3',['b']),task('T4',['b'],depends_on=['T3'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                results={};cursor=initial
                for task_id,path,remove in [('T3','b',False),('T4','b',True),('T1','a',False),('T2','a',True)]:
                    if remove:(root/path).unlink()
                    else:(root/path).write_text('temporary')
                    proof=run_evidence(root,baseline,check)
                    results[task_id]={'status':'DONE','fresh_pass':True,'source_before':cursor,
                        'source_after':proof['source'],'evidence':[proof]}
                    cursor=proof['source']
                self.assertEqual('verify',self.next_plan({'plan':frozen,'task_results':results,'final_acceptance':[]},root)['status'])
                tasks=[task('T1',['a']),task('T2',['a'],depends_on=['T1']),task('T3',['b']),
                    task('T4',['b'],depends_on=['T3']),task('T5',['c'],depends_on=['T4'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                results={};cursor=initial
                for tid,path,operation in [('T3','b','add'),('T4','b','remove'),('T1','a','add'),('T5','c','noop'),('T2','a','remove')]:
                    if operation=='add':(root/path).write_text('temporary')
                    elif operation=='remove':(root/path).unlink()
                    proof=run_evidence(root,baseline,check)
                    results[tid]={'status':'DONE','fresh_pass':True,'source_before':cursor,'source_after':proof['source'],'evidence':[proof]}
                    cursor=proof['source']
                self.assertEqual('verify',self.next_plan({'plan':frozen,'task_results':results,'final_acceptance':[]},root)['status'])
                tasks=[task('T1',['a']),task('T2',['a'],depends_on=['T1']),task('T3',['b'],depends_on=['T1'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                marker.unlink();(root/'a').write_text('temporary');middle=workspace_source(root,baseline)
                failed=run_evidence(root,baseline,argv,.05)
                prior={'status':'PARTIAL','source_before':initial,'source_after':middle,
                    'blocker':{'reason':'native acceptance tool timed out','evidence':failed}}
                dependent={'status':'DONE','fresh_pass':True,'source_before':middle,'source_after':middle,
                    'evidence':[run_evidence(root,baseline,check)]}
                (root/'a').unlink();marker.touch();proof=run_evidence(root,baseline,check)
                recovered={'status':'DONE','fresh_pass':True,'prior_attempt':prior,'blocker':prior['blocker'],
                    'recovery_evidence':run_evidence(root,baseline,argv),'source_before':initial,'source_after':initial,'evidence':[proof]}
                results={'T1':recovered,'T2':{'status':'DONE','fresh_pass':True,'source_before':middle,'source_after':initial,'evidence':[proof]},'T3':dependent}
                envelope={'plan':frozen,'task_results':results,'final_acceptance':[{'criterion':frozen['final_acceptance'][0],
                    'result':'pass','freshness':'fresh','evidence':proof}]}
                self.assertEqual('blocked',self.next_plan(envelope,root)['status'])
                envelope['task_results']['T1']['prior_attempt'].update(source_before=initial,source_after=initial)
                with self.assertRaisesRegex(ValueError,'failure.*boundary'):
                    self.next_plan(envelope,root)
                tasks=[task('T1',['b']),task('T4',['a']),task('T2',['a'],depends_on=['T1','T4']),task('T3',['c'],depends_on=['T1'])]
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline,source=initial)
                marker.unlink();(root/'a').write_text('temporary');middle=workspace_source(root,baseline)
                failed=run_evidence(root,baseline,argv,.05)
                prior={'status':'PARTIAL','blocker':{'reason':'native acceptance tool timed out','evidence':failed}}
                change={'status':'DONE','fresh_pass':True,'source_before':initial,'source_after':middle,'evidence':[run_evidence(root,baseline,check)]}
                dependent={'status':'DONE','fresh_pass':True,'source_before':middle,'source_after':middle,'evidence':[run_evidence(root,baseline,check)]}
                (root/'a').unlink();marker.touch();proof=run_evidence(root,baseline,check)
                recovered={'status':'DONE','fresh_pass':True,'prior_attempt':prior,'blocker':prior['blocker'],
                    'recovery_evidence':run_evidence(root,baseline,argv),'source_before':initial,'source_after':initial,'evidence':[proof]}
                results={'T1':recovered,'T4':change,'T2':{'status':'DONE','fresh_pass':True,'source_before':middle,'source_after':initial,'evidence':[proof]},'T3':dependent}
                envelope={'plan':frozen,'task_results':results,'final_acceptance':[{'criterion':frozen['final_acceptance'][0],
                    'result':'pass','freshness':'fresh','evidence':proof}]}
                self.assertEqual('blocked',self.next_plan(envelope,root)['status'])
        finally:sys.path.remove(str(fixture_dir))

    def test_tooling_classification_requires_executor_observation(self):
        from evidence_contract import run_evidence
        from plan_execution import require_tool_failure
        from test_delivery_next import WORKSPACE, HEAD
        failed = run_evidence(WORKSPACE, HEAD, [sys.executable, '-c', 'raise SystemExit(124)'])
        with self.assertRaisesRegex(ValueError, 'observed tooling'):
            require_tool_failure('native acceptance tool timed out', failed)
        timed = run_evidence(WORKSPACE, HEAD, [sys.executable, '-c', 'import time; time.sleep(5)'], .05)
        require_tool_failure('native acceptance tool timed out', timed)
        self.assertEqual('timed_out', timed['tooling_failure'])
        missing = run_evidence(WORKSPACE, HEAD, ['missing-converge-native-tool-20261008'])
        require_tool_failure('native acceptance tool is unavailable', missing)
        self.assertEqual('unavailable', missing['tooling_failure'])

    def test_later_block_and_partial_recovery_keep_the_actual_source_chain(self):
        import copy, shlex
        from evidence_contract import run_evidence, workspace_source
        from plan_execution import next_plan_action
        from delivery_next import plan_check_module
        fixture_dir = Path(__file__).resolve().parents[1] / 'skills/converge-plan/scripts'
        sys.path.insert(0, str(fixture_dir))
        try:
            from test_plan_check import plan, task
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / 'repo'; root.mkdir()
                def git(*args):
                    return subprocess.check_output(['git', '-C', str(root), *args]).decode().strip()
                git('init', '-q'); git('config', 'user.name', 'Jeff.Liu'); git('config', 'user.email', 'test@example.invalid')
                (root/'base').write_text('base');git('add','.');git('commit','-qm','baseline')
                baseline = git('rev-parse','HEAD'); initial = workspace_source(root, baseline)
                tasks = [task('T1',['a']),task('T2',['b']),task('T3',['c'])]
                check = [sys.executable,'-c','pass']
                for item in tasks:item['verification']=[shlex.join(check)]
                frozen=plan(tasks);frozen.pop('closure_matrix');frozen['baseline'].update(commit=baseline, source=initial)
                noop_evidence=run_evidence(root,baseline,check)
                (root/'a').write_text('first');after=workspace_source(root,baseline)
                done={'status':'DONE','fresh_pass':True,'source_before':initial,'source_after':after,
                      'evidence':[run_evidence(root,baseline,check)]}
                failargv=[sys.executable,'-c','import time; time.sleep(5)']
                failed=run_evidence(root,baseline,failargv,.05)
                blocked={'status':'PARTIAL',
                         'blocker':{'reason':'native acceptance tool timed out','evidence':failed}}
                envelope={'plan':frozen,'task_results':{'T1':done,'T2':blocked},'final_acceptance':[]}
                self.assertEqual('T3',self.next_plan(envelope,root)['next_action']['task_id'])
                (root/'c').write_text('independent'); independent=workspace_source(root,baseline)
                envelope['task_results']['T3']={'status':'DONE','fresh_pass':True,'source_before':after,
                                               'source_after':independent,'evidence':[run_evidence(root,baseline,check)]}
                stopped=self.next_plan(envelope,root)
                self.assertEqual('no independently executable task',stopped['reason'])
                envelope['task_results'].pop('T3');(root/'c').unlink()
                (root/'b').write_text('partial');partial=workspace_source(root,baseline)
                blocked.update(source_before=after,source_after=partial)
                blocked['blocker']['evidence']=run_evidence(root,baseline,failargv,.05)
                original=copy.deepcopy(blocked)
                recovered={'status':'NOT_DONE','prior_attempt':original,
                           'blocker':original['blocker'], 'recovery_evidence':run_evidence(root,baseline,failargv,10)}
                envelope['task_results']['T2']=recovered
                self.assertEqual('T2',self.next_plan(envelope,root)['next_action']['task_id'])
                (root/'b').write_text('fixed');final=workspace_source(root,baseline)
                recovered.update(status='DONE',fresh_pass=True,source_before=partial,source_after=final,
                                 evidence=[run_evidence(root,baseline,check)])
                self.assertEqual('DONE',plan_check_module().audit(envelope,root)['tasks']['T2'])
                self.assertEqual('T3',self.next_plan(envelope,root)['next_action']['task_id'])
                envelope['task_results']['T3']={'status':'DONE','fresh_pass':True,'source_before':initial,
                                               'source_after':initial,'evidence':[noop_evidence]}
                self.assertEqual('verify',self.next_plan(envelope,root)['status'])
                recovered.pop('prior_attempt')
                with self.assertRaisesRegex(ValueError,'original attempt history'):
                    plan_check_module().audit(envelope,root)
        finally:sys.path.remove(str(fixture_dir))

    def test_native_preflight_gap_cli_continues_only_with_authorization(self):
        with tempfile.TemporaryDirectory() as workspace:
            for authorized in (True, False):
                with self.subTest(authorized=authorized):
                    argv = [sys.executable, str(Path(__file__).with_name("plan_execution.py")),
                            "--task-id", "B02b", "--native-preflight-workspace", workspace]
                    if authorized:
                        argv.append("--implementation-authorized")
                    completed = subprocess.run(argv, text=True, capture_output=True, check=False)
                    self.assertEqual(0, completed.returncode, completed.stderr)
                    result = json.loads(completed.stdout)
                    self.assertEqual("execute" if authorized else "blocked", result["status"])
                    if authorized:
                        self.assertIn("codegraph_index", result["uncovered_reason"])
                        self.assertIn("coverage", result["uncovered_reason"])
                    self.assertEqual([], list(Path(workspace).iterdir()))

    def test_ready_native_preflight_retains_normal_execution(self):
        from plan_execution import main
        from io import StringIO

        output = StringIO()
        with patch.object(sys, "argv", ["plan_execution.py", "--task-id", "B02b",
                                       "--implementation-authorized", "--native-preflight-workspace", "."]), \
                patch("tdd_impact_guard.preflight", return_value={"status": "ready"}) as preflight, \
                patch("sys.stdout", output):
            main()
        preflight.assert_called_once_with(".")
        result = json.loads(output.getvalue())
        self.assertEqual("execute", result["status"])
        self.assertIsNone(result["uncovered_reason"])

    def test_acceptance_failure_is_not_a_tooling_gap(self):
        for reason in ("acceptance test failed", "permission denied", "missing decision",
                       "native acceptance tool timed out; permission denied"):
            with self.subTest(reason=reason):
                self.assertEqual({"status": "blocked", "reason": reason},
                                 decide("B02b", implementation_authorized=True,
                                        validation=classify_validation_failure(reason)))

    def test_authorized_tooling_gap_continues_with_an_uncovered_receipt(self):
        validation = classify_validation_failure("closure path has no indexed files")

        self.assertEqual(
            {
                "status": "execute",
                "next_action": {
                    "action": "execute-inline",
                    "task_id": "T1",
                    "phase": "implementation",
                },
                "uncovered_reason": "closure path has no indexed files",
            },
            decide("T1", implementation_authorized=True, validation=validation),
        )

    def test_uncovered_tooling_gap_without_write_authorization_does_not_execute(self):
        validation = classify_validation_failure("CodeGraph requires a fresh index and verified graph bindings")

        self.assertEqual(
            {"status": "blocked", "reason": "implementation_authorization_required"},
            decide("T1", implementation_authorized=False, validation=validation),
        )

    def test_non_tooling_plan_failure_remains_blocked(self):
        validation = classify_validation_failure("unknown dependency: T99")

        self.assertEqual(
            {"status": "blocked", "reason": "unknown dependency: T99"},
            decide("T1", implementation_authorized=True, validation=validation),
        )

    def test_valid_plan_executes_without_an_uncovered_reason(self):
        self.assertEqual(
            {
                "status": "execute",
                "next_action": {
                    "action": "execute-inline",
                    "task_id": "T1",
                    "phase": "implementation",
                },
                "uncovered_reason": None,
            },
            decide("T1", implementation_authorized=True, validation={"status": "valid"}),
        )

    def test_decide_rejects_malformed_inputs_before_choosing_an_action(self):
        with self.assertRaisesRegex(ValueError, "task_id"):
            decide("  ", implementation_authorized=True, validation={"status": "valid"})
        with self.assertRaisesRegex(ValueError, "boolean"):
            decide("T1", implementation_authorized="yes", validation={"status": "valid"})
        with self.assertRaisesRegex(ValueError, "must be an object"):
            decide("T1", implementation_authorized=True, validation="valid")
        with self.assertRaisesRegex(ValueError, "validation result is invalid"):
            decide("T1", implementation_authorized=True, validation={"status": "uncovered"})
        with self.assertRaisesRegex(ValueError, "must be a non-empty string"):
            decide("T1", implementation_authorized=True, validation={
                "status": "blocked", "reason": " ",
            })

    def test_cli_emits_one_structured_execute_or_block_decision(self):
        script = Path(__file__).with_name("plan_execution.py")
        valid = subprocess.run(
            [sys.executable, str(script), "--task-id", "T1", "--implementation-authorized"],
            text=True, capture_output=True, check=False,
        )
        blocked = subprocess.run(
            [sys.executable, str(script), "--task-id", "T1", "--validation-error", "missing decision"],
            text=True, capture_output=True, check=False,
        )

        self.assertEqual(0, valid.returncode, valid.stderr)
        self.assertEqual("execute", json.loads(valid.stdout)["status"])
        self.assertEqual(0, blocked.returncode, blocked.stderr)
        self.assertEqual(
            {"status": "blocked", "reason": "missing decision"},
            json.loads(blocked.stdout),
        )


if __name__ == "__main__":
    unittest.main()
