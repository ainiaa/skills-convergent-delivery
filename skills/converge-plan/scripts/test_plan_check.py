import json
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("plan_check.py")
SHA = "a" * 64


def provider_binding(workflow="native-v1", tdd=None):
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


def task(task_id, paths, depends_on=None, execution="auto", provider=None):
    return {
        "task_id": task_id,
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


def plan(tasks, context="short", planner=None):
    return {
        "schema_version": 2,
        "plan_id": "plan-example",
        "requirement_fingerprint": SHA,
        "planner": planner or {
            "name": "native-plan-v1",
            "source_path": None,
            "source_fingerprint": None,
        },
        "context": context,
        "tasks": tasks,
        "final_acceptance": ["all checks pass"],
        "decisions": [],
    }


def evidence_receipt(source, command="bash scripts/check.sh"):
    return {"command": command, "exit_code": 0, "source": source}


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

    def run_check(self, command, payload, workspace=None):
        arguments = ["python3", str(SCRIPT), command, "--input", "-"]
        if workspace is not None:
            arguments.extend(["--workspace", str(workspace)])
        return subprocess.run(
            arguments,
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

    def current_source(self, value):
        result = self.run_check(
            "audit",
            {"plan": value, "task_results": {}, "final_acceptance": []},
            self.workspace,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return json.loads(result.stdout)["source"]

    def write_changes(self, *paths):
        for path in paths:
            target = self.workspace / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(f"changed {path}\n", encoding="utf-8")

    def test_independent_tasks_share_a_wave_and_dependencies_form_the_next_wave(self):
        value = plan(
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
        self.assertEqual("batch", output["execution_mode"])

    def test_overlapping_paths_are_serialized_even_without_dependencies(self):
        value = plan([task("T1", ["src/shared"]), task("T2", ["src/shared/file.py"])])

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["T1"], ["T2"]], json.loads(result.stdout)["waves"])

    def test_multiple_bounded_pdlc_runs_are_allowed_in_one_plan(self):
        value = plan(
            [
                task("schema", ["providers"], provider=provider_binding("pdlc-v1")),
                task(
                    "runtime",
                    ["scripts"],
                    ["schema"],
                    provider=provider_binding("pdlc-v1"),
                ),
            ]
        )

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual([["schema"], ["runtime"]], json.loads(result.stdout)["waves"])
        self.assertEqual("batch", json.loads(result.stdout)["execution_mode"])

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
                value = plan([task("T1", ["src"], provider=provider_binding("pdlc-v1"))])
                value["tasks"][0]["provider_run"] = provider_run

                self.assertNotEqual(0, self.run_check("validate", value).returncode)

    def test_v1_engine_plan_is_migrated_to_provider_bindings(self):
        value = plan([task("pdlc-run", ["."])])
        value["schema_version"] = 1
        value["engine"] = "pdlc-v1"
        value["planner"]["name"] = "pdlc-delegation-v1"
        value["tasks"][0].pop("provider_binding")

        result = self.run_check("validate", value)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(2, json.loads(result.stdout)["normalized_schema_version"])

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
        unknown_provider = plan(
            [task("T1", ["a"], provider=provider_binding("invented-v1"))]
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
        result = self.run_check("validate", plan([task("T1", ["src"])], context="long"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("fresh", json.loads(result.stdout)["execution_mode"])

    def test_audit_reports_partial_missing_changed_and_scope_drift(self):
        value = plan(
            [task("T1", ["src/a"]), task("T2", ["src/b"]), task("T3", ["src/c"])]
        )
        self.write_changes("src/a/file.py", "src/b/file.py", "extra.txt")
        source = self.current_source(value)
        envelope = {
            "plan": value,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
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
            {"T1": "DONE", "T2": "PARTIAL", "T3": "CHANGED"}, output["tasks"]
        )
        self.assertEqual(["extra.txt"], output["scope_drift"])
        self.assertFalse(output["complete"])

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
        self.write_changes("src\\evil")

        result = self.run_check(
            "audit",
            {"plan": value, "task_results": {}, "final_acceptance": []},
            self.workspace,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(["src\\evil"], json.loads(result.stdout)["scope_drift"])


if __name__ == "__main__":
    unittest.main()
