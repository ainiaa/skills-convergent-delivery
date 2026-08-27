import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import stat
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("controller_snapshot.py")
ROOT = MODULE_PATH.parent.parent
SPEC = importlib.util.spec_from_file_location("controller_snapshot", MODULE_PATH)
controller_snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller_snapshot)
REQUIRED_CONTROL_REFERENCES = (
    "evals/evals.json",
    "references/activation.md",
    "references/evaluation-scenarios.md",
    "references/evaluation-catalog.json",
    "references/review-orchestration.md",
    "references/worker-runners.md",
    "references/multi-model.md",
    "references/multi-model-evaluation.json",
    "references/autonomous-delivery-evaluation.json",
    "references/runtime-adapters.md",
    "skills/converge-plan/SKILL.md",
    "skills/converge-plan/references/plan-contract.md",
    "skills/converge-plan/scripts/plan_check.py",
    "skills/converge-review/SKILL.md",
    "skills/converge-review/references/review-contract.md",
    "skills/converge-review/scripts/review_contract.py",
    "skills/converge-batch/SKILL.md",
    "skills/converge-batch/references/batch-contract.md",
    "skills/converge-batch/references/runtime-adapters.md",
    "skills/converge-batch/scripts/batch_next.py",
    "skills/converge-batch/scripts/batch_state.py",
    "skills/converge-eval/SKILL.md",
    "skills/converge-eval/references/evaluation-contract.json",
    "skills/converge-eval/scripts/eval_contract.py",
    "scripts/trigger_eval.py",
)


class ControllerSnapshotTest(unittest.TestCase):
    def test_writable_workspace_cannot_masquerade_as_a_controller_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            fake = controller_snapshot.descriptor(
                source, controller_snapshot.aggregate_fingerprint(source), "1.0.0"
            )

            with self.assertRaisesRegex(ValueError, "snapshot|provenance|writable"):
                controller_snapshot.validate_snapshot(fake)

    def test_frozen_resolver_can_select_native_without_the_live_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "run",
                    "--descriptor",
                    str(descriptor_path),
                    "--script",
                    "scripts/delivery_engine.py",
                    "--",
                    "select",
                    "--mode",
                    "auto",
                    "--kind",
                    "feature",
                ],
                text=True,
                capture_output=True,
                check=False,
                env={**os.environ, "HOME": str(Path(directory) / "empty-home")},
            )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("native-v1", json.loads(result.stdout)["engine"])

    def source(self, directory):
        source = Path(directory) / "suite"
        for relative in controller_snapshot.CONTROLLER_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        for relative in controller_snapshot.PROVIDER_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        for relative in controller_snapshot.CONTROL_RESOURCE_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        for relative in REQUIRED_CONTROL_REFERENCES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        (source / "VERSION").write_text("1.0.0\n", encoding="utf-8")
        return source

    def test_self_modification_keeps_the_frozen_snapshot_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            descriptor = controller_snapshot.create_snapshot(source, Path(directory) / "control")
            (source / controller_snapshot.CONTROLLER_FILES[0]).write_text("self modified\n", encoding="utf-8")

            identity = controller_snapshot.validate_snapshot(descriptor)
            self.assertTrue((Path(descriptor["root"]) / "scripts/delivery_next.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/fast_path.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/runner_registry.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/role_flow.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/role_dispatch.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/role_fanout.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/role_result.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/codex_exec_runner.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/claude_exec_runner.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/runner_launch.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/runner_lifecycle.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/multi_model_eval.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "providers/native-v1.json").is_file())
            self.assertTrue((Path(descriptor["root"]) / "SKILL.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/state-schema.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/reporting.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/tdd-providers.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/worker-runners.md").is_file())
            self.assertIn("scripts/fast_path.py", descriptor["files"])
            self.assertIn("scripts/openai_compatible_runner.py", descriptor["files"])
            self.assertIn("scripts/role_flow.py", descriptor["files"])
            self.assertIn("scripts/role_dispatch.py", descriptor["files"])
            self.assertIn("scripts/role_fanout.py", descriptor["files"])
            self.assertIn("scripts/role_result.py", descriptor["files"])
            self.assertIn("scripts/runner_launch.py", descriptor["files"])
            self.assertIn("scripts/runner_lifecycle.py", descriptor["files"])
            self.assertIn("scripts/multi_model_eval.py", descriptor["files"])
            for relative in REQUIRED_CONTROL_REFERENCES:
                self.assertIn(relative, descriptor["files"])
                self.assertEqual(f"{relative}\n", (Path(descriptor["root"]) / relative).read_text())

        self.assertEqual("1.0.0", identity["package_version"])
        self.assertNotEqual(str(source), descriptor["root"])

    def test_version_only_change_creates_a_distinct_content_addressed_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            control = Path(directory) / "control"
            first = controller_snapshot.create_snapshot(source, control)
            (source / "VERSION").write_text("1.0.1\n", encoding="utf-8")

            second = controller_snapshot.create_snapshot(source, control)

            self.assertNotEqual(first["root"], second["root"])
            self.assertEqual("1.0.1", second["package_version"])

    def test_snapshot_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                self.source(directory), Path(directory) / "control"
            )
            snapshot = Path(descriptor["root"])
            (snapshot / controller_snapshot.CONTROLLER_FILES[0]).chmod(0o600)
            (snapshot / controller_snapshot.CONTROLLER_FILES[0]).write_text("tampered\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "snapshot.*changed"):
                controller_snapshot.validate_snapshot(descriptor)

    def test_snapshot_makes_every_nested_directory_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                self.source(directory), Path(directory) / "control"
            )
            snapshot = Path(descriptor["root"])
            writable = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH

            for path in (snapshot, *sorted(path for path in snapshot.rglob("*") if path.is_dir())):
                with self.subTest(path=path.relative_to(snapshot)):
                    self.assertEqual(0, path.stat().st_mode & writable)

    def test_snapshot_freezes_every_manifest_seen_by_the_provider_registry(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            extra = source / "providers/extra-v1.json"
            manifest = json.loads((ROOT / "providers/native-v1.json").read_text())
            manifest["provider"].update(id="extra-v1", source_id="test/extra")
            extra.write_text(json.dumps(manifest), encoding="utf-8")

            descriptor = controller_snapshot.create_snapshot(
                source, Path(directory) / "control"
            )

            self.assertIn("providers/extra-v1.json", descriptor["files"])
            self.assertTrue((Path(descriptor["root"]) / "providers/extra-v1.json").is_file())

    def test_trusted_runner_rejects_tampering_before_the_helper_starts(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")
            snapshot = Path(descriptor["root"])
            scripts = snapshot / "scripts"
            scripts.chmod(0o700)
            target = scripts / "provider_contract.py"
            target.chmod(0o600)
            target.write_text("raise RuntimeError('must not import')\n", encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "run",
                    "--descriptor",
                    str(descriptor_path),
                    "--script",
                    "scripts/delivery_engine.py",
                    "--",
                    "select",
                    "--mode",
                    "native",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(2, result.returncode)
            self.assertIn("controller snapshot blocked", result.stderr)
            self.assertNotIn("invalid choice", result.stderr)
            self.assertNotIn("must not import", result.stderr)

    def test_trusted_runner_executes_only_the_frozen_batch_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            result = subprocess.run(
                [
                    sys.executable,
                    str(MODULE_PATH),
                    "run",
                    "--descriptor",
                    str(descriptor_path),
                    "--script",
                    "skills/converge-batch/scripts/batch_next.py",
                    "--",
                    "--help",
                ],
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn("--input", result.stdout)
            eval_command = controller_snapshot.trusted_command(
                descriptor_path,
                "skills/converge-eval/scripts/eval_contract.py",
                ["--help"],
            )
            self.assertTrue(eval_command[1].endswith("skills/converge-eval/scripts/eval_contract.py"))
            with self.assertRaisesRegex(ValueError, "not authorized"):
                controller_snapshot.trusted_command(
                    descriptor_path,
                    "skills/converge-review/scripts/review_contract.py",
                    ["--help"],
                )
            with self.assertRaisesRegex(ValueError, "not authorized"):
                controller_snapshot.trusted_command(
                    descriptor_path, "skills/converge-batch/SKILL.md", []
                )

    def test_legacy_snapshot_can_only_release_its_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            descriptor["protocol_version"] -= 1
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            command = controller_snapshot.trusted_command(
                descriptor_path, "scripts/delivery_lease.py", ["release"]
            )
            self.assertEqual(
                str(MODULE_PATH.with_name("delivery_lease.py").resolve()),
                command[1],
            )
            with self.assertRaisesRegex(ValueError, "protocol changed"):
                controller_snapshot.trusted_command(
                    descriptor_path, "scripts/delivery_next.py", []
                )

    def test_current_snapshot_release_executes_the_frozen_lease_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            command = controller_snapshot.trusted_command(
                descriptor_path, "scripts/delivery_lease.py", ["release"]
            )

            self.assertEqual(
                str(Path(descriptor["root"]) / "scripts/delivery_lease.py"), command[1]
            )

    def test_legacy_release_never_executes_the_snapshot_lease_script(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control"
            )
            snapshot_script = Path(descriptor["root"]) / "scripts/delivery_lease.py"
            snapshot_script.chmod(0o600)
            snapshot_script.write_text("raise RuntimeError('legacy payload executed')\n")
            snapshot_script.chmod(0o400)
            descriptor["protocol_version"] -= 1
            descriptor["protocol_fingerprint"] = controller_snapshot.aggregate_fingerprint(
                descriptor["root"], descriptor["files"]
            )
            snapshot = Path(descriptor["root"])
            renamed = snapshot.with_name(descriptor["protocol_fingerprint"])
            snapshot.rename(renamed)
            descriptor["root"] = str(renamed)
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            command = controller_snapshot.trusted_command(
                descriptor_path, "scripts/delivery_lease.py", ["release"]
            )

            self.assertEqual(
                str(MODULE_PATH.with_name("delivery_lease.py").resolve()),
                command[1],
            )


if __name__ == "__main__":
    unittest.main()
