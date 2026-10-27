"""Real-file regressions for blind evidence handoff and bounded blocked review recovery."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import delivery_state
import runner_lifecycle
from evidence_contract import run_evidence, workspace_source
from multi_model import resolve
from role_dispatch import plan_dispatch
from role_result import observe_local_evidence, prompt_for_review, review_result
from runner_contract import bind_role_result, fingerprint
from runner_launch import plan_dispatch_launch
from test_runner_lifecycle import flow_state, managed_state, review_request
from test_multimodel_recovery import receipt


class ReviewEnvironmentRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root/'scripts').mkdir()
        (self.root/'scripts/test_case.py').write_text('import unittest\nclass Check(unittest.TestCase):\n def test_ok(self): self.assertEqual(2, 1+1)\n')
        subprocess.run(['git','-C',str(self.root),'add','.'],check=True)
        subprocess.run(['git','-C',str(self.root),'-c','user.name=Test','-c','user.email=test@example.invalid','commit','-qm','fixture'],check=True)
        self.head = subprocess.check_output(['git','-C',str(self.root),'rev-parse','HEAD'],text=True).strip()
        self.source = workspace_source(self.root,self.head)
        self.state = managed_state(self.root)
        self.state.update(status='blocked',blocked_code='environment',baseline={'commit':self.head},source_fingerprint=self.source['source_fingerprint'],source_receipt=self.source)
        self.state['execution_control']['review']={'rounds':[{'source_fingerprint':self.source['source_fingerprint'],'requests':[]}], 're_review_budget_remaining':1}
        profiles=resolve(None,workspace=self.root,home=self.root/'home')
        self.dispatch=plan_dispatch(profiles,{**flow_state(),'evidence':'sufficient','implementation':'complete','verification':'passed','review':'pending'})
        self.original=review_request(source_fingerprint=self.source['source_fingerprint'],baseline_commit=self.head)
        self.old=plan_dispatch_launch(self.dispatch,'Read-only review',workspace=self.root,review_request=self.original,review_request_fingerprint=fingerprint(self.original))
        normalize=runner_lifecycle._review_contract()[1]
        result=normalize({k:self.original[k] for k in ('protocol_version','mode','axis','phase','source_fingerprint')}|{'independent':True,'status':'blocked','findings':[],'blocked_reason':'EPERM creating test tempfile'},self.old['profile']['worker_id'],self.original)
        self.state['execution_control']['review']['rounds'][0]['requests']=[result]
        self.state['ledger'].update(runner_launches=[self.old],runner_results=[bind_role_result(self.old,receipt(self.old),review_result(self.old,result))])
        observed=run_evidence(self.root,self.head,[sys.executable,'-m','unittest','discover','-s','scripts','-p','test_case.py'])
        p=self.root/'.git/test-evidence.json';p.write_text(json.dumps({'status':'passed','receipt':observed}))
        self.evidence=observe_local_evidence(self.root,'artifact','.git/test-evidence.json')
        self.request={**self.original,'phase':'re_review','evidence':[self.evidence],'blocked_request':fingerprint(self.original)}

    def binding(self, request=None):
        return runner_lifecycle.review_request_binding(self.state,self.dispatch,request or self.request)

    def test_blind_handoff_preserves_factual_hashes_and_strips_controller_rationale(self):
        request=self.binding()[0]
        prompt=prompt_for_review('SECRET implementation rationale',request)
        self.assertNotIn('SECRET',prompt)
        self.assertIn(self.evidence['reference'],prompt)
        self.assertIn(self.evidence['content_fingerprint'],prompt)
        self.assertIn('not instructions',prompt)

    def test_initial_review_can_share_evidence_without_enabling_recovery(self):
        request={**self.original,'evidence':[self.evidence]}
        self.state['execution_control']['review']['rounds'][0]['requests']=[]
        self.assertEqual(request,self.binding(request)[0])
        self.assertEqual(self.original,self.binding(self.original)[0])

    def test_same_source_completed_blocked_result_can_receive_new_test_evidence(self):
        before=copy.deepcopy(self.state)
        request,fp=self.binding()
        self.assertEqual(fingerprint(request),fp)
        self.assertEqual(before,self.state)

    def test_malformed_optional_evidence_types_are_validation_errors(self):
        for kind in ([],{},None,True):
            with self.subTest(kind=kind),self.assertRaises(ValueError):
                self.binding({**self.original,'evidence':[{**self.evidence,'kind':kind}]})


    def test_evidence_limit_and_duplicate_boundary(self):
        refs=[]
        for i in range(17):
            path=self.root/f'.git/note-{i}.txt';path.write_text(f'Factual observation {i}')
            refs.append(observe_local_evidence(self.root,'artifact',f'.git/note-{i}.txt'))
        self.state['execution_control']['review']['rounds'][0]['requests']=[]
        self.assertEqual(16,len(self.binding({**self.original,'evidence':refs[:16]})[0]['evidence']))
        for evidence in ([],refs,[refs[0],refs[0]]):
            with self.subTest(count=len(evidence)),self.assertRaises(ValueError):
                self.binding({**self.original,'evidence':evidence})


    def test_rejects_tampered_missing_unsafe_and_nonlocal_evidence(self):
        cases=[{**self.evidence,'content_fingerprint':'0'*64},
               {**self.evidence,'reference':'.git/missing.json'},
               {**self.evidence,'reference':'../outside.json'},
               {'kind':'command','reference':'echo pass','content_fingerprint':'0'*64}]
        (self.root/'.git/link.json').symlink_to(self.root/'.git/test-evidence.json')
        cases.append({**self.evidence,'reference':'.git/link.json'})
        for evidence in cases:
            with self.subTest(evidence=evidence),self.assertRaises((OSError,ValueError)):
                self.binding({**self.request,'evidence':[evidence]})

    def test_existing_receipt_repacking_or_path_change_is_not_evidence_progress(self):
        wrapper=json.loads((self.root/'.git/test-evidence.json').read_text())
        for raw_original in (False,True):
            with self.subTest(raw_original=raw_original):
                previous_path=self.root/'.git/previous.json'
                previous_path.write_text(json.dumps(wrapper['receipt'] if raw_original else wrapper))
                previous=observe_local_evidence(self.root,'artifact','.git/previous.json')
                original={**self.original,'evidence':[previous]}
                launch=plan_dispatch_launch(self.dispatch,'Review',workspace=self.root,
                    review_request=original,review_request_fingerprint=fingerprint(original))
                record=runner_lifecycle._review_contract()[1](
                    {k:original[k] for k in ('protocol_version','mode','axis','phase','source_fingerprint')}
                    |{'independent':True,'status':'blocked','findings':[],'blocked_reason':'readonly tempfile denied'},
                    launch['profile']['worker_id'],original)
                self.state['execution_control']['review']['rounds'][0]['requests']=[record]
                self.state['ledger'].update(runner_launches=[launch],runner_results=[
                    bind_role_result(launch,receipt(launch),review_result(launch,record))])
                path=self.root/'.git/repacked.json';path.write_text(json.dumps(wrapper,indent=3))
                repacked=observe_local_evidence(self.root,'artifact','.git/repacked.json')
                self.assertNotEqual(previous['content_fingerprint'],repacked['content_fingerprint'])
                with self.assertRaises(ValueError):
                    self.binding({**self.request,'blocked_request':fingerprint(original),'evidence':[repacked]})


    def test_rejects_stale_failed_non_test_and_already_handed_evidence(self):
        value=json.loads((self.root/'.git/test-evidence.json').read_text())
        for change in ('stale','failed','non-test','seen'):
            with self.subTest(change=change):
                state=copy.deepcopy(self.state);modified=copy.deepcopy(value)
                if change=='stale':modified['receipt']['source']['source_fingerprint']='0'*64
                elif change=='failed':modified['receipt']['exit_code']=1
                elif change=='non-test':modified['receipt'].pop('test_check',None)
                else:
                    state['ledger']['runner_launches'][0]['configuration']['review_request']['evidence']=[self.evidence]
                if change!='seen':
                    raw=modified['receipt'];raw['receipt_fingerprint']=fingerprint({k:v for k,v in raw.items() if k!='receipt_fingerprint'})
                    p=self.root/'.git/changed.json';p.write_text(json.dumps(modified));e=observe_local_evidence(self.root,'artifact','.git/changed.json')
                else:e=self.evidence
                with self.assertRaises(ValueError):
                    runner_lifecycle.review_request_binding(state,self.dispatch,{**self.request,'evidence':[e]})

    def test_rejects_wrong_axis_wrong_target_missing_budget_and_unknown_transport(self):
        for change in ('axis','target','budget','unknown','not-blocked','not-initial','findings'):
            with self.subTest(change=change):
                state=copy.deepcopy(self.state);req=copy.deepcopy(self.request)
                record=state['execution_control']['review']['rounds'][0]['requests'][0]
                if change=='axis':req['axis']='quality'
                elif change=='target':req['blocked_request']='0'*64
                elif change=='budget':state['execution_control']['review']['re_review_budget_remaining']=0
                elif change=='unknown':state['ledger']['runner_results']=[]
                elif change=='not-blocked':record['status']='pass'
                elif change=='not-initial':record['phase']='re_review'
                else:record['finding_fingerprints']=['f'*64]
                with self.assertRaises(ValueError):runner_lifecycle.review_request_binding(state,self.dispatch,req)

    def test_non_environment_block_or_unbound_active_run_cannot_recover(self):
        for change in ({'status':'active'},{'blocked_code':'decision'}):
            with self.subTest(change=change):
                state={**self.state,**change}
                with self.assertRaises(ValueError):
                    runner_lifecycle.review_request_binding(state,self.dispatch,self.request)


    def test_shared_spec_blocked_result_without_independence_can_resume(self):
        original={**self.original,'mode':'shared'}
        launch=plan_dispatch_launch(self.dispatch,'Shared spec',workspace=self.root,
            review_request=original,review_request_fingerprint=fingerprint(original))
        record=runner_lifecycle._review_contract()[1](
            {k:original[k] for k in ('protocol_version','mode','axis','phase','source_fingerprint')}
            |{'independent':False,'status':'blocked','findings':[],'blocked_reason':'readonly tempfile denied'},
            launch['profile']['worker_id'],original)
        self.state['execution_control']['review']['rounds'][0]['requests']=[record]
        self.state['ledger'].update(runner_launches=[launch],runner_results=[
            bind_role_result(launch,receipt(launch),review_result(launch,record))])
        request={**self.request,'mode':'shared','blocked_request':fingerprint(original)}
        self.assertEqual(request,self.binding(request)[0])


    def test_repeated_recovery_is_rejected_even_with_remaining_budget(self):
        launch=copy.deepcopy(self.old);launch['configuration']['review_request']=self.request
        self.state['ledger']['runner_launches'].append(launch)
        with self.assertRaises(ValueError):self.binding()

    def test_environment_recheck_allows_only_one_bound_format_recovery(self):
        from types import SimpleNamespace
        from delivery_state import _validate_runner_record
        from role_result import invalid_result
        from runner_contract import role_results_complete
        from test_runner_lifecycle import review_response

        self.state.update(status='active', blocked_code=None)
        self.state['execution_control']['review']['recovery'] = {
            'request_fingerprint': fingerprint(self.request),
            'blocked_request': self.request['blocked_request'], 'previous_controller': {},
        }
        failed = plan_dispatch_launch(self.dispatch, 'Environment recheck', workspace=self.root,
            review_request=self.request, review_request_fingerprint=fingerprint(self.request))
        self.state['ledger']['runner_launches'].append(failed)
        self.state['ledger']['runner_results'].append(bind_role_result(failed, receipt(failed),
            invalid_result(failed, 'invalid JSON', reason='invalid_json')))
        before = copy.deepcopy(self.state)
        arguments = SimpleNamespace(allow_execute=True, allow_network=False, task_key='task-1',
            run_id='run-1', writer_id='writer-1', repo_id='repo', lease_root=None, state_root=None,
            codex_bin=failed['configuration']['codex_bin'], claude_bin='claude', review_request=self.request,
            review_request_fingerprint=None, recover_launch=failed['launch_fingerprint'])

        def append(args, field, record):
            _validate_runner_record(self.state, field, record)
            self.state['ledger'][field].append(record)
            return args.expected_revision + 1

        def execute(launch, *_args, **_kwargs):
            return {'receipt': receipt(launch), 'output': {
                'status': 'available', 'content': review_response(self.request)}}

        result = runner_lifecycle.run_dispatch(arguments, self.dispatch, 'Correct the format',
            load=lambda _: self.state, append=append, execute=execute, preflight=lambda *_: None)
        self.assertEqual('completed', result['status'])
        self.assertTrue(role_results_complete(self.state['ledger']['runner_launches'],
                                             self.state['ledger']['runner_results']))
        self.assertEqual(before['execution_control'], self.state['execution_control'])
        self.assertEqual(before['ledger']['runner_results'], self.state['ledger']['runner_results'][:2])
        for target in (None, self.old['launch_fingerprint'], failed['launch_fingerprint'],
                       result['launch']['launch_fingerprint']):
            with self.subTest(target=target), self.assertRaises(ValueError):
                arguments.recover_launch = target
                runner_lifecycle.run_dispatch(arguments, self.dispatch, 'Another attempt',
                    load=lambda _: self.state, append=append, execute=execute, preflight=lambda *_: None)

    def test_blocked_request_does_not_bypass_normal_finding_focus(self):
        for patch_value in ({'phase':'initial'},{'prior_findings':['f'*64]},{'evidence':[]}):
            with self.subTest(value=patch_value),self.assertRaises(ValueError):self.binding({**self.request,**patch_value})

    def test_completed_evidence_requests_bind_to_prerequisite_and_final_state(self):
        from delivery_next import _external_request_matches_state
        for request in ({**self.original,'evidence':[self.evidence]},self.request):
            with self.subTest(phase=request['phase']):
                launch=plan_dispatch_launch(self.dispatch,'Review',workspace=self.root,
                    review_request=request,review_request_fingerprint=fingerprint(request))
                record=runner_lifecycle._review_contract()[1](
                    {k:request[k] for k in ('protocol_version','mode','axis','phase','source_fingerprint')}
                    |{'independent':True,'status':'pass','findings':[]},launch['profile']['worker_id'],request)
                kwargs=dict(task_key=self.state['task_key'],baseline_commit=self.head,
                            source_fingerprint=self.state['source_fingerprint'],
                            acceptance=request['acceptance'],allowed_scope=request['allowed_scope'])
                self.assertTrue(_external_request_matches_state(launch,record,**kwargs))
                tampered=copy.deepcopy(launch);tampered['configuration']['review_request']['evidence'][0]['content_fingerprint']='f'*64
                self.assertFalse(_external_request_matches_state(tampered,record,**kwargs))


    def test_existing_initial_cannot_be_reopened_instead_of_recovery(self):
        with self.assertRaises(ValueError):self.binding(self.original)


    def test_active_recovery_freezes_dispatch_identity(self):
        self.state['execution_control']['review']['recovery']={
            'request_fingerprint':fingerprint(self.request),
            'blocked_request':self.request['blocked_request'], 'previous_controller':{}}
        with self.assertRaises(ValueError):self.binding(self.original)
        self.assertEqual(self.request,self.binding()[0])


    def test_real_resume_cli_preserves_receipts_and_rejects_duplicate_or_stale_revision(self):
        from autonomy_begin import initial_state
        from controller_snapshot import create_snapshot
        from delivery_engine import controller_identity
        from delivery_state import state_path, project_state_root, project_lease_root
        root=Path(__file__).resolve().parents[1]
        with patch('controller_snapshot.PROTOCOL_VERSION',22):
            old=create_snapshot(root,self.root/'.git/controllers',('multimodel',))
        new=create_snapshot(root,self.root/'.git/controllers',('multimodel',))
        state=initial_state(self.root,['Review recovery'],['Review behavior'],['scripts'],
                            'run-1','writer-1',mode='native',task_kind='fix',
                            extensions=('multimodel',),controller=controller_identity(snapshot=old))
        state.update(task_key='task-1',status='blocked',blocked_code='environment',
                     blocked_reason='readonly tempfile denied',current_stage='round-1-semantic-review')
        state['execution_control']['review'].update(self.state['execution_control']['review'])
        state['ledger'].update({key:self.state['ledger'][key] for key in ('runner_launches','runner_results')})
        sr=project_state_root(self.root);lr=project_lease_root(self.root)
        common=['--state-root',str(sr),'--lease-root',str(lr),'--repo-id',state['repo_id'],
                '--task-key',state['task_key'],'--run-id','run-1','--writer-id','writer-1']
        lease=[sys.executable,str(root/'scripts/delivery_lease.py'),'acquire','--root',str(lr),
               '--repo',state['repo_id'],'--workspace',str(self.root),'--task-key','task-1',
               '--run-id','run-1','--writer-id','writer-1']
        subprocess.run(lease,check=True,capture_output=True)
        command=[sys.executable,str(root/'scripts/delivery_state.py')]
        seed=subprocess.run([*command,'write','--input','-',*common,'--expected-revision','-1'],
                            input=json.dumps(state),text=True,capture_output=True)
        self.assertEqual(0,seed.returncode,seed.stderr)
        payload=json.dumps({'review_request':self.request,'controller_snapshot':new})
        resume=[*command,'resume-review','--input','-',*common,'--expected-revision','0']
        unsupported=json.dumps({'review_request':self.request,'controller_snapshot':old})
        rejected=subprocess.run(resume,input=unsupported,text=True,capture_output=True)
        self.assertNotEqual(0,rejected.returncode)
        self.assertEqual(state,json.loads(state_path(sr,state['repo_id'],'task-1','run-1').read_text()))
        result=subprocess.run(resume,input=payload,text=True,capture_output=True)
        self.assertEqual(0,result.returncode,result.stderr)
        path=state_path(sr,state['repo_id'],'task-1','run-1');after=json.loads(path.read_text())
        self.assertEqual('active',after['status']);self.assertEqual(1,after['revision'])
        self.assertEqual(state['ledger'],after['ledger'])
        self.assertEqual(1,after['execution_control']['review']['re_review_budget_remaining'])
        self.assertEqual(state['controller'],after['execution_control']['review']['recovery']['previous_controller'])
        self.assertEqual(23,after['controller']['protocol_version'])
        for revision in ('0','1'):
            result=subprocess.run([*resume[:-1],revision],input=payload,text=True,capture_output=True)
            self.assertNotEqual(0,result.returncode)
            self.assertEqual(after,json.loads(path.read_text()))


    def test_recovery_candidate_changes_only_status_revision_and_explicit_controller(self):
        old_controller={'snapshot':{'extensions':['multimodel']},'extensions':['multimodel']}
        new_controller={**old_controller,'protocol_version':23,
                        'snapshot':{**old_controller['snapshot'],'protocol_version':23}}
        state=copy.deepcopy(self.state)
        state.update(status='blocked',blocked_code='environment',blocked_reason='readonly sandbox',controller=old_controller,workers=[],run_id='run-1',writer_id='writer-1',repo_id='/repo')
        before=copy.deepcopy(state)
        with patch('delivery_state.validate_candidate'),patch('controller_snapshot.validate_snapshot',side_effect=lambda x:x):
            result=delivery_state.resume_review_candidate(state,self.request,new_controller)
        expected=copy.deepcopy(before);expected['execution_control']['review']['recovery']={'request_fingerprint':fingerprint(self.request),'blocked_request':self.request['blocked_request'],'previous_controller':old_controller};expected.update(status='active',blocked_code=None,blocked_reason=None,controller=new_controller,revision=before['revision']+1)
        self.assertEqual(expected,result)
        self.assertEqual(before,state)
        padded={**self.request,'task_id':' '+self.request['task_id']+' '}
        canonical=runner_lifecycle._review_contract()[0](padded)
        with patch('delivery_state.validate_candidate'),patch('controller_snapshot.validate_snapshot',side_effect=lambda x:x):
            normalized=delivery_state.resume_review_candidate(state,padded,new_controller)
        self.assertEqual(fingerprint(canonical),normalized['execution_control']['review']['recovery']['request_fingerprint'])
        for change in ({'blocked_code':'permission'},{'status':'active'},{'workers':[{'status':'working'}]}):
            with self.subTest(change=change),patch('delivery_state.validate_candidate'),self.assertRaises(ValueError):
                delivery_state.resume_review_candidate({**state,**change},self.request,new_controller)


if __name__=='__main__':unittest.main()
