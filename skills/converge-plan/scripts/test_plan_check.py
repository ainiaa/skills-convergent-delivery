import json
import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("plan_check.py")
SHA = "a" * 64
SOURCE_SHA = "b" * 64


def task(task_id, paths, depends_on=None, execution="auto"):
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
    }


def plan(tasks, engine="native-v1", context="short", planner=None):
    return {
        "schema_version": 1,
        "plan_id": "plan-example",
        "requirement_fingerprint": SHA,
        "engine": engine,
        "planner": planner or {
            "name": "pdlc-delegation-v1" if engine == "pdlc-v1" else "native-plan-v1",
            "source_path": None,
            "source_fingerprint": None,
        },
        "context": context,
        "tasks": tasks,
        "final_acceptance": ["all checks pass"],
        "decisions": [],
    }


def final_evidence(source_fingerprint=SOURCE_SHA):
    return [
        {
            "criterion": "all checks pass",
            "result": "pass",
            "freshness": "fresh",
            "evidence": "bash scripts/check.sh exited 0",
            "verified_source_fingerprint": source_fingerprint,
        }
    ]


class PlanCheckTest(unittest.TestCase):
    def run_check(self, command, payload):
        return subprocess.run(
            ["python3", str(SCRIPT), command, "--input", "-"],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            check=False,
        )

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

    def test_pdlc_is_one_fresh_pdlc_run_task(self):
        valid = plan([task("pdlc-run", ["."])], engine="pdlc-v1")
        invalid = plan(
            [task("requirements", ["docs"]), task("implementation", ["src"])],
            engine="pdlc-v1",
        )

        accepted = self.run_check("validate", valid)
        rejected = self.run_check("validate", invalid)

        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertEqual("fresh", json.loads(accepted.stdout)["execution_mode"])
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("pdlc-run", rejected.stderr)

    def test_rejects_cycles_unknown_dependencies_and_duplicate_ids(self):
        cases = [
            plan([task("T1", ["a"], ["T2"]), task("T2", ["b"], ["T1"])]),
            plan([task("T1", ["a"], ["missing"])]),
            plan([task("T1", ["a"]), task("T1", ["b"])]),
        ]

        for value in cases:
            with self.subTest(value=value):
                self.assertNotEqual(0, self.run_check("validate", value).returncode)

    def test_rejects_unknown_engines_and_unfrozen_third_party_planners(self):
        unknown_engine = plan([task("T1", ["a"])], engine="invented-v1")
        unfrozen_planner = plan(
            [task("T1", ["a"])],
            planner={
                "name": "generic-plan-v1",
                "source_path": None,
                "source_fingerprint": None,
            },
        )

        self.assertNotEqual(0, self.run_check("validate", unknown_engine).returncode)
        self.assertNotEqual(0, self.run_check("validate", unfrozen_planner).returncode)

    def test_long_single_task_uses_a_fresh_context(self):
        result = self.run_check("validate", plan([task("T1", ["src"])], context="long"))

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("fresh", json.loads(result.stdout)["execution_mode"])

    def test_audit_reports_partial_missing_changed_and_scope_drift(self):
        value = plan(
            [task("T1", ["src/a"]), task("T2", ["src/b"]), task("T3", ["src/c"])]
        )
        envelope = {
            "plan": value,
            "source_fingerprint": SOURCE_SHA,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "verified_source_fingerprint": SOURCE_SHA,
                    "evidence": ["check-T1 exited 0"],
                },
                "T2": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "verified_source_fingerprint": SHA,
                    "evidence": ["check-T2 exited 0 before the last change"],
                },
                "T3": {"status": "CHANGED", "fresh_pass": True},
            },
            "final_acceptance": final_evidence(),
            "changed_paths": ["src/a/file.py", "src/b/file.py", "extra.txt"],
        }

        result = self.run_check("audit", envelope)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(
            {"T1": "DONE", "T2": "PARTIAL", "T3": "CHANGED"}, output["tasks"]
        )
        self.assertEqual(["extra.txt"], output["scope_drift"])
        self.assertFalse(output["complete"])

    def test_done_without_bound_evidence_is_downgraded_to_partial(self):
        value = plan([task("T1", ["src/a"])])
        envelope = {
            "plan": value,
            "source_fingerprint": SOURCE_SHA,
            "task_results": {"T1": {"status": "DONE", "fresh_pass": True}},
            "final_acceptance": final_evidence(),
            "changed_paths": ["src/a/file.py"],
        }

        result = self.run_check("audit", envelope)

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("PARTIAL", json.loads(result.stdout)["tasks"]["T1"])

    def test_complete_requires_fresh_plan_level_acceptance_evidence(self):
        value = plan([task("T1", ["src/a"])])
        envelope = {
            "plan": value,
            "source_fingerprint": SOURCE_SHA,
            "task_results": {
                "T1": {
                    "status": "DONE",
                    "fresh_pass": True,
                    "verified_source_fingerprint": SOURCE_SHA,
                    "evidence": ["check-T1 exited 0"],
                }
            },
            "final_acceptance": [],
            "changed_paths": ["src/a/file.py"],
        }

        result = self.run_check("audit", envelope)

        self.assertEqual(0, result.returncode, result.stderr)
        output = json.loads(result.stdout)
        self.assertFalse(output["final_acceptance"])
        self.assertFalse(output["complete"])


if __name__ == "__main__":
    unittest.main()
