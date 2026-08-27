import json
import hashlib
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("plan_check.py")
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import evidence_contract
from delivery_engine import provider_reference
from provider_contract import canonical_fingerprint
SHA = "a" * 64
PROJECT_HEAD = subprocess.run(
    ["git", "-C", str(ROOT), "rev-parse", "HEAD"], check=True,
    capture_output=True, text=True,
).stdout.strip()
PROJECT_SOURCE = evidence_contract.workspace_source(ROOT, PROJECT_HEAD)


def summary_provider_binding(workflow="native-v1", tdd=None):
    stages = {"tdd": tdd} if tdd else {}
    payload = {
        "controller": "converge",
        "workflow_provider": workflow,
        "stage_providers": stages,
    }
    return {
        **payload,
        "binding_fingerprint": hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def provider_binding():
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference("native-v1", "feature"),
        "stage_providers": {},
    }
    return {
        "selection": "auto",
        "reason": "native workflow is frozen",
        "task_kind": "feature",
        "binding": binding,
        "binding_fingerprint": canonical_fingerprint(binding),
    }


def pdlc_provider_binding(root):
    files = [
        "pdlc-feature/SKILL.md",
        "pdlc-tdd/SKILL.md",
        "pdlc-implement/SKILL.md",
        "pdlc-review/SKILL.md",
    ]
    digest = hashlib.sha256()
    for relative in files:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{relative}\n", encoding="utf-8")
        digest.update(relative.encode("utf-8") + b"\0" + path.read_bytes())
    manifest = {
        "schema_version": 2,
        "provider": {
            "id": "pdlc-v1", "source_id": "test/pdlc", "version": "test", "role": "workflow",
        },
        "capabilities": {"task_kinds": ["feature"], "stages": ["plan", "tdd", "implement", "review"]},
        "task_contracts": {
            "feature": {
                "entrypoint": files[0], "closure": files[1:],
                "source_fingerprint": digest.hexdigest(), "preserve_external_behavior": False,
            }
        },
        "authorization": {
            "stop_for": ["business_rules", "public_contracts", "permissions", "release", "irreversible_actions"],
            "forbidden_actions": ["pdlc-ship", "commit", "tag", "push", "publish", "install"],
        },
        "outputs": {"progress_protocol": 1, "required_evidence": ["tests"]},
    }
    manifest_path = root / "converge-provider.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    binding = {
        "controller": "converge",
        "workflow_provider": provider_reference(
            "pdlc-v1", "feature", manifest=str(manifest_path), root=str(root)
        ),
        "stage_providers": {},
    }
    return {
        "selection": "explicit",
        "reason": "test PDLC workflow is frozen",
        "task_kind": "feature",
        "binding": binding,
        "binding_fingerprint": canonical_fingerprint(binding),
    }


def task(task_id, paths, depends_on=None, execution="auto", provider=None):
    return {
        "task_id": task_id,
        "task_kind": "vertical_slice",
        "outcomes": [f"deliver {task_id}"],
        "goal": f"deliver {task_id}",
        "owned_paths": paths,
        "depends_on": depends_on or [],
        "steps": [f"implement {task_id}", f"verify {task_id}"],
        "acceptance": [f"{task_id} works"],
        "verification": [f"check-{task_id}"],
        "execution": execution,
        "status": "pending",
        "provider_binding": provider or provider_binding(),
        "provider_run": {"scope": "task", "recursive_planning": False},
    }


def plan(tasks, context="short", planner=None, checkpoint="same_session"):
    return {
        "schema_version": 6,
        "plan_id": "plan-example",
        "requirement_fingerprint": SHA,
        "planner": planner or {
            "name": "native-plan-v1",
            "source_path": None,
            "source_fingerprint": None,
        },
        "context": context,
        "baseline": {"commit": PROJECT_HEAD, "source": PROJECT_SOURCE},
        "tasks": tasks,
        "final_acceptance": ["all checks pass"],
        "closure_matrix": {
            "schema_version": 2,
            "chains": [{
                "id": "main",
                "description": "the planned control chain",
                "entrypoints": sorted({path for item in tasks for path in item["owned_paths"]}),
                "callers": ["external"],
                "coverage": {
                    dimension: {"status": "covered", "acceptance": ["all checks pass"]}
                    for dimension in ("input", "freeze", "effect", "receipt", "recovery")
                },
            }],
        },
        "decisions": [],
        "checkpoint": checkpoint,
    }


def granular_plan(tasks, context="long", checkpoint="same_session"):
    return plan(tasks, context=context, checkpoint=checkpoint)


def evidence_receipt(source, command="bash scripts/check.sh"):
    argv = [sys.executable, "-c", "pass", command]
    receipt = {
        "schema_version": 2,
        "argv": argv,
        "command": shlex.join(argv),
        "exit_code": 0,
        "stdout_fingerprint": hashlib.sha256(b"").hexdigest(),
        "stderr_fingerprint": hashlib.sha256(b"").hexdigest(),
        "runner_fingerprint": evidence_contract._runner_fingerprint(),
        "evidence_level": "observed",
        "source": source,
    }
    return {**receipt, "receipt_fingerprint": evidence_contract._fingerprint(receipt)}


def final_evidence(source):
    return [
        {
            "criterion": "all checks pass",
            "result": "pass",
            "freshness": "fresh",
            "evidence": evidence_receipt(source),
        }
    ]


class PlanCheckTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.pdlc_root = Path(self.temporary.name) / "pdlc"
        self.workspace = Path(self.temporary.name) / "workspace"
        self.workspace.mkdir()
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "config", "user.name", "Test"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
        subprocess.run(["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"], check=True)

    def tearDown(self):
        self.temporary.cleanup()

    def run_check(self, command, payload, workspace=None, require_complete=False):
        arguments = ["python3", str(SCRIPT), command, "--input", "-"]
        if workspace is not None:
            arguments.extend(["--workspace", str(workspace)])
        if require_complete:
            arguments.append("--require-complete")
        return subprocess.run(
            arguments,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def current_source(self, value):
        value["baseline"]["commit"] = self.baseline
        value["baseline"]["source"] = evidence_contract.workspace_source(
            self.workspace, self.baseline
        )
        result = self.run_check(
            "audit",
            {"plan": value, "task_results": {}, "final_acceptance": []},
            self.workspace,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["source"]

    @property
    def baseline(self):
        return subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def write_changes(self, *paths):
        for path in paths:
            target = self.workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"changed {path}\n", encoding="utf-8")

    def test_python_runtime_caches_do_not_change_source_identity(self):
        cache = self.workspace / "scripts" / "__pycache__" / "helper.cpython-314.pyc"
        cache.parent.mkdir(parents=True)
        cache.write_bytes(b"generated runtime cache")

        source = self.current_source(plan([task("T1", ["src"])]))

        self.assertEqual([], source["changed_paths"])

    def test_closure_matrix_is_required_and_uncovered_blocks_complete_audit(self):
        value = plan([task("T1", ["src"])])
        missing = json.loads(json.dumps(value))
        missing.pop("closure_matrix")
        self.assertNotEqual(0, self.run_check("validate", missing).returncode)

        value["closure_matrix"]["chains"][0]["coverage"]["recovery"] = {
            "status": "uncovered", "reason": "recovery path has no executable evidence",
        }
        self.assertEqual(0, self.run_check("validate", value).returncode)
        source = self.current_source(value)
        value["baseline"] = {"commit": self.baseline, "source": source}
        result = self.run_check("audit", {
            "plan": value,
            "task_results": {"T1": {
                "status": "DONE", "fresh_pass": True,
                "source_before": source, "source_after": source,
                "evidence": [evidence_receipt(source)],
            }},
            "final_acceptance": final_evidence(source),
        }, self.workspace, require_complete=True)

        self.assertEqual(1, result.returncode, result.stderr)
        self.assertFalse(json.loads(result.stdout)["closure_complete"])

    def test_closure_matrix_must_cover_every_owned_path_with_entrypoints_and_callers(self):
        value = plan([task("T1", ["src/service", "tests/service"])])
        value["closure_matrix"]["chains"][0]["entrypoints"] = ["src/service"]
        value["closure_matrix"]["chains"][0]["callers"] = []
        result = self.run_check("validate", value)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("callers", result.stderr)

        value["closure_matrix"]["chains"][0]["callers"] = ["tests/service"]
        result = self.run_check("validate", value)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("owned_paths", result.stderr)

    def test_independent_tasks_share_a_wave_and_dependencies_form_the_next_wave(self):
        value = granular_plan(
            [
                task("T1", ["src/a"]),
                task("T2", ["src/b"]),
                task("T3", ["src/c"], ["T1", "T2"]),
            ]
        )

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual([["T1", "T2"], ["T3"]], output["waves"])
        self.assertEqual("sequential", output["execution_mode"])

    def test_only_resolved_structured_decisions_can_enter_execution(self):
        resolved = granular_plan([task("T1", ["src"])])
        baseline_source = self.current_source(resolved)
        resolved["schema_version"] = 6
        resolved["baseline"] = {"commit": self.baseline, "source": baseline_source}
        resolved["decisions"] = [{
            "id": "D1",
            "status": "resolved",
            "question": "Which local cache name should be used?",
            "resolution": "Reuse the existing cache name.",
            "source": "code",
        }]
        self.assertEqual(0, self.run_check("validate", resolved).returncode)

        for decision in (
            {"status": "open", "question": "Which public API is correct?"},
            "assume the public API",
        ):
            with self.subTest(decision=decision):
                value = json.loads(json.dumps(resolved))
                value["decisions"] = [decision]
                result = self.run_check("validate", value)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("decision", result.stderr)

        for resolution in ("TBD", "unknown", "待定", "待确认"):
            with self.subTest(resolution=resolution):
                value = json.loads(json.dumps(resolved))
                value["decisions"][0]["resolution"] = resolution
                result = self.run_check("validate", value)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("resolution", result.stderr)

    def test_overlapping_paths_are_serialized_even_without_dependencies(self):
        value = plan([task("T1", ["src/shared"]), task("T2", ["src/shared/file.py"])])

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["T1"], ["T2"]], json.loads(result.stdout)["waves"])

    def test_multiple_bounded_pdlc_runs_are_allowed_in_one_plan(self):
        value = granular_plan(
            [
                task("schema", ["providers"], provider=pdlc_provider_binding(self.pdlc_root)),
                task(
                    "runtime",
                    ["scripts"],
                    ["schema"],
                    provider=pdlc_provider_binding(self.pdlc_root),
                ),
            ]
        )

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["schema"], ["runtime"]], json.loads(result.stdout)["waves"])
        self.assertEqual("sequential", json.loads(result.stdout)["execution_mode"])

    def test_rejects_a_forged_provider_binding_fingerprint(self):
        value = plan([task("T1", ["src"])])
        value["tasks"][0]["provider_binding"]["binding_fingerprint"] = "b" * 64

        self.assertNotEqual(0, self.run_check("validate", value).returncode)

    def test_rejects_recursive_or_unbounded_provider_runs(self):
        for provider_run in (
            {"scope": "plan", "recursive_planning": False},
            {"scope": "task", "recursive_planning": True},
        ):
            with self.subTest(provider_run=provider_run):
                value = plan([task("T1", ["src"], provider=pdlc_provider_binding(self.pdlc_root))])
                value["tasks"][0]["provider_run"] = provider_run

                self.assertNotEqual(0, self.run_check("validate", value).returncode)

    def test_legacy_plan_schemas_are_rejected(self):
        for schema_version in (1, 2, 3, 4):
            with self.subTest(schema_version=schema_version):
                value = plan([task("T1", ["src"])])
                value["schema_version"] = schema_version
                result = self.run_check("validate", value)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("schema_version must be 6", result.stderr)

    def test_unknown_plan_schema_fields_are_rejected(self):
        cases = (
            ("plan", lambda value: value.__setitem__("legacy_marker", True)),
            ("planner", lambda value: value["planner"].__setitem__("legacy_marker", True)),
            ("task", lambda value: value["tasks"][0].__setitem__("legacy_marker", True)),
        )
        for location, mutate in cases:
            with self.subTest(location=location):
                value = plan([task("T1", ["src"])])
                mutate(value)
                result = self.run_check("validate", value)
                self.assertNotEqual(0, result.returncode)
                self.assertIn("fields are invalid", result.stderr)

    def test_plan_rejects_summary_provider_binding_without_frozen_sources(self):
        result = self.run_check(
            "validate", plan([task("T1", ["src"], provider=summary_provider_binding())])
        )

        self.assertNotEqual(0, result.returncode)
        self.assertIn("provider_binding fields are invalid", result.stderr)

    def test_rejects_cycles_unknown_dependencies_and_duplicate_ids(self):
        cases = [
            plan([task("T1", ["a"], ["T2"]), task("T2", ["b"], ["T1"])]),
            plan([task("T1", ["a"], ["missing"])]),
            plan([task("T1", ["a"]), task("T1", ["b"])]),
        ]

        for value in cases:
            with self.subTest(value=value):
                self.assertNotEqual(0, self.run_check("validate", value).returncode)

    def test_rejects_unknown_providers_and_unfrozen_third_party_planners(self):
        unknown_provider = plan([task("T1", ["a"])])
        binding = unknown_provider["tasks"][0]["provider_binding"]["binding"]
        binding["workflow_provider"]["id"] = "invented-v1"
        unknown_provider["tasks"][0]["provider_binding"]["binding_fingerprint"] = (
            canonical_fingerprint(binding)
        )
        unfrozen_planner = plan(
            [task("T1", ["a"])],
            planner={
                "name": "generic-plan-v1",
                "source_path": None,
                "source_fingerprint": None,
            },
        )

        self.assertNotEqual(0, self.run_check("validate", unknown_provider).returncode)
        self.assertNotEqual(0, self.run_check("validate", unfrozen_planner).returncode)

    def test_long_single_task_uses_a_fresh_context(self):
        result = self.run_check(
            "validate", granular_plan([task("T1", ["src"])], context="long")
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("fresh", json.loads(result.stdout)["execution_mode"])

    def test_task_kinds_are_explicit_and_integration_requires_a_dependency(self):
        for kind in ("vertical_slice", "wide_refactor"):
            with self.subTest(kind=kind):
                value = granular_plan([task("T1", ["src"])])
                value["tasks"][0]["task_kind"] = kind
                result = self.run_check("validate", value)
                self.assertEqual(0, result.returncode, result.stderr)

        integration = granular_plan(
            [task("slice", ["src/a"]), task("integrate", ["src/b"], ["slice"])]
        )
        integration["tasks"][1]["task_kind"] = "integration"
        result = self.run_check("validate", integration)
        self.assertEqual(0, result.returncode, result.stderr)

        missing_dependency = granular_plan([task("integrate", ["src"])])
        missing_dependency["tasks"][0]["task_kind"] = "integration"
        result = self.run_check("validate", missing_dependency)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("integration", result.stderr)

    def test_long_task_with_multiple_outcomes_is_blocked_with_an_actionable_reason(self):
        value = granular_plan([task("wide", ["src"])])
        value["tasks"][0]["outcomes"] = ["deliver API", "deliver UI"]

        result = self.run_check("validate", value)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("wide", result.stderr)
        self.assertIn("split", result.stderr)
        self.assertIn("vertical_slice", result.stderr)

        self.assertIn("split", result.stderr)

    def test_same_session_tasks_are_sequential_without_commit_authorization(self):
        value = granular_plan(
            [task("slice", ["src/a"]), task("integrate", ["src/b"], ["slice"])]
        )
        value["tasks"][1]["task_kind"] = "integration"

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("sequential", output["execution_mode"])
        self.assertFalse(output["commit_authorization_required"])

    def test_only_cross_session_checkpoint_requires_commit_authorization(self):
        value = granular_plan(
            [task("slice", ["src/a"]), task("integrate", ["src/b"], ["slice"])],
            checkpoint="cross_session",
        )
        value["tasks"][1]["task_kind"] = "integration"

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("batch", output["execution_mode"])
        self.assertTrue(output["commit_authorization_required"])

    def test_audit_reports_partial_missing_changed_and_scope_drift(self):
        value = plan(
            [task("T1", ["src/a"]), task("T2", ["src/b"]), task("T3", ["src/c"])]
        )
        value["baseline"] = {
            "commit": self.baseline,
            "source": evidence_contract.workspace_source(self.workspace, self.baseline),
        }
        self.write_changes("src/a/file.py", "src/b/file.py", "extra.txt")
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        envelope = {
            "plan": value,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "source_before": value["baseline"]["source"],
                    "source_after": source,
                    "evidence": [evidence_receipt(source, "check-T1")],
                },
                "T2": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "evidence": [
                        evidence_receipt({**source, "diff_fingerprint": "0" * 64}, "check-T2")
                    ],
                },
                "T3": {"status": "CHANGED", "fresh_pass": True},
            },
            "final_acceptance": final_evidence(source),
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(
            {"T1": "PARTIAL", "T2": "PARTIAL", "T3": "CHANGED"}, output["tasks"]
        )
        self.assertEqual(["extra.txt"], output["scope_drift"])
        self.assertEqual(["extra.txt"], output["closure_scope_drift"])
        self.assertFalse(output["closure_complete"])
        self.assertFalse(output["complete"])

        gated = self.run_check(
            "audit", envelope, self.workspace, require_complete=True
        )
        self.assertEqual(1, gated.returncode, gated.stderr)
        self.assertFalse(json.loads(gated.stdout)["complete"])

    def test_done_without_bound_evidence_is_downgraded_to_partial(self):
        value = plan([task("T1", ["src/a"])])
        self.write_changes("src/a/file.py")
        source = self.current_source(value)
        envelope = {
            "plan": value,
            "task_results": {"T1": {"status": "DONE", "fresh_pass": True}},
            "final_acceptance": final_evidence(source),
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("PARTIAL", json.loads(result.stdout)["tasks"]["T1"])

    def test_complete_requires_fresh_plan_level_acceptance_evidence(self):
        value = plan([task("T1", ["src/a"])])
        self.write_changes("src/a/file.py")
        source = self.current_source(value)
        envelope = {
            "plan": value,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "evidence": [evidence_receipt(source, "check-T1")],
                }
            },
            "final_acceptance": [],
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["final_acceptance"])
        self.assertFalse(output["complete"])

    def test_应该_当调用者伪造源码身份时_以真实工作区为准(self):
        value = plan([task("T1", ["src/a"])])
        self.write_changes("src/a/file.py")
        stale_source = self.current_source(value)
        self.write_changes("src/a/file.py", "outside.txt")
        envelope = {
            "plan": value,
            "source_fingerprint": stale_source["source_fingerprint"],
            "changed_paths": ["src/a/file.py"],
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "evidence": [evidence_receipt(stale_source, "check-T1")],
                }
            },
            "final_acceptance": final_evidence(stale_source),
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("PARTIAL", output["tasks"]["T1"])
        self.assertEqual(["outside.txt"], output["scope_drift"])
        self.assertNotEqual(stale_source, output["source"])

    def test_应该_当审计收到命令字符串时_只校验回执而不执行命令(self):
        value = plan([task("T1", ["src/a"])])
        self.write_changes("src/a/file.py")
        source = self.current_source(value)
        marker = self.workspace / "must-not-exist"
        dangerous = f"touch {marker}"
        envelope = {
            "plan": value,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "evidence": [evidence_receipt(source, dangerous)],
                }
            },
            "final_acceptance": final_evidence(source),
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertFalse(marker.exists())

    def test_应该_当Git文件名包含反斜杠时_不归一化为已授权斜杠路径(self):
        value = plan([task("T1", ["src/evil"])])
        value["baseline"] = {
            "commit": self.baseline,
            "source": evidence_contract.workspace_source(self.workspace, self.baseline),
        }
        self.write_changes("src\\evil")

        result = self.run_check(
            "audit",
            {"plan": value, "task_results": {}, "final_acceptance": []},
            self.workspace,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["src\\evil"], json.loads(result.stdout)["scope_drift"])

    def test_audit_detects_committed_scope_drift_since_the_plan_baseline(self):
        value = plan([task("T1", ["src"])])
        value["baseline"] = {
            "commit": self.baseline,
            "source": evidence_contract.workspace_source(self.workspace, self.baseline),
        }
        self.write_changes("outside.txt")
        subprocess.run(["git", "-C", str(self.workspace), "add", "outside.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "outside"],
            check=True,
        )

        result = self.run_check(
            "audit",
            {"plan": value, "task_results": {}, "final_acceptance": []},
            self.workspace,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["outside.txt"], json.loads(result.stdout)["scope_drift"])

    def test_v6_ignores_preexisting_dirty_baseline_and_attributes_each_task_delta(self):
        self.write_changes("preexisting.txt")
        base_plan = granular_plan([task("T1", ["src/a"]), task("T2", ["src/b"])])
        baseline_source = self.current_source(base_plan)
        base_plan["schema_version"] = 6
        base_plan["baseline"] = {"commit": self.baseline, "source": baseline_source}

        self.write_changes("src/a/owned.py", "src/b/wrong-owner.py")
        after_t1 = self.current_source(base_plan)
        envelope = {
            "plan": base_plan,
            "task_results": {
                "T1": {
                    "status": "DONE", "fresh_pass": True,
                    "source_before": baseline_source, "source_after": after_t1,
                    "evidence": [evidence_receipt(after_t1, "check-T1")],
                }
            },
            "final_acceptance": [],
        }

        result = self.run_check("audit", envelope, self.workspace)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual("PARTIAL", output["tasks"]["T1"])
        self.assertNotIn("preexisting.txt", output["scope_drift"])
        self.assertIn("src/b/wrong-owner.py", output["task_scope_drift"]["T1"])


if __name__ == "__main__":
    unittest.main()
