import importlib.util
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if str(ROOT_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(ROOT_SCRIPTS))
from delivery_next import upgrade_state
from test_delivery_next import state as single_state


MODULE_PATH = Path(__file__).with_name("batch_state.py")
SPEC = importlib.util.spec_from_file_location("batch_state", MODULE_PATH)
batch_state = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch_state)


def provider_binding(workflow="native-v1"):
    binding = {
        "controller": "converge",
        "workflow_provider": workflow,
        "stage_providers": {},
    }
    return {
        **binding,
        "binding_fingerprint": hashlib.sha256(
            json.dumps(binding, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def capsule(batch_id, plan_id="plan-1", task_id=None):
    return {
        "planned_task": True,
        "plan_id": plan_id,
        "task_id": task_id or batch_id.replace("B", "T"),
        "batch_id": batch_id,
        "goal": f"goal-{batch_id}",
        "scope": [f"module-{batch_id}"],
        "global_constraints": ["keep compatibility"],
        "consumes": ["baseline"],
        "produces": [f"output-{batch_id}"],
        "baseline": "abc123",
        "acceptance": [f"accept-{batch_id}"],
        "verification": [f"test-{batch_id}"],
        "provider_binding": provider_binding(),
    }


def receipt(batch_id, dispatch_id, commit_id, tree_hash, workspace=None):
    value = {
        "protocol_version": 2,
        "batch_id": batch_id,
        "dispatch_id": dispatch_id,
        "commit_id": commit_id,
        "tree_hash": tree_hash,
        "verified_tree_hash": tree_hash,
        "acceptance": [
            {
                "criterion": f"accept-{batch_id}",
                "evidence": f"test-{batch_id}",
                "result": "pass",
                "freshness": "fresh",
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
        ))
        value.update(
            delegate_run_id=run_id,
            delegate_state=child,
            delegate_state_fingerprint=hashlib.sha256(
                json.dumps(child, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        )
    return value


def candidate(workspace, revision=0):
    return {
        "schema_version": 3,
        "run_id": "batch-run-1",
        "writer_id": "scheduler-1",
        "revision": revision,
        "repo_id": str(workspace / ".git"),
        "workspace": str(workspace),
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
                "capsule": capsule("B1"),
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
                "capsule": capsule("B2"),
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
            {"criterion": "whole-plan", "evidence": None, "result": "unknown", "freshness": "unavailable"}
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
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "state"
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"], check=True
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
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

        state["revision"] = 3
        state["batches"][0]["status"] = "validating-receipt"
        state["batches"][0]["receipt"] = receipt(
            "B1", "dispatch-B1", self.commit_id, self.tree_hash, self.workspace
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
        state["revision"] = 7
        state["batches"][1]["status"] = "validating-receipt"
        state["batches"][1]["receipt"] = receipt(
            "B2", "dispatch-B2", self.commit_id, self.tree_hash, self.workspace
        )
        self.write(state, 6)
        state["revision"] = 8
        state["batches"][1]["status"] = "completed"
        state["batches"][1]["worker_status"] = "completed"
        state["current_batch"] = None
        self.write(state, 7)
        state["revision"] = 9
        state["status"] = "complete"
        state["final_acceptance"] = [
            {"criterion": "whole-plan", "evidence": "e2e", "result": "pass", "freshness": "fresh"}
        ]
        self.write(state, 8)
        self.assertEqual(9, json.loads(path.read_text(encoding="utf-8"))["revision"])

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

    def test_应该_当v1或v2活动状态迁移时_按阶段补齐v3生命周期(self):
        for schema_version in (1, 2):
            with self.subTest(schema_version=schema_version):
                legacy = candidate(self.workspace)
                legacy["schema_version"] = schema_version
                legacy["batches"][0].update(
                    status="running", dispatch_id="dispatch-B1", worker_ref="thread-1"
                )
                for batch in legacy["batches"]:
                    for field in ("worker_role", "worker_owner_run_id", "worker_status", "delegate_run_id"):
                        batch.pop(field)
                    if schema_version == 1:
                        batch.pop("task_id")
                        batch.pop("recovery_count")
                        for field in ("planned_task", "plan_id", "task_id"):
                            batch["capsule"].pop(field)
                batch_state.validate_state(legacy)

                upgraded = candidate(self.workspace, revision=1)
                upgraded["batches"][0].update(status="running", dispatch_id="dispatch-B1")
                register_worker(upgraded, 0, "thread-1")

                batch_state.validate_state(upgraded)
                batch_state.validate_transition(legacy, upgraded)

    def test_应该_当v1或v2未启动状态迁移时_允许无worker引用(self):
        for schema_version in (1, 2):
            for status in ("pending", "dispatching"):
                with self.subTest(schema_version=schema_version, status=status):
                    legacy = candidate(self.workspace)
                    legacy["schema_version"] = schema_version
                    legacy["batches"][0]["status"] = status
                    if status == "dispatching":
                        legacy["batches"][0]["dispatch_id"] = "dispatch-B1"
                    for batch in legacy["batches"]:
                        for field in ("worker_role", "worker_owner_run_id", "worker_status", "delegate_run_id"):
                            batch.pop(field)
                        if schema_version == 1:
                            batch.pop("task_id")
                            batch.pop("recovery_count")
                            for field in ("planned_task", "plan_id", "task_id"):
                                batch["capsule"].pop(field)
                    batch_state.validate_state(legacy)

                    upgraded = candidate(self.workspace, revision=1)
                    upgraded["batches"][0]["status"] = status
                    if status == "dispatching":
                        upgraded["batches"][0]["dispatch_id"] = "dispatch-B1"

                    batch_state.validate_state(upgraded)
                    batch_state.validate_transition(legacy, upgraded)

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
        with self.assertRaisesRegex(ValueError, "active plan"):
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
        with self.assertRaisesRegex(ValueError, "Git commit"):
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

    def test_应该_当恢复真实旧v1状态时_迁移到新Schema并继续(self):
        legacy = candidate(self.workspace)
        legacy["schema_version"] = 1
        for batch in legacy["batches"]:
            batch.pop("task_id")
            batch.pop("recovery_count")
            batch.pop("worker_role")
            batch.pop("worker_owner_run_id")
            batch.pop("worker_status")
            batch.pop("delegate_run_id")
            for field in ("planned_task", "plan_id", "task_id"):
                batch["capsule"].pop(field)
        batch_state.validate_state(legacy)
        with self.assertRaisesRegex(ValueError, "schema_version 3"):
            batch_state.write_state(self.root / "new-state", legacy, -1)
        path = batch_state.state_path(
            self.root, legacy["repo_id"], legacy["plan"]["plan_id"], legacy["run_id"]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        upgraded = candidate(self.workspace, revision=1)
        upgraded["schema_version"] = 3

        written = self.write(upgraded, 0)

        self.assertEqual(3, json.loads(written.read_text(encoding="utf-8"))["schema_version"])

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

    def test_应该_当旧状态没有恢复计数时_按零次恢复兼容读取(self):
        state = candidate(self.workspace)
        for batch in state["batches"]:
            batch.pop("recovery_count")

        path = self.write(state, -1)

        self.assertTrue(path.exists())

    def test_应该_当恢复v2状态时_只添加worker生命周期并迁移到v3(self):
        legacy = candidate(self.workspace)
        legacy["schema_version"] = 2
        for batch in legacy["batches"]:
            batch.pop("worker_role")
            batch.pop("worker_owner_run_id")
            batch.pop("worker_status")
            batch.pop("delegate_run_id")
        batch_state.validate_state(legacy)
        path = batch_state.state_path(
            self.root, legacy["repo_id"], legacy["plan"]["plan_id"], legacy["run_id"]
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(legacy), encoding="utf-8")
        upgraded = candidate(self.workspace, revision=1)

        written = self.write(upgraded, 0)

        self.assertEqual(3, json.loads(written.read_text(encoding="utf-8"))["schema_version"])


if __name__ == "__main__":
    unittest.main()
