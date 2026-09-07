import importlib.util
import copy
import hashlib
import json
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))
from delivery_engine import provider_reference
from delivery_next import upgrade_state
from delivery_state import state_path as delegate_state_path
from provider_contract import canonical_fingerprint
from test_delivery_next import state as single_state, tdd_trace, configure_coverage_fixture, routing
from evidence_contract import run_evidence, workspace_source


MODULE_PATH = Path(__file__).with_name("batch_state.py")
SPEC = importlib.util.spec_from_file_location("batch_state", MODULE_PATH)
batch_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_state)


def provider_binding(workflow="native-v1"):
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference(workflow, "feature"),
        "stage_providers": {},
    }
    return {
        "selection": "auto",
        "reason": "frozen for Batch",
        "task_kind": "feature",
        "binding": binding,
        "binding_fingerprint": canonical_fingerprint(binding),
    }


def capsule(batch_id, plan_id="plan-1", task_id=None, baseline="abc123"):
    return {
        "planned_task": True,
        "plan_id": plan_id,
        "task_id": task_id or batch_id.replace("B", "T"),
        "batch_id": batch_id,
        "goal": f"goal-{batch_id}",
        "scope": ["."],
        "global_constraints": ["keep compatibility"],
        "consumes": ["baseline"],
        "produces": [f"output-{batch_id}"],
        "baseline": baseline,
        "acceptance": [f"accept-{batch_id}"],
        "verification": [shlex.join([sys.executable, "-c", "pass", batch_id])],
        "provider_binding": provider_binding(),
    }


def receipt(batch_id, dispatch_id, commit_id, tree_hash, workspace=None, baseline=None):
    value = {
        "protocol_version": 4,
        "batch_id": batch_id,
        "dispatch_id": dispatch_id,
        "commit_id": commit_id,
        "tree_hash": tree_hash,
        "verified_tree_hash": tree_hash,
        "parent_commit_id": baseline or commit_id,
        "acceptance": [
            {
                "criterion": f"accept-{batch_id}",
                "evidence": f"test-{batch_id}",
                "result": "pass",
                "freshness": "fresh",
                "source_fingerprint": "a" * 64,
            }
        ],
        "open_issues": [],
    }
    if workspace is not None:
        run_id = f"delegate-{batch_id}"
        child = upgrade_state(single_state(
            run_id=run_id,
            writer_id=f"writer-{batch_id}",
            repo_id=str(Path(workspace) / ".git"),
            workspace=str(workspace),
            task_key=batch_id.replace("B", "T"),
            status="complete",
            current_stage="verify-final",
            baseline={"commit": baseline or commit_id, "diff_fingerprint": "clean"},
        ))
        try:
            child["source_receipt"] = workspace_source(workspace, baseline or commit_id)
        except ValueError:
            child["source_receipt"] = workspace_source(workspace, "HEAD")
        child["source_fingerprint"] = child["source_receipt"]["source_fingerprint"]
        child["ledger"]["acceptance"][0].update(criterion=f"accept-{batch_id}", evidence=f"test-{batch_id}")
        child["ledger"]["tdd_trace"] = tdd_trace(
            child["source_receipt"], criterion=child["ledger"]["acceptance"][0]["criterion"]
        )
        child["execution_control"]["review"]["rounds"] = []
        child["ledger"]["acceptance"][0]["source_fingerprint"] = child["source_fingerprint"]
        child["ledger"]["acceptance"][0]["evidence_receipts"] = [run_evidence(
            workspace, child["source_receipt"]["baseline_commit"],
            [sys.executable, "-c", "pass", batch_id],
        )]
        state_root = Path(workspace).parent / "delegate-state"
        path = delegate_state_path(
            state_root, child["repo_id"], child["task_key"], child["run_id"]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(child), encoding="utf-8")
        value["acceptance"][0]["source_fingerprint"] = child["source_fingerprint"]
        value.update(
            delegate_run_id=run_id,
            delegate_state_revision=child["revision"],
            delegate_source_fingerprint=child["source_fingerprint"],
            delegate_source_receipt=child["source_receipt"],
        )
    return value


def candidate(workspace, revision=0):
    baseline = subprocess.check_output(
        ["git", "-C", str(workspace), "rev-parse", "HEAD"], text=True
    ).strip()
    return {
        "schema_version": 4,
        "run_id": "batch-run-1",
        "writer_id": "scheduler-1",
        "revision": revision,
        "repo_id": str(workspace / ".git"),
        "workspace": str(workspace),
        "delegate_state_root": str(workspace.parent / "delegate-state"),
        "plan": {
            "plan_id": "plan-1",
            "plan_revision": 1,
            "plan_fingerprint": "f" * 64,
        },
        "preflight": {
            "passed": True,
            "checked_at": "2026-08-20T00:00:00Z",
            "issues": [],
            "commit_authorized": True,
        },
        "status": "active",
        "current_batch": "B1",
        "batches": [
            {
                "batch_id": "B1",
                "task_id": "T1",
                "status": "pending",
                "capsule": capsule("B1", baseline=baseline),
                "dispatch_id": None,
                "worker_ref": None,
                "worker_role": None,
                "worker_owner_run_id": None,
                "worker_status": None,
                "delegate_run_id": None,
                "recovery_count": 0,
                "receipt": None,
            },
            {
                "batch_id": "B2",
                "task_id": "T2",
                "status": "pending",
                "capsule": capsule("B2", baseline=baseline),
                "dispatch_id": None,
                "worker_ref": None,
                "worker_role": None,
                "worker_owner_run_id": None,
                "worker_status": None,
                "delegate_run_id": None,
                "recovery_count": 0,
                "receipt": None,
            },
        ],
        "final_acceptance": [
            {"criterion": "whole-plan", "evidence": None, "result": "unknown", "freshness": "unavailable", "source_fingerprint": None}
        ],
        "blocked_reason": None,
    }


def lifecycle_candidate(workspace, revision=0):
    return candidate(workspace, revision)


def register_worker(state, index, worker_ref):
    state["batches"][index].update(
        worker_ref=worker_ref,
        worker_role="controller-delegate",
        worker_owner_run_id=state["run_id"],
        worker_status="working",
        delegate_run_id=f"delegate-{state['batches'][index]['batch_id']}",
    )


class BatchStateTest(unittest.TestCase):
    def test_execution_capsule_uses_verified_predecessor_and_preserves_frozen_plan(self):
        state = candidate(self.workspace)
        before = copy.deepcopy(state)
        result = self.execution_capsule(state)
        self.assertEqual(self.commit_id, result["baseline"])
        self.assertEqual(before, state)
        dirty = self.workspace / 'unverified.txt'
        dirty.write_text('not verified')
        rejected = subprocess.run([sys.executable, str(MODULE_PATH), "capsule", "--input", "-"],
                                  input=json.dumps(state), text=True, capture_output=True)
        self.assertEqual(2, rejected.returncode)
        self.assertIn('unverified changes', rejected.stderr)
        dirty.unlink()
        state["current_batch"] = "B2"
        rejected = subprocess.run([sys.executable, str(MODULE_PATH), "capsule", "--input", "-"],
                                  input=json.dumps(state), text=True, capture_output=True)
        self.assertEqual(2, rejected.returncode)

    def execution_capsule(self, state):
        result = subprocess.run([sys.executable, str(MODULE_PATH), "capsule", "--input", "-"],
                                input=json.dumps(state), text=True, capture_output=True)
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)

    def test_disjoint_batch_scopes_use_each_checkpoint_not_cumulative_source(self):
        state = candidate(self.workspace)
        parent = self.commit_id
        for index, batch in enumerate(state['batches']):
            module = f"module-{batch['batch_id']}"
            batch['capsule']['scope'] = [module]
            execution = self.execution_capsule(state)
            self.assertEqual(parent, execution['baseline'])
            self.assertEqual(self.commit_id, batch['capsule']['baseline'])
            target = self.workspace / module / 'implementation.txt'
            target.parent.mkdir()
            target.write_text(module)
            subprocess.run(['git', '-C', str(self.workspace), 'add', module], check=True)
            subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', module], check=True)
            commit = batch_state.git_output(str(self.workspace), 'rev-parse', 'HEAD')
            tree = batch_state.git_output(str(self.workspace), 'rev-parse', 'HEAD^{tree}')
            batch.update(status='completed', dispatch_id=f'dispatch-{index}')
            register_worker(state, index, f'worker-{index}')
            batch['worker_status'] = 'completed'
            batch['receipt'] = receipt(batch['batch_id'], batch['dispatch_id'], commit, tree,
                                       self.workspace, baseline=execution['baseline'])
            batch['receipt']['parent_commit_id'] = parent
            path = delegate_state_path(state['delegate_state_root'], state['repo_id'],
                                       batch['task_id'], batch['delegate_run_id'])
            child = json.loads(path.read_text())
            child['execution_control']['routing'] = routing(allowed_paths=[module])
            path.unlink()  # The real writer must create and validate the managed state.
            leases = Path(self.temporary.name) / 'delegate-leases'
            identity = ['--root', str(leases), '--repo', child['repo_id'], '--workspace', str(self.workspace),
                        '--task-key', child['task_key'], '--run-id', child['run_id'], '--writer-id', child['writer_id']]
            acquired = subprocess.run([sys.executable, str(ROOT_SCRIPTS / 'delivery_lease.py'), 'acquire', *identity],
                                      text=True, capture_output=True)
            self.assertEqual(0, acquired.returncode, acquired.stdout + acquired.stderr)
            write = subprocess.run([sys.executable, str(ROOT_SCRIPTS / 'delivery_state.py'), 'write',
                '--input', '-', '--state-root', state['delegate_state_root'], '--lease-root', str(leases),
                '--repo-id', child['repo_id'], '--task-key', child['task_key'], '--run-id', child['run_id'],
                '--writer-id', child['writer_id'], '--expected-revision', '-1'],
                input=json.dumps(child), text=True, capture_output=True)
            self.assertEqual(0, write.returncode, write.stdout + write.stderr)
            report = subprocess.run([sys.executable, str(ROOT_SCRIPTS / 'delivery_report.py'), '--state', str(path)],
                                    text=True, capture_output=True)
            self.assertEqual(0, report.returncode, report.stderr)
            released = subprocess.run([sys.executable, str(ROOT_SCRIPTS / 'delivery_lease.py'), 'release',
                *identity, '--state-root', state['delegate_state_root']], text=True, capture_output=True)
            self.assertEqual(0, released.returncode, released.stdout + released.stderr)
            state['current_batch'] = 'B2' if index == 0 else None
            batch_state.validate_state(state)
            parent = commit
        self.assertEqual(['module-B2/implementation.txt'],
                         state['batches'][1]['receipt']['delegate_source_receipt']['changed_paths'])
        rejected = subprocess.run([sys.executable, str(MODULE_PATH), "capsule", "--input", "-"],
                                  input=json.dumps(state), text=True, capture_output=True)
        self.assertEqual(2, rejected.returncode)
        self.assertNotIn('Traceback', rejected.stderr)

    def test_capsule_rejects_absolute_or_escaping_scope_before_dispatch(self):
        for scope in ('/', '/tmp', '../outside', 'module/../../outside', '\\tmp'):
            with self.subTest(scope=scope):
                state = candidate(self.workspace)
                state['batches'][0]['capsule']['scope'] = [scope]
                with self.assertRaises(ValueError):
                    self.write(state, -1)

    def test_capsule_commands_must_be_executed_with_exact_arguments(self):
        state = self.completed_first_batch()
        batch_state.validate_state(state)
        for command in (shlex.join([sys.executable, "-c", "raise SystemExit(1)"]),
                        shlex.join([sys.executable, "-c", "pass", "B2"]), "unterminated '"):
            with self.subTest(command=command):
                invalid = copy.deepcopy(state)
                invalid["batches"][0]["capsule"]["verification"].append(command)
                with self.assertRaisesRegex(ValueError, 'verification'):
                    batch_state.validate_state(invalid)
        state["batches"][0]["capsule"]["verification"] = [f'"{sys.executable}" -c "pass" B1']
        batch_state.validate_state(state)

    def test_capsule_scope_rejects_broader_delegate_routing(self):
        state = self.completed_first_batch()
        state["batches"][0]["capsule"]["scope"] = ["module-B1"]
        with self.assertRaisesRegex(ValueError, 'scope'):
            batch_state.validate_state(state)

    def test_scope_is_checked_on_real_checkpoint_delta_before_persisting(self):
        for changed in ("outside.txt", "module-B10/file.txt", "module-B1/inside.txt"):
            with self.subTest(changed=changed):
                state = candidate(self.workspace)
                batch = state["batches"][0]
                batch["capsule"]["scope"] = ["module-B1"]
                # Freeze scope and commands before any execution.
                root = self.root / changed.replace('/', '-')
                batch_state.write_state(root, state, -1)
                batch.update(status="dispatching", dispatch_id="dispatch-B1")
                state["revision"] = 1
                batch_state.write_state(root, state, 0)
                register_worker(state, 0, "fixture-worker")
                batch["status"] = "running"
                state["revision"] = 2
                persisted = batch_state.write_state(root, state, 1)
                target = self.workspace / changed
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(changed)
                subprocess.run(['git', '-C', str(self.workspace), 'add', changed], check=True)
                subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', 'checkpoint'], check=True)
                commit = batch_state.git_output(str(self.workspace), 'rev-parse', 'HEAD')
                tree = batch_state.git_output(str(self.workspace), 'rev-parse', 'HEAD^{tree}')
                batch.update(status="validating-receipt", worker_status="completed")
                batch["receipt"] = receipt('B1', 'dispatch-B1', commit, tree, self.workspace,
                                           baseline=batch["capsule"]["baseline"])
                path = delegate_state_path(state["delegate_state_root"], state["repo_id"], 'T1', 'delegate-B1')
                child = json.loads(path.read_text())
                child['execution_control']['routing'] = routing(allowed_paths=['module-B1'])
                path.write_text(json.dumps(child))
                state['revision'] = 3
                if changed == 'module-B1/inside.txt':
                    batch_state.write_state(root, state, 2)
                    self.assertEqual(3, json.loads(persisted.read_text())['revision'])
                else:
                    with self.assertRaisesRegex(ValueError, 'scope'):
                        batch_state.write_state(root, state, 2)
                    self.assertEqual(2, json.loads(persisted.read_text())['revision'])

    def test_terminal_takeover_preserves_worker_provenance_and_allows_cleanup(self):
        for status in ("blocked", "stopped"):
            for outcome in ("completed", "interrupted", "blocked"):
                with self.subTest(status=status, outcome=outcome), tempfile.TemporaryDirectory() as root:
                    before = candidate(self.workspace)
                    before["batches"][0].update(status="running", dispatch_id="dispatch-B1")
                    register_worker(before, 0, "thread-1")
                    before["status"] = status
                    if status == "blocked": before["blocked_reason"] = "manual cleanup: thread-1"
                    path = batch_state.write_state(root, before, -1)
                    replacement = copy.deepcopy(before)
                    replacement.update(revision=1, run_id="replacement-run", writer_id="replacement-writer")
                    with self.assertRaises(ValueError):
                        batch_state.write_state(root, replacement, 0, takeover=True)
                    lease = batch_state.scheduler_lease_path(root, before["repo_id"], before["plan"]["plan_id"])
                    record = json.loads(lease.read_text())
                    record["lease_expires_at"] = "2000-01-01T00:00:00Z"
                    lease.write_text(json.dumps(record))
                    with self.assertRaises(ValueError):
                        batch_state.write_state(root, replacement, 0)
                    batch_state.write_state(root, replacement, 0, takeover=True)
                    self.assertEqual(before["batches"], json.loads(path.read_text())["batches"])
                    cleaned = copy.deepcopy(replacement)
                    cleaned["revision"] = 2
                    cleaned["batches"][0]["worker_status"] = outcome
                    batch_state.write_state(root, cleaned, 1)
                    self.assertEqual(cleaned, json.loads(path.read_text()))
                    for mutation in ("status", "worker_ref", "worker_owner_run_id"):
                        invalid = copy.deepcopy(cleaned)
                        invalid["revision"] = 3
                        if mutation == "status": invalid["status"] = "active"
                        else: invalid["batches"][0][mutation] = "replacement"
                        with self.assertRaises(ValueError):
                            batch_state.write_state(root, invalid, 2, takeover=True)
                    self.assertEqual(cleaned, json.loads(path.read_text()))

    def test_terminal_cleanup_can_only_finish_existing_workers(self):
        for status in ("blocked", "stopped"):
            for outcome in ("completed", "interrupted", "blocked"):
                with self.subTest(status=status, outcome=outcome), tempfile.TemporaryDirectory() as root:
                    before = candidate(self.workspace)
                    before["batches"][0].update(status="running", dispatch_id="dispatch-B1")
                    register_worker(before, 0, "thread-1")
                    path = batch_state.write_state(root, before, -1)
                    terminal = copy.deepcopy(before)
                    terminal.update(status=status, revision=1)
                    if status == "blocked":
                        terminal["blocked_reason"] = "manual cleanup required: thread-1"
                    batch_state.write_state(root, terminal, 0)
                    cleaned = copy.deepcopy(terminal)
                    cleaned["revision"] = 2
                    cleaned["batches"][0]["worker_status"] = outcome
                    batch_state.write_state(root, cleaned, 1)
                    self.assertEqual(outcome, json.loads(path.read_text())["batches"][0]["worker_status"])
                    for mutation in ("status", "worker_ref", "acceptance", "goal", "worker_status"):
                        invalid = copy.deepcopy(cleaned)
                        invalid["revision"] = 3
                        if mutation == "status": invalid["status"] = "active"
                        elif mutation == "worker_ref": invalid["batches"][0]["worker_ref"] = "replacement"
                        elif mutation == "acceptance": invalid["final_acceptance"][0]["evidence"] = "rewritten"
                        elif mutation == "goal": invalid["batches"][0]["capsule"]["goal"] = "new task"
                        else: invalid["batches"][0]["worker_status"] = "working"
                        with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                            batch_state.write_state(root, invalid, 2)
                    self.assertEqual(cleaned, json.loads(path.read_text()))

    def test_final_acceptance_can_pass_incrementally_without_rewriting_prior_passes(self):
        before = candidate(self.workspace)
        before["final_acceptance"].append(dict(before["final_acceptance"][0], criterion="second acceptance"))
        for index, batch in enumerate(before["batches"]):
            batch.update(status="completed", dispatch_id="dispatch-" + batch["batch_id"])
            register_worker(before, index, "thread-" + str(index))
            batch["worker_status"] = "completed"
            batch["receipt"] = receipt(batch["batch_id"], batch["dispatch_id"], self.commit_id, self.tree_hash, self.workspace)
        before["current_batch"] = None
        path = self.write(before, -1)
        for index in range(2):
            after = copy.deepcopy(before)
            after["revision"] += 1
            observed = run_evidence(self.workspace, self.commit_id, [sys.executable, "-c", f"print({index})"])
            after["final_acceptance"][index].update(
                result="pass", freshness="fresh", evidence=observed,
                source_fingerprint=observed["source"]["source_fingerprint"],
            )
            if index == 1:
                after["status"] = "complete"
                rewritten = copy.deepcopy(after)
                rewritten["final_acceptance"][0]["evidence"] = observed
                with self.assertRaises(ValueError):
                    self.write(rewritten, before["revision"])
            self.write(after, before["revision"])
            before = after
        self.assertEqual("complete", json.loads(path.read_text())["status"])

    def test_receipt_acceptance_must_match_the_verified_delegate(self):
        for mismatch in ("criterion", "evidence", "missing_receipt", "failed", "stale"):
            with self.subTest(mismatch=mismatch):
                state = self.completed_first_batch()
                batch = state["batches"][0]
                batch_state.validate_state(state)
                path = delegate_state_path(Path(state["delegate_state_root"]), state["repo_id"],
                                           batch["task_id"], batch["delegate_run_id"])
                child = json.loads(path.read_text())
                acceptance = child["ledger"]["acceptance"][0]
                if mismatch == "criterion":
                    acceptance["criterion"] = "unrelated behavior"
                    child["ledger"]["tdd_trace"]["acceptance"][0]["criterion"] = "unrelated behavior"
                elif mismatch == "evidence":
                    batch["receipt"]["acceptance"][0]["evidence"] = "unobserved verification"
                elif mismatch == "missing_receipt":
                    acceptance.pop("evidence_receipts")
                elif mismatch == "failed":
                    acceptance["result"] = "fail"
                else:
                    acceptance["freshness"] = "stale"
                path.write_text(json.dumps(child))
                with self.assertRaises(ValueError):
                    batch_state.validate_state(state)

    def test_final_acceptance_identity_is_frozen_before_any_pass(self):
        before = candidate(self.workspace)
        self.write(before, -1)
        for change in ('replace', 'remove', 'duplicate'):
            with self.subTest(change=change):
                after = json.loads(json.dumps(before))
                after['revision'] = 1
                if change == 'replace':
                    after['final_acceptance'][0]['criterion'] = 'easier criterion'
                elif change == 'remove':
                    after['final_acceptance'] = []
                else:
                    after['final_acceptance'].append(dict(after['final_acceptance'][0]))
                with self.assertRaises(ValueError):
                    self.write(after, 0)

    def test_final_acceptance_requires_current_observed_passing_evidence(self):
        state = candidate(self.workspace)
        for index, batch in enumerate(state['batches']):
            batch.update(status='completed', dispatch_id='dispatch-' + batch['batch_id'])
            register_worker(state, index, 'thread-' + str(index))
            batch['worker_status'] = 'completed'
            batch['receipt'] = receipt(batch['batch_id'], batch['dispatch_id'], self.commit_id, self.tree_hash, self.workspace)
        state.update(status='complete', current_batch=None)
        observed = run_evidence(self.workspace, self.commit_id, [sys.executable, '-c', 'pass'])
        entry = state['final_acceptance'][0]
        entry.update(result='pass', freshness='fresh', source_fingerprint=observed['source']['source_fingerprint'])
        for evidence in ('NEVER EXECUTED', None,
                         run_evidence(self.workspace, self.commit_id, [sys.executable, '-c', 'raise SystemExit(1)'])):
            with self.subTest(evidence=type(evidence).__name__):
                entry['evidence'] = evidence
                with self.assertRaises(ValueError):
                    batch_state.validate_state(state)
        entry['evidence'] = observed
        batch_state.validate_state(state)
        observed['exit_code'] = 1
        with self.assertRaises(ValueError):
            batch_state.validate_state(state)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "state"
        self.workspace = (Path(self.temporary.name) / "workspace").resolve()
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"], check=True
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        configure_coverage_fixture(self.workspace)
        subprocess.run(["git", "-C", str(self.workspace), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"], check=True)
        self.commit_id = subprocess.check_output(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"], text=True
        ).strip()
        self.tree_hash = subprocess.check_output(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD^{tree}"], text=True
        ).strip()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, state, expected_revision):
        return batch_state.write_state(self.root, state, expected_revision)

    def completed_first_batch(self):
        state = candidate(self.workspace)
        state['batches'][0].update(status='completed', dispatch_id='dispatch-B1')
        register_worker(state, 0, 'thread-1')
        state['batches'][0]['worker_status'] = 'completed'
        state['batches'][0]['receipt'] = receipt(
            'B1', 'dispatch-B1', self.commit_id, self.tree_hash, self.workspace
        )
        state['current_batch'] = 'B2'
        return state

    def test_later_batch_edits_and_coverage_changes_preserve_historical_receipts(self):
        state = self.completed_first_batch()
        state['batches'][1].update(status='running', dispatch_id='dispatch-B2')
        register_worker(state, 1, 'thread-2')
        batch_state.validate_state(state)
        (self.workspace / 'seed.txt').write_text('Batch 2 implementation\n')
        (self.workspace / 'docs/00_standards/test-commands.yml').write_text('coverage: invalid\n')
        batch_state.validate_state(state)
        subprocess.run(['git', '-C', str(self.workspace), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', 'Batch 2'], check=True)
        batch_state.validate_state(state)
        state['status'] = 'paused'
        batch_state.validate_state(state)

    def test_receipt_rejects_verified_edits_missing_from_checkpoint(self):
        for kind in ('modified', 'untracked', 'deleted', 'mode', 'symlink'):
            with self.subTest(kind=kind):
                seed = self.workspace / 'seed.txt'
                if seed.is_symlink():
                    seed.unlink()
                seed.write_text('seed\n')
                seed.chmod(0o644)
                extra = self.workspace / 'extra.txt'
                extra.unlink(missing_ok=True)
                if kind == 'modified':
                    seed.write_text('verified new content\n')
                elif kind == 'untracked':
                    extra.write_text('verified new file\n')
                elif kind == 'deleted':
                    seed.unlink()
                elif kind == 'mode':
                    seed.chmod(0o755)
                else:
                    seed.unlink()
                    seed.symlink_to('extra.txt')
                state = self.completed_first_batch()
                with self.assertRaisesRegex(ValueError, 'committed|checkpoint'):
                    batch_state.validate_state(state)

    def test_evidence_before_commit_can_bind_to_the_matching_checkpoint(self):
        (self.workspace / 'seed.txt').write_text('verified implementation\n')
        executable = self.workspace / 'new.bin'
        executable.write_bytes(b'\x00\xff\n')
        executable.chmod(0o755)
        (self.workspace / 'link').symlink_to('new.bin')
        state = self.completed_first_batch()
        subprocess.run(['git', '-C', str(self.workspace), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', 'checkpoint'], check=True)
        checkpoint = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD'], text=True).strip()
        tree = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        state['batches'][0]['receipt'].update(commit_id=checkpoint, tree_hash=tree, verified_tree_hash=tree)
        batch_state.validate_state(state)
        # Historical state validation must still reject damaged evidence.
        path = delegate_state_path(self.workspace.parent / 'delegate-state', state['repo_id'], 'T1', 'delegate-B1')
        child = json.loads(path.read_text())
        child['ledger']['acceptance'][0]['evidence_receipts'][0]['exit_code'] = 1
        path.write_text(json.dumps(child))
        with self.assertRaises(ValueError):
            batch_state.validate_state(state)

    def test_checkpoint_cannot_add_unverified_files(self):
        state = self.completed_first_batch()
        (self.workspace / 'unexpected.txt').write_text('not verified\n')
        subprocess.run(['git', '-C', str(self.workspace), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qm', 'unexpected'], check=True)
        checkpoint = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD'], text=True).strip()
        tree = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        state['batches'][0]['receipt'].update(commit_id=checkpoint, tree_hash=tree, verified_tree_hash=tree)
        with self.assertRaisesRegex(ValueError, 'outside the verified changes'):
            batch_state.validate_state(state)

    def test_current_receipt_rejects_workspace_drift_after_verification(self):
        state = self.completed_first_batch()
        state['batches'][0]['status'] = 'validating-receipt'
        state['current_batch'] = 'B1'
        batch_state.validate_state(state)
        (self.workspace / 'seed.txt').write_text('unverified changes\n')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            batch_state.validate_state(state)

    def test_plan_state_path_is_stable_across_scheduler_takeover(self):
        repo = str(self.workspace / ".git")
        first = batch_state.state_path(self.root, repo, "plan-1", "run-1")
        second = batch_state.state_path(self.root, repo, "plan-1", "run-2")

        self.assertEqual(first, second)

    def test_preflight_requires_one_time_commit_authorization_before_dispatch(self):
        missing = candidate(self.workspace)
        missing["preflight"].pop("commit_authorized")
        denied = candidate(self.workspace)
        denied["preflight"]["commit_authorized"] = False

        for value in (missing, denied):
            with self.subTest(preflight=value["preflight"]):
                with self.assertRaisesRegex(ValueError, "commit authorization"):
                    self.write(value, -1)

    def test_schema_v3_capsule_requires_the_frozen_provider_binding(self):
        missing = candidate(self.workspace)
        missing["batches"][0]["capsule"].pop("provider_binding")
        forged = candidate(self.workspace)
        forged["batches"][0]["capsule"]["provider_binding"]["binding_fingerprint"] = "0" * 64

        for value in (missing, forged):
            with self.subTest(capsule=value["batches"][0]["capsule"]):
                with self.assertRaisesRegex(ValueError, "provider binding"):
                    batch_state.validate_state(value)

    def test_completed_receipt_requires_a_terminal_converge_delegate_state(self):
        value = candidate(self.workspace)
        value["batches"][0].update(
            status="validating-receipt", dispatch_id="dispatch-B1",
            worker_ref="thread-1", worker_role="controller-delegate",
            worker_owner_run_id=value["run_id"], worker_status="completed",
            delegate_run_id="delegate-B1",
        )
        value["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash
        )

        with self.assertRaisesRegex(ValueError, "delegate"):
            batch_state.validate_state(value)

    def test_receipt_rejects_an_embedded_self_asserted_delegate_state(self):
        value = candidate(self.workspace)
        value["batches"][0].update(
            status="validating-receipt", dispatch_id="dispatch-B1",
            worker_ref="thread-1", worker_role="controller-delegate",
            worker_owner_run_id=value["run_id"], worker_status="completed",
            delegate_run_id="delegate-B1",
        )
        value["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
        )
        value["batches"][0]["receipt"]["delegate_state"] = {"status": "complete"}

        with self.assertRaisesRegex(ValueError, "self-asserted"):
            batch_state.validate_state(value)

    def test_receipt_must_continue_the_recorded_git_chain(self):
        value = candidate(self.workspace)
        value["batches"][0].update(
            status="validating-receipt", dispatch_id="dispatch-B1",
            worker_ref="thread-1", worker_role="controller-delegate",
            worker_owner_run_id=value["run_id"], worker_status="completed",
            delegate_run_id="delegate-B1",
        )
        value["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
        )
        value["batches"][0]["receipt"]["parent_commit_id"] = "0" * 40

        with self.assertRaisesRegex(ValueError, "chain"):
            batch_state.validate_state(value)

    def test_delegate_run_identity_is_unique_across_batches(self):
        value = candidate(self.workspace)
        value["batches"][0].update(
            status="running", dispatch_id="dispatch-B1", worker_ref="thread-1",
            worker_role="controller-delegate", worker_owner_run_id=value["run_id"],
            worker_status="working", delegate_run_id="shared-run",
        )
        value["batches"][1].update(
            status="running", dispatch_id="dispatch-B2", worker_ref="thread-2",
            worker_role="controller-delegate", worker_owner_run_id=value["run_id"],
            worker_status="working", delegate_run_id="shared-run",
        )

        with self.assertRaisesRegex(ValueError, "unique child run"):
            batch_state.validate_state(value)

    def test_init_and_legal_batch_lifecycle(self):
        state = candidate(self.workspace)
        path = self.write(state, -1)

        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)

        state["revision"] = 2
        state["batches"][0]["status"] = "running"
        register_worker(state, 0, "thread-1")
        self.write(state, 1)

        (self.workspace / 'seed.txt').write_text('Batch 1 implementation\n')
        subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qam', 'Batch 1'], check=True)
        first_commit = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD'], text=True).strip()
        first_tree = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD^{tree}'], text=True).strip()

        state["revision"] = 3
        state["batches"][0]["status"] = "validating-receipt"
        state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", first_commit, first_tree, self.workspace, baseline=self.commit_id
        )
        self.write(state, 2)

        state["revision"] = 4
        state["batches"][0]["status"] = "completed"
        state["batches"][0]["worker_status"] = "completed"
        state["current_batch"] = "B2"
        self.write(state, 3)

        state["revision"] = 5
        state["batches"][1]["status"] = "dispatching"
        state["batches"][1]["dispatch_id"] = "dispatch-B2"
        self.write(state, 4)
        state["revision"] = 6
        state["batches"][1]["status"] = "running"
        register_worker(state, 1, "thread-2")
        self.write(state, 5)
        (self.workspace / 'seed.txt').write_text('Batch 2 implementation\n')
        subprocess.run(['git', '-C', str(self.workspace), 'commit', '-qam', 'Batch 2'], check=True)
        second_commit = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD'], text=True).strip()
        second_tree = subprocess.check_output(['git', '-C', str(self.workspace), 'rev-parse', 'HEAD^{tree}'], text=True).strip()
        state["revision"] = 7
        state["batches"][1]["status"] = "validating-receipt"
        state["batches"][1]["receipt"] = receipt(
            "B2", "dispatch-B2", second_commit, second_tree, self.workspace, baseline=first_commit
        )
        state['batches'][1]['receipt']['parent_commit_id'] = first_commit
        self.write(state, 6)
        state["revision"] = 8
        state["batches"][1]["status"] = "completed"
        state["batches"][1]["worker_status"] = "completed"
        state["current_batch"] = None
        self.write(state, 7)
        state["revision"] = 9
        state["status"] = "complete"
        state["final_acceptance"] = [
            {
                "criterion": "whole-plan", "evidence": run_evidence(
                    self.workspace, self.commit_id, [sys.executable, "-c", "print('e2e passed')"]
                ), "result": "pass",
                "freshness": "fresh",
                "source_fingerprint": workspace_source(self.workspace, self.commit_id)["source_fingerprint"],
            }
        ]
        self.write(state, 8)
        self.assertEqual(9, json.loads(path.read_text(encoding="utf-8"))["revision"])
        (self.workspace / 'seed.txt').write_text('unverified final change\n')
        with self.assertRaisesRegex(ValueError, 'checkpoint'):
            batch_state.validate_state(state)

    def test_应该_当worker启动时_原子登记身份归属和活动状态(self):
        state = lifecycle_candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)
        state["revision"] = 2
        state["batches"][0]["status"] = "running"
        state["batches"][0]["worker_ref"] = "thread-1"

        with self.assertRaisesRegex(ValueError, "worker_role"):
            self.write(state, 1)

        state["batches"][0].update(
            worker_role="controller-delegate",
            worker_owner_run_id="another-run",
            worker_status="working",
            delegate_run_id="delegate-B1",
        )

        with self.assertRaisesRegex(ValueError, "current run"):
            self.write(state, 1)

        state["batches"][0]["worker_owner_run_id"] = state["run_id"]
        self.write(state, 1)

    def test_应该_当回执已到但宿主仍working时_拒绝完成Batch(self):
        state = lifecycle_candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)
        state["revision"] = 2
        state["batches"][0].update(
            status="running",
            worker_ref="thread-1",
            worker_role="controller-delegate",
            worker_owner_run_id=state["run_id"],
            worker_status="working",
            delegate_run_id="delegate-B1",
        )
        self.write(state, 1)
        state["revision"] = 3
        state["batches"][0]["status"] = "validating-receipt"
        state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
        )
        self.write(state, 2)
        state["revision"] = 4
        state["batches"][0]["status"] = "completed"
        state["current_batch"] = "B2"

        with self.assertRaisesRegex(ValueError, "worker_status"):
            self.write(state, 3)

        state["batches"][0]["worker_status"] = "completed"
        self.write(state, 3)

    def test_应该_当前一批仍运行时_拒绝未来pending批次提前登记worker(self):
        state = lifecycle_candidate(self.workspace)
        state["batches"][0].update(status="running", dispatch_id="dispatch-B1")
        register_worker(state, 0, "thread-1")
        register_worker(state, 1, "thread-2")

        with self.assertRaisesRegex(ValueError, "worker lifecycle.*running"):
            batch_state.validate_state(state)

    def test_应该_当批次仍pending或dispatching时_拒绝任何worker生命周期(self):
        for status in ("pending", "dispatching"):
            with self.subTest(status=status):
                state = lifecycle_candidate(self.workspace)
                state["batches"][0]["status"] = status
                if status == "dispatching":
                    state["batches"][0]["dispatch_id"] = "dispatch-B1"
                register_worker(state, 0, "thread-1")

                with self.assertRaisesRegex(ValueError, "worker lifecycle.*running"):
                    batch_state.validate_state(state)

    def test_legacy_batch_schemas_are_rejected(self):
        for schema_version in (1, 2, 3):
            with self.subTest(schema_version=schema_version):
                legacy = candidate(self.workspace)
                legacy["schema_version"] = schema_version
                with self.assertRaisesRegex(ValueError, "schema_version must be 4"):
                    batch_state.validate_state(legacy)

    def test_unknown_batch_schema_fields_are_rejected(self):
        cases = (
            ("state", lambda value: value.__setitem__("legacy_marker", True)),
            ("plan", lambda value: value["plan"].__setitem__("legacy_marker", True)),
            ("preflight", lambda value: value["preflight"].__setitem__("legacy_marker", True)),
            ("batch", lambda value: value["batches"][0].__setitem__("legacy_marker", True)),
            ("capsule", lambda value: value["batches"][0]["capsule"].__setitem__("legacy_marker", True)),
        )
        for location, mutate in cases:
            with self.subTest(location=location):
                value = candidate(self.workspace)
                mutate(value)
                with self.assertRaisesRegex(ValueError, "fields are invalid"):
                    batch_state.validate_state(value)

    def test_unknown_persisted_receipt_and_evidence_fields_are_rejected(self):
        receipt_state = candidate(self.workspace)
        receipt_state["batches"][0].update(
            status="validating-receipt", dispatch_id="dispatch-B1", worker_ref="thread-1",
            worker_role="controller-delegate", worker_owner_run_id=receipt_state["run_id"],
            worker_status="completed", delegate_run_id="delegate-B1",
        )
        receipt_state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
        )
        cases = (
            ("receipt", lambda value: value["batches"][0]["receipt"].__setitem__("legacy_marker", True)),
            ("receipt acceptance", lambda value: value["batches"][0]["receipt"]["acceptance"][0].__setitem__("legacy_marker", True)),
            ("final acceptance", lambda value: value["final_acceptance"][0].__setitem__("legacy_marker", True)),
        )
        for location, mutate in cases:
            with self.subTest(location=location):
                value = json.loads(json.dumps(receipt_state))
                mutate(value)
                with self.assertRaisesRegex(ValueError, "fields are invalid"):
                    batch_state.validate_state(value)

    def test_summary_provider_binding_is_rejected(self):
        value = candidate(self.workspace)
        summary = {
            "controller": "converge",
            "workflow_provider": "pdlc-v1",
            "stage_providers": {},
        }
        summary["binding_fingerprint"] = batch_state.digest(
            json.dumps(summary, sort_keys=True, separators=(",", ":"))
        )
        value["batches"][0]["capsule"]["provider_binding"] = summary

        with self.assertRaisesRegex(ValueError, "provider_binding fields are invalid"):
            batch_state.validate_state(value)

    def test_rejects_stale_revision_plan_drift_and_illegal_jump(self):
        state = candidate(self.workspace)
        self.write(state, -1)

        state["revision"] = 1
        with self.assertRaisesRegex(ValueError, "expected revision"):
            self.write(state, -1)

        state = candidate(self.workspace, revision=1)
        state["plan"]["plan_fingerprint"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "plan is immutable"):
            self.write(state, 0)

        state = candidate(self.workspace, revision=1)
        state["batches"][0]["status"] = "completed"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        register_worker(state, 0, "thread-1")
        state["batches"][0]["worker_status"] = "completed"
        state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
        )
        state["current_batch"] = "B2"
        with self.assertRaisesRegex(ValueError, "invalid batch transition"):
            self.write(state, 0)

    def test_rejects_changed_dispatch_and_mismatched_receipt(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)

        state["revision"] = 2
        state["batches"][0]["dispatch_id"] = "another"
        with self.assertRaisesRegex(ValueError, "dispatch_id is immutable"):
            self.write(state, 1)

        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        state["batches"][0]["status"] = "running"
        register_worker(state, 0, "thread-1")
        self.write(state, 1)
        state["revision"] = 3
        state["batches"][0]["status"] = "validating-receipt"
        state["batches"][0]["receipt"] = receipt(
            "B1", "wrong-dispatch", self.commit_id, self.tree_hash, self.workspace
        )
        with self.assertRaisesRegex(ValueError, "receipt dispatch_id does not match"):
            self.write(state, 2)

    def test_complete_requires_all_batches_and_fresh_final_acceptance(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["status"] = "complete"
        with self.assertRaisesRegex(ValueError, "all batches"):
            self.write(state, 0)

    def test_pause_blocks_new_dispatch_and_batch_block_stops_the_plan(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["status"] = "paused"
        self.write(state, 0)

        state["revision"] = 2
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        with self.assertRaisesRegex(ValueError, "paused plan"):
            self.write(state, 1)

        state["batches"][0]["status"] = "pending"
        state["batches"][0]["dispatch_id"] = None
        state["status"] = "active"
        self.write(state, 1)
        state["revision"] = 3
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 2)
        state["revision"] = 4
        state["batches"][0]["status"] = "blocked"
        with self.assertRaisesRegex(ValueError, "blocked batch"):
            self.write(state, 3)

    def test_rejects_out_of_order_dispatch_and_dispatch_after_stop(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][1]["status"] = "dispatching"
        state["batches"][1]["dispatch_id"] = "dispatch-B2"
        with self.assertRaisesRegex(ValueError, "current batch"):
            self.write(state, 0)

        state = candidate(self.workspace, revision=1)
        state["status"] = "stopped"
        self.write(state, 0)
        state["revision"] = 2
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        with self.assertRaisesRegex(ValueError, "terminal plan"):
            self.write(state, 1)

    def test_receipt_must_resolve_to_the_verified_git_tree(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)
        state["revision"] = 2
        state["batches"][0]["status"] = "running"
        register_worker(state, 0, "thread-1")
        self.write(state, 1)
        state["revision"] = 3
        state["batches"][0]["status"] = "validating-receipt"
        state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", "definitely-not-a-git-commit", "self-asserted-tree",
            self.workspace,
        )
        with self.assertRaisesRegex(ValueError, "baseline|Git commit"):
            self.write(state, 2)

    def test_应该_当胶囊缺少计划身份时_拒绝递归规划风险(self):
        for name, mutate in (
            ("missing planned_task", lambda value: value.pop("planned_task")),
            ("false planned_task", lambda value: value.update(planned_task=False)),
            ("wrong plan_id", lambda value: value.update(plan_id="another-plan")),
            ("missing task_id", lambda value: value.pop("task_id")),
        ):
            with self.subTest(name=name):
                value = candidate(self.workspace)
                mutate(value["batches"][0]["capsule"])
                with self.assertRaises(ValueError):
                    self.write(value, -1)

    def test_应该_当同一计划已有调度者时_拒绝第二个运行窗口(self):
        first = candidate(self.workspace)
        self.write(first, -1)
        second = candidate(self.workspace)
        second["run_id"] = "batch-run-2"
        second["writer_id"] = "scheduler-2"

        with self.assertRaisesRegex(ValueError, "scheduler lease"):
            self.write(second, -1)

        with self.assertRaisesRegex(ValueError, "scheduler lease"):
            batch_state.write_state(self.root, second, -1, takeover=True)

    def test_应该_当调度租约已过期且状态未落盘时_允许显式接管(self):
        stale = candidate(self.workspace)
        lease_path = batch_state.scheduler_lease_path(
            self.root, stale["repo_id"], stale["plan"]["plan_id"]
        )
        lease_path.parent.mkdir(parents=True, exist_ok=True)
        lease_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "run_id": "crashed-run",
                    "writer_id": "crashed-scheduler",
                    "lease_expires_at": "2000-01-01T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        replacement = candidate(self.workspace)
        replacement["run_id"] = "batch-run-2"
        replacement["writer_id"] = "scheduler-2"

        path = batch_state.write_state(self.root, replacement, -1, takeover=True)

        self.assertTrue(path.exists())

    def test_应该_当已有状态被接管时_在同一文件转移owner而不复制状态(self):
        original = candidate(self.workspace)
        path = self.write(original, -1)
        lease_path = batch_state.scheduler_lease_path(
            self.root, original["repo_id"], original["plan"]["plan_id"]
        )
        lease = json.loads(lease_path.read_text(encoding="utf-8"))
        lease["lease_expires_at"] = "2000-01-01T00:00:00Z"
        lease_path.write_text(json.dumps(lease), encoding="utf-8")
        replacement = candidate(self.workspace, revision=1)
        replacement["run_id"] = "batch-run-2"
        replacement["writer_id"] = "scheduler-2"

        written = batch_state.write_state(
            self.root, replacement, 0, takeover=True
        )

        self.assertEqual(path, written)
        self.assertEqual("batch-run-2", json.loads(path.read_text())["run_id"])
        self.assertEqual(1, len(list(path.parent.glob("*.json"))))

    def test_terminal_plan_and_final_acceptance_are_immutable(self):
        previous = candidate(self.workspace)
        previous["status"] = "stopped"
        candidate_state = json.loads(json.dumps(previous))
        candidate_state["revision"] = 1
        candidate_state["final_acceptance"][0]["evidence"] = "rewritten"

        with self.assertRaisesRegex(ValueError, "terminal plan"):
            batch_state.validate_transition(previous, candidate_state)

    def test_takeover_keeps_completed_worker_owner_as_historical_provenance(self):
        value = candidate(self.workspace)
        value["run_id"] = "new-scheduler-run"
        value["writer_id"] = "new-scheduler"
        value["batches"][0].update(
            status="completed", dispatch_id="dispatch-B1", worker_ref="thread-1",
            worker_role="controller-delegate", worker_owner_run_id="old-scheduler-run",
            worker_status="completed", delegate_run_id="delegate-B1",
            receipt=receipt("B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace),
        )
        value["current_batch"] = "B2"

        batch_state.validate_state(value)

    def test_应该_当恢复次数倒退或超过一次时_拒绝状态更新(self):
        state = candidate(self.workspace)
        self.write(state, -1)
        state["revision"] = 1
        state["batches"][0]["status"] = "dispatching"
        state["batches"][0]["dispatch_id"] = "dispatch-B1"
        self.write(state, 0)
        state["revision"] = 2
        state["batches"][0]["status"] = "running"
        register_worker(state, 0, "thread-1")
        self.write(state, 1)
        state["revision"] = 3
        state["batches"][0]["recovery_count"] = 1
        self.write(state, 2)

        state["revision"] = 4
        state["batches"][0]["recovery_count"] = 2
        with self.assertRaisesRegex(ValueError, "recovery_count"):
            self.write(state, 3)

        state["batches"][0]["recovery_count"] = 0
        with self.assertRaisesRegex(ValueError, "recovery_count"):
            self.write(state, 3)

    def test_missing_current_recovery_count_is_rejected(self):
        state = candidate(self.workspace)
        for batch in state["batches"]:
            batch.pop("recovery_count")

        with self.assertRaisesRegex(ValueError, "recovery_count"):
            batch_state.validate_state(state)


if __name__ == "__main__":
    unittest.main()
