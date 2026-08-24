import json
import hashlib
import os
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from delivery_engine import legacy_pdlc_fingerprint
from delivery_progress import apply_event
from delivery_progress import plan_projection_fingerprint
from delivery_next import upgrade_state
from delivery_state import validate_transition
from runtime_adapter import cleanup_receipt, negotiate


LEASE_SCRIPT = Path(__file__).with_name("delivery_lease.py")
STATE_SCRIPT = Path(__file__).with_name("delivery_state.py")


def state(revision=0, writer_id="writer-1"):
    return {
        "schema_version": 5,
        "run_id": "run-1",
        "repo_id": "/repo/common.git",
        "task_key": "task-payment",
        "writer_id": writer_id,
        "revision": revision,
        "workspace": "/repo/worktree-a",
        "baseline": {"commit": "abc123", "diff_fingerprint": "base-diff"},
        "scope_fingerprint": "scope-123",
        "source_fingerprint": "a" * 64,
        "execution_control": {
            "routing": {
                "schema_version": 1, "status": "frozen", "assessment_count": 1,
                "route": "inline", "review_tier": "low", "profile_fingerprint": "b" * 64,
            },
            "review": {
                "protocol_version": 2, "source_fingerprint": "a" * 64,
                "repair_budget_remaining": 1, "re_review_budget_remaining": 1,
                "integration_budget_remaining": 0, "requests": [],
            },
        },
        "engine": {
            "name": "native-v1",
            "selection": "auto",
            "reason": "PDLC is unavailable",
        },
        "current_stage": "round-1-semantic-review",
        "requires_stability_round": False,
        "status": "active",
        "ledger": {
            "completed_rounds": 0,
            "repair_fingerprints": [],
            "checks": [],
            "acceptance": [
                {
                    "criterion": "Requested behavior",
                    "evidence": "targeted test",
                    "result": "pass",
                    "freshness": "fresh",
                    "source_fingerprint": "a" * 64,
                }
            ],
        },
        "handoff": {
            "goal": "Fix requested behavior",
            "last_verification": "targeted test passed",
            "open_issues": "none",
            "next_action": "Run final verification",
        },
    }


class DeliveryStateTest(unittest.TestCase):
    def runtime_binding(self):
        return negotiate(
            "codex", {"dispatch": True, "query": True, "wait": True, "interrupt": True,
                      "tree_query": True, "restrict_dispatch": False}
        )

    def test_shared_state_path_is_deterministic(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            command = [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ]
            first = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )
            second = subprocess.run(
                command, text=True, capture_output=True, check=False, env=self.environment(state_home)
            )

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            self.assertIn("/.convergent-delivery/state/", first.stdout)
            self.assertTrue(first.stdout.endswith(".json\n"))

    def test_review_round_history_is_append_only_across_source_changes(self):
        previous = upgrade_state(state())
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 1
        candidate["source_fingerprint"] = "c" * 64
        candidate["execution_control"]["review"]["rounds"].append({
            "source_fingerprint": "c" * 64,
            "requests": [],
        })

        validate_transition(previous, candidate)

        rewritten = copy.deepcopy(candidate)
        rewritten["revision"] = 2
        rewritten["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "quality", "phase": "initial", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-a", "mode": "shared",
            "independent": False, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "review rounds"):
            validate_transition(candidate, rewritten)

    def test_native_plan_acknowledgement_must_be_a_separate_transition(self):
        previous = upgrade_state(state())
        previous["host_sync"] = {
            "mode": "native", "acknowledged_fingerprint": None,
            "evidence_level": "controller_attested",
        }
        acknowledgement = copy.deepcopy(previous)
        acknowledgement["revision"] = 1
        acknowledgement["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(acknowledgement)
        acknowledgement["host_sync"]["evidence_level"] = "host_observed"
        validate_transition(previous, acknowledgement)

        unobserved = copy.deepcopy(previous)
        unobserved["revision"] = 1
        unobserved["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(unobserved)
        with self.assertRaisesRegex(ValueError, "host-observed"):
            validate_transition(previous, unobserved)

        combined = copy.deepcopy(previous)
        combined["revision"] = 1
        combined["current_stage"] = "verify-final"
        combined["host_sync"]["acknowledged_fingerprint"] = \
            plan_projection_fingerprint(combined)
        combined["host_sync"]["evidence_level"] = "host_observed"
        with self.assertRaisesRegex(ValueError, "acknowledgement-only"):
            validate_transition(previous, combined)

    def test_terminal_report_history_can_only_advance_by_itself(self):
        previous = upgrade_state(state())
        previous.update(status="complete", current_stage="verify-final")
        candidate = copy.deepcopy(previous)
        candidate["revision"] = 1
        candidate["ledger"]["report_history"] = {
            "last_outcome": "ready", "reported_fingerprints": [],
            "summary_fingerprint": "c" * 64,
        }
        validate_transition(previous, candidate)

        mixed = copy.deepcopy(candidate)
        mixed["revision"] = 2
        mixed["handoff"]["goal"] = "changed"
        mixed["ledger"]["report_history"]["summary_fingerprint"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "report-only"):
            validate_transition(candidate, mixed)

    def test_state_path_hashes_run_id(self):
        with tempfile.TemporaryDirectory() as directory:
            state_home = Path(directory) / "home"
            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "path",
                    "--repo",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--run-id",
                    "../other-run",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("/.convergent-delivery/state/", result.stdout)
            self.assertNotIn("..", result.stdout)

    def test_list_and_doctor_discover_recoverable_states_by_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            environment = self.environment(state_home)

            listed = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "list", "--workspace", "/repo/worktree-a"],
                text=True, capture_output=True, check=False, env=environment,
            )
            diagnosed = subprocess.run(
                [sys.executable, str(STATE_SCRIPT), "doctor", "--workspace", "/repo/worktree-a"],
                text=True, capture_output=True, check=False, env=environment,
            )

            self.assertEqual(0, listed.returncode, listed.stderr)
            self.assertEqual("run-1", json.loads(listed.stdout)["states"][0]["run_id"])
            self.assertEqual(0, diagnosed.returncode, diagnosed.stderr)
            self.assertEqual("valid", json.loads(diagnosed.stdout)["states"][0]["health"])

    def environment(self, state_home):
        return {**os.environ, "HOME": str(state_home)}

    def acquire(self, root, workspace="/repo/worktree-a"):
        result = subprocess.run(
            [
                sys.executable,
                str(LEASE_SCRIPT),
                "acquire",
                "--root",
                str(root),
                "--repo",
                "/repo/common.git",
                "--workspace",
                workspace,
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
                "--writer-id",
                "writer-1",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def state_path(self, state_home):
        result = subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "path",
                "--repo",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--run-id",
                "run-1",
            ],
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return Path(result.stdout.strip())

    def write(self, root, state_home, payload, expected_revision, writer_id="writer-1"):
        return subprocess.run(
            [
                sys.executable,
                str(STATE_SCRIPT),
                "write",
                "--input",
                "-",
                "--lease-root",
                str(root),
                "--run-id",
                "run-1",
                "--writer-id",
                writer_id,
                "--repo-id",
                "/repo/common.git",
                "--task-key",
                "task-payment",
                "--expected-revision",
                str(expected_revision),
            ],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
            env=self.environment(state_home),
        )

    def test_write_requires_current_lease_and_monotonic_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)

            first = self.write(root, state_home, state(), -1)
            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual("written", json.loads(first.stdout)["status"])

            second = self.write(root, state_home, state(revision=1), 0)
            self.assertEqual(0, second.returncode, second.stderr)
            self.assertEqual(1, json.loads(state_path.read_text(encoding="utf-8"))["revision"])

    def test_v5_write_migrates_to_provider_binding_and_empty_worker_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps(state()), encoding="utf-8")

            result = self.write(root, state_home, state(revision=1), 0)

            self.assertEqual(0, result.returncode, result.stderr)
            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(10, written["schema_version"])
            self.assertEqual([], written["workers"])
            self.assertIsNone(written["worker_tree_receipt"])
            self.assertEqual(
                {"package_version", "protocol_version", "protocol_fingerprint"},
                set(written["controller"]),
            )
            self.assertEqual("native-v1", written["provider_binding"]["binding"]["workflow_provider"]["id"])
            self.assertNotIn("engine", written)

    def test_应该_当旧_schema_直接声明完成时_拒绝绕过_v10_完成证据(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = state(revision=1)
            candidate.update(status="complete", current_stage="verify-final")

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertRegex(result.stderr, "source_receipt|canonical routing")

    def test_state_write_renews_the_owned_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["renewed_at"] = "2000-01-01T00:00:00Z"
                record_path.write_text(json.dumps(record), encoding="utf-8")

            result = self.write(root, state_home, state(), -1)

            self.assertEqual(0, result.returncode, result.stderr)
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                self.assertNotEqual("2000-01-01T00:00:00Z", record["renewed_at"])

    def test_failed_state_write_does_not_renew_the_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            before = {}
            for record_path in root.rglob("*.json"):
                record = json.loads(record_path.read_text(encoding="utf-8"))
                record["renewed_at"] = "2000-01-01T00:00:00Z"
                record["lease_expires_at"] = "2099-01-01T00:00:00Z"
                record_path.write_text(json.dumps(record), encoding="utf-8")
                before[str(record_path)] = record_path.read_text(encoding="utf-8")
            invalid = state(revision=1)

            result = self.write(root, state_home, invalid, 0)

            self.assertNotEqual(0, result.returncode)
            for record_path in root.rglob("*.json"):
                self.assertEqual(before[str(record_path)], record_path.read_text(encoding="utf-8"))

    def test_v5_migration_rejects_stage_or_ledger_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            state_path.parent.mkdir(parents=True, exist_ok=True)
            original = state()
            original["current_stage"] = "scope"
            state_path.write_text(json.dumps(original), encoding="utf-8")
            candidate = state(revision=1)
            candidate["current_stage"] = "round-1-build"
            candidate["ledger"]["checks"].append(
                {"stage": "scope", "command": "test", "result": "pass"}
            )

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("migration", result.stderr.lower())
            self.assertEqual(original, json.loads(state_path.read_text(encoding="utf-8")))

    def test_complete_rejects_a_current_run_worker_without_host_terminal_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
            candidate.update(revision=1, status="complete", current_stage="verify-final")
            candidate["workers"] = [
                {
                    "ref": "worker-1",
                    "role": "pdlc",
                    "owner_run_id": "run-1",
                    "status": "working",
                    "progress": None,
                }
            ]

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("worker", result.stderr.lower())

    def test_blocked_state_allows_only_host_cleanup_to_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = upgrade_state(state())
            initial.update(
                status="blocked", blocked_code="environment",
                blocked_reason="worker cleanup required", runtime_binding=self.runtime_binding(),
                workers=[{
                    "ref": "worker-1", "parent_ref": None, "task_id": "task-payment",
                    "depth": 1, "may_dispatch": False, "role": "reviewer",
                    "owner_run_id": "run-1", "status": "working", "progress": None,
                }],
            )
            initial["worker_tree_receipt"] = cleanup_receipt(
                initial["runtime_binding"], 0, ["worker-1"], ["worker-1"], [],
                "2026-08-21T00:00:00Z",
            )
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

            cleaned = json.loads(json.dumps(initial))
            cleaned["revision"] = 1
            cleaned["workers"][0]["status"] = "interrupted"
            cleaned["worker_tree_receipt"] = cleanup_receipt(
                cleaned["runtime_binding"], 1, ["worker-1"], [], [],
                "2026-08-21T00:01:00Z",
            )
            result = self.write(root, state_home, cleaned, 0)

            self.assertEqual(0, result.returncode, result.stderr)

            rewritten = json.loads(json.dumps(cleaned))
            rewritten["revision"] = 2
            rewritten["handoff"]["goal"] = "silently changed"
            rewritten["worker_tree_receipt"] = cleanup_receipt(
                rewritten["runtime_binding"], 2, ["worker-1"], [], [],
                "2026-08-21T00:02:00Z",
            )
            rejected = self.write(root, state_home, rewritten, 1)
            self.assertNotEqual(0, rejected.returncode)
            self.assertIn("blocked cleanup", rejected.stderr)

    def test_controller_drift_is_rejected_after_it_is_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            candidate = json.loads(state_path.read_text(encoding="utf-8"))
            candidate["revision"] = 1
            candidate["controller"]["protocol_fingerprint"] = "0" * 64

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)
            self.assertIn("controller", result.stderr.lower())

    def test_package_version_change_does_not_break_a_compatible_controller_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            stored = json.loads(state_path.read_text(encoding="utf-8"))
            stored["controller"]["package_version"] = "older-package"
            state_path.write_text(json.dumps(stored), encoding="utf-8")
            candidate = json.loads(json.dumps(stored))
            candidate["revision"] = 1

            result = self.write(root, state_home, candidate, 0)

            self.assertEqual(0, result.returncode, result.stderr)

    def test_worker_progress_is_latest_only_and_objective_progress_is_monotonic(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            registered = json.loads(state_path.read_text(encoding="utf-8"))
            registered["revision"] = 1
            registered["runtime_binding"] = self.runtime_binding()
            registered["workers"] = [{
                "ref": "worker-1", "parent_ref": None, "task_id": "task-payment",
                "depth": 1, "may_dispatch": False,
                "role": "implementation",
                "owner_run_id": "run-1",
                "status": "working",
                "progress": None,
            }]
            self.assertEqual(0, self.write(root, state_home, registered, 0).returncode)

            first_heartbeat = apply_event(
                registered, "worker-1", "heartbeat", "testing", "Test still running",
                "process active", "worker responded", "wait for first result",
                now="2026-08-20T09:59:00Z",
            )
            self.assertEqual(
                0,
                self.write(root, state_home, first_heartbeat, 1).returncode,
            )
            registered = first_heartbeat

            milestone = apply_event(
                registered, "worker-1", "milestone", "implementing", "Schema green",
                "target tests pass", "26 passed", "run state tests",
                now="2026-08-20T10:00:00Z",
            )
            self.assertEqual(0, self.write(root, state_home, milestone, 2).returncode)
            heartbeat = apply_event(
                milestone, "worker-1", "heartbeat", "verifying", "Schema green",
                "full suite running", "process active", "wait for result",
                now="2026-08-20T10:01:00Z",
            )

            result = self.write(root, state_home, heartbeat, 3)

            self.assertEqual(0, result.returncode, result.stderr)
            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(3, written["workers"][0]["progress"]["sequence"])
            self.assertEqual(1, written["workers"][0]["progress"]["objective_revision"])

    def test_write_rejects_stale_revision_or_wrong_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)

            stale = self.write(root, state_home, state(revision=2), 0)
            self.assertNotEqual(0, stale.returncode)
            self.assertIn("revision", stale.stderr)

            wrong_writer = self.write(
                root,
                state_home,
                state(writer_id="writer-2"),
                -1,
                "writer-2",
            )
            self.assertNotEqual(0, wrong_writer.returncode)
            self.assertIn("lease", wrong_writer.stderr)

    def test_write_persists_the_frozen_pdlc_engine_without_native_stages(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            pdlc_root = Path(directory) / "pdlc"
            for name in ("pdlc-tdd", "pdlc-implement", "pdlc-review", "pdlc-feature"):
                skill = pdlc_root / "skills" / name / "SKILL.md"
                skill.parent.mkdir(parents=True, exist_ok=True)
                skill.write_text(f"{name}\n", encoding="utf-8")
            files = [
                "pdlc-feature/SKILL.md",
                "pdlc-tdd/SKILL.md",
                "pdlc-implement/SKILL.md",
                "pdlc-review/SKILL.md",
            ]
            digest = hashlib.sha256()
            for relative in files:
                digest.update(
                    relative.encode("utf-8")
                    + b"\0"
                    + (pdlc_root / "skills" / relative).read_bytes()
                )
            (pdlc_root / "converge-provider.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "provider": {
                            "id": "pdlc-v1",
                            "source_id": "pdlc-skills",
                            "version": "test-v1",
                            "role": "workflow",
                        },
                        "capabilities": {
                            "task_kinds": ["feature"],
                            "stages": ["plan", "tdd", "implement", "review"],
                        },
                        "task_contracts": {
                            "feature": {
                                "entrypoint": files[0],
                                "closure": files[1:],
                                "source_fingerprint": digest.hexdigest(),
                                "preserve_external_behavior": False,
                            }
                        },
                        "authorization": {
                            "stop_for": [
                                "business_rules",
                                "public_contracts",
                                "permissions",
                                "release",
                                "irreversible_actions",
                            ],
                            "forbidden_actions": [
                                "pdlc-ship",
                                "commit",
                                "tag",
                                "push",
                                "publish",
                                "install",
                            ],
                        },
                        "outputs": {
                            "progress_protocol": 1,
                            "required_evidence": ["tests", "validation", "findings"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            payload = state()
            payload["engine"] = {
                "name": "pdlc-v1",
                "selection": "explicit",
                "reason": "PDLC v1 capability is available",
                "pdlc_root": str(pdlc_root.resolve()),
                "feature_id": "F-123",
                "task_kind": "feature",
                "pdlc_fingerprint": legacy_pdlc_fingerprint(pdlc_root, "feature"),
                "provider_manifest": str(pdlc_root / "converge-provider.json"),
            }
            payload["current_stage"] = "pdlc-run"

            result = self.write(root, state_home, payload, -1)

            self.assertEqual(0, result.returncode, result.stderr)
            written = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(
                "pdlc-v1",
                written["provider_binding"]["binding"]["workflow_provider"]["id"],
            )
            self.assertEqual("pdlc-run", written["current_stage"])

    def test_write_rejects_external_candidate_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            candidate = Path(directory) / "candidate.json"
            candidate.write_text(json.dumps(state()), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    str(candidate),
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--repo-id",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--expected-revision",
                    "-1",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("stdin", result.stderr)
            self.assertFalse(self.state_path(state_home).exists())

    def test_incomplete_stdin_preserves_the_previous_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            before = state_path.read_text(encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(STATE_SCRIPT),
                    "write",
                    "--input",
                    "-",
                    "--lease-root",
                    str(root),
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                    "--repo-id",
                    "/repo/common.git",
                    "--task-key",
                    "task-payment",
                    "--expected-revision",
                    "0",
                ],
                input='{"schema_version":',
                text=True,
                capture_output=True,
                check=False,
                env=self.environment(state_home),
            )

            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_path.read_text(encoding="utf-8"))

    def test_write_without_lease_creates_no_state_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            state_path = self.state_path(state_home)

            result = self.write(root, state_home, state(), -1)

            self.assertNotEqual(0, result.returncode)
            self.assertFalse(state_path.parent.exists())

    def test_应该_当状态被回写时_拒绝冻结契约和证据倒退(self):
        def cases():
            changed_repo = state(revision=1)
            changed_repo["repo_id"] = "/repo/other.git"
            changed_task = state(revision=1)
            changed_task["task_key"] = "task-other"
            changed_run = state(revision=1)
            changed_run["run_id"] = "run-2"
            changed_writer = state(revision=1, writer_id="writer-2")
            changed_baseline = state(revision=1)
            changed_baseline["baseline"]["commit"] = "rewritten"
            changed_scope = state(revision=1)
            changed_scope["scope_fingerprint"] = "rewritten"
            changed_engine = state(revision=1)
            changed_engine["engine"]["reason"] = "silently switched"
            regressed_stage = state(revision=1)
            regressed_stage["current_stage"] = "round-1-build"
            skipped_stage = state(revision=1)
            skipped_stage["current_stage"] = "round-2-risk-review"
            regressed_rounds = state(revision=1)
            regressed_rounds["ledger"]["completed_rounds"] = 0
            skipped_rounds = state(revision=1)
            skipped_rounds["ledger"]["completed_rounds"] = 2
            removed_repair = state(revision=1)
            removed_repair["ledger"]["repair_fingerprints"] = []
            removed_check = state(revision=1)
            removed_check["ledger"]["checks"] = []
            changed_acceptance = state(revision=1)
            changed_acceptance["ledger"]["acceptance"][0]["evidence"] = "invented evidence"
            return {
                "repo": (state(), changed_repo),
                "task": (state(), changed_task),
                "run": (state(), changed_run),
                "writer": (state(), changed_writer),
                "baseline": (state(), changed_baseline),
                "scope": (state(), changed_scope),
                "engine": (state(), changed_engine),
                "stage": (state(), regressed_stage),
                "stage_skip": (
                    {**state(), "current_stage": "round-1-build"},
                    skipped_stage,
                ),
                "completed_rounds": (
                    {**state(), "ledger": {**state()["ledger"], "completed_rounds": 1}},
                    regressed_rounds,
                ),
                "completed_rounds_skip": (state(), skipped_rounds),
                "repair_fingerprints": (
                    {
                        **state(),
                        "ledger": {
                            **state()["ledger"],
                            "repair_fingerprints": ["fixed-once"],
                        },
                    },
                    removed_repair,
                ),
                "checks": (
                    {
                        **state(),
                        "ledger": {
                            **state()["ledger"],
                            "checks": [
                                {"stage": "build", "command": "test-one", "result": "pass"}
                            ],
                        },
                    },
                    removed_check,
                ),
                "acceptance": (state(), changed_acceptance),
            }

        for name, (initial, candidate) in cases().items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "leases"
                state_home = Path(directory) / "home"
                self.acquire(root)
                self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

                result = self.write(root, state_home, candidate, 0)

                self.assertNotEqual(0, result.returncode, name)

    def test_应该_当状态合法前进时_保留追加证据并允许工作区迁移(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)

            candidate = state(revision=1)
            candidate["ledger"]["completed_rounds"] = 1
            candidate["ledger"]["repair_fingerprints"] = ["fixed-once"]
            candidate["execution_control"]["review"]["repair_budget_remaining"] = 0
            candidate["ledger"]["checks"] = [
                {"stage": "verify-final", "command": "test-one", "result": "pass"}
            ]
            completed = self.write(root, state_home, candidate, 0)
            self.assertEqual(0, completed.returncode, completed.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            moved = subprocess.run(
                [
                    sys.executable,
                    str(LEASE_SCRIPT),
                    "move",
                    "--root",
                    str(root),
                    "--repo",
                    "/repo/common.git",
                    "--from-workspace",
                    "/repo/worktree-a",
                    "--workspace",
                    "/repo/worktree-b",
                    "--task-key",
                    "task-payment",
                    "--run-id",
                    "run-1",
                    "--writer-id",
                    "writer-1",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, moved.returncode, moved.stderr)
            candidate = state(revision=1)
            candidate["workspace"] = "/repo/worktree-b"

            result = self.write(root, state_home, candidate, 0)

            self.assertEqual(0, result.returncode, result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            initial = state()
            self.assertEqual(0, self.write(root, state_home, initial, -1).returncode)
            candidate = state(revision=1)
            previous_acceptance = initial["ledger"]["acceptance"][0]
            candidate["ledger"]["acceptance_history"] = [
                {"revision": 0, "acceptance": previous_acceptance}
            ]
            candidate["ledger"]["acceptance"][0] = {
                "criterion": "Requested behavior",
                "evidence": "source changed after the passing verification",
                "result": "pass",
                "freshness": "stale",
            }

            stale = self.write(root, state_home, candidate, 0)
            self.assertEqual(0, stale.returncode, stale.stderr)

            failed_candidate = state(revision=2)
            failed_candidate["ledger"]["acceptance_history"] = [
                {"revision": 0, "acceptance": previous_acceptance},
                {"revision": 1, "acceptance": candidate["ledger"]["acceptance"][0]},
            ]
            failed_candidate["ledger"]["acceptance"][0] = {
                "criterion": "Requested behavior",
                "evidence": "latest verification exited non-zero",
                "result": "fail",
                "freshness": "fresh",
            }

            failed = self.write(root, state_home, failed_candidate, 1)

            self.assertEqual(0, failed.returncode, failed.stderr)

    def test_review_budgets_must_be_consumed_by_their_exact_actions(self):
        previous = upgrade_state(state())

        repair_without_budget = copy.deepcopy(previous)
        repair_without_budget["revision"] = 1
        repair_without_budget["ledger"]["repair_fingerprints"].append("repair-1")
        with self.assertRaisesRegex(ValueError, "repair_budget"):
            validate_transition(previous, repair_without_budget)

        review_without_budget = copy.deepcopy(previous)
        review_without_budget["revision"] = 1
        review_without_budget["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "quality", "phase": "re_review", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-1", "mode": "blind",
            "independent": True, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "re_review_budget"):
            validate_transition(previous, review_without_budget)

        integration_previous = copy.deepcopy(previous)
        integration_previous["execution_control"]["review"]["integration_budget_remaining"] = 1
        integration_without_budget = copy.deepcopy(integration_previous)
        integration_without_budget["revision"] = 1
        integration_without_budget["execution_control"]["review"]["rounds"][0]["requests"].append({
            "axis": "integration", "phase": "initial", "source_fingerprint": "a" * 64,
            "status": "pass", "reviewer_ref": "reviewer-1", "mode": "blind",
            "independent": True, "finding_fingerprints": [],
        })
        with self.assertRaisesRegex(ValueError, "integration_budget"):
            validate_transition(integration_previous, integration_without_budget)

    def test_应该_当终态候选删除字段时_对称比较并拒绝(self):
        terminal = upgrade_state(state())
        terminal.update(status="complete", current_stage="verify-final")
        candidate = copy.deepcopy(terminal)
        candidate["revision"] = 1
        candidate.pop("requires_stability_round")

        with self.assertRaisesRegex(ValueError, "terminal state"):
            validate_transition(terminal, candidate)

    def test_应该_当未执行租约迁移时_拒绝直接改写工作区(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "leases"
            state_home = Path(directory) / "home"
            self.acquire(root)
            self.assertEqual(0, self.write(root, state_home, state(), -1).returncode)
            self.acquire(root, "/repo/worktree-b")
            candidate = state(revision=1)
            candidate["workspace"] = "/repo/worktree-b"

            result = self.write(root, state_home, candidate, 0)

            self.assertNotEqual(0, result.returncode)


if __name__ == "__main__":
    unittest.main()
