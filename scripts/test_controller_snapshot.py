import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import stat
from unittest import mock
from pathlib import Path

from delivery_engine import controller_identity


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
    def test_core_identity_ignores_an_unselected_multimodel_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            before = controller_identity(source)
            optional = source / "scripts/multi_model.py"
            optional.parent.mkdir(parents=True, exist_ok=True)
            optional.write_text("changed optional extension\n", encoding="utf-8")

            self.assertEqual(before, controller_identity(source))

    def test_snapshot_freezes_only_explicitly_requested_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            core = controller_snapshot.create_snapshot(ROOT, Path(directory) / "core")
            multi = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "multi", extensions=("multimodel",)
            )

            self.assertEqual([], core["extensions"])
            self.assertEqual(["multimodel"], multi["extensions"])
            self.assertNotIn("scripts/multi_model.py", core["files"])
            self.assertNotIn("scripts/autonomy_contract.py", core["files"])
            self.assertIn("scripts/multi_model.py", multi["files"])
            self.assertIn("scripts/multi_model_smoke.py", multi["files"])
            self.assertIn("scripts/multi_model_repo_eval.py", multi["files"])
            self.assertIn("references/multi-model-repository-evaluation.json", multi["files"])
            self.assertNotIn("scripts/autonomy_begin.py", multi["files"])

    def test_legacy_profile_maps_to_the_same_canonical_extension_set(self):
        self.assertEqual((), controller_snapshot.snapshot_extensions({"profile": "core"}))
        self.assertEqual(
            ("multimodel", "autonomy", "autonomy-eval"),
            controller_snapshot.snapshot_extensions({"profile": "extended"}),
        )

    def test_hook_autonomy_does_not_freeze_multimodel_but_service_does(self):
        with tempfile.TemporaryDirectory() as directory:
            hook = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "hook", extensions=("autonomy",)
            )
            service = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "service", extensions=("multimodel", "autonomy")
            )

            self.assertEqual(["autonomy"], hook["extensions"])
            self.assertIn("scripts/autonomy_contract.py", hook["files"])
            self.assertNotIn("scripts/multi_model.py", hook["files"])
            self.assertNotIn("scripts/autonomous_delivery_eval.py", hook["files"])
            self.assertEqual(["multimodel", "autonomy"], service["extensions"])
            self.assertIn("scripts/multi_model.py", service["files"])

    def test_autonomy_evaluation_files_are_frozen_only_when_explicitly_requested(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control", extensions=("autonomy-eval",)
            )

            self.assertEqual(["autonomy", "autonomy-eval"], descriptor["extensions"])
            self.assertIn("scripts/autonomous_delivery_eval.py", descriptor["files"])
            self.assertIn("scripts/test_autonomy_hook.py", descriptor["files"])
            self.assertIn("scripts/autonomy_hook_config.py", descriptor["files"])
            self.assertIn("scripts/test_autonomy_hook_config.py", descriptor["files"])
            self.assertIn("scripts/autonomy_service_config.py", descriptor["files"])
            self.assertIn("scripts/test_autonomy_service_config.py", descriptor["files"])

    def test_autonomy_only_snapshot_cannot_run_the_service(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control", extensions=("autonomy",)
            )
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "requires autonomy and multimodel"):
                controller_snapshot.trusted_command(
                    descriptor_path, "scripts/autonomy_service.py", []
                )

    def test_launch_uses_a_valid_snapshot_after_the_live_protocol_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            with mock.patch.object(
                    controller_snapshot, "PROTOCOL_VERSION", controller_snapshot.PROTOCOL_VERSION + 1):
                command = controller_snapshot.trusted_command(
                    descriptor_path, "scripts/delivery_engine.py", ["select"]
                )

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(Path(descriptor["root"]) / "scripts/delivery_engine.py"), command[1])

    def test_launch_rejects_a_descriptor_that_does_not_fingerprint_its_bootstrap(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            descriptor["files"].remove("scripts/controller_snapshot.py")
            descriptor["protocol_fingerprint"] = controller_snapshot.aggregate_fingerprint(
                descriptor["root"], descriptor["files"]
            )
            snapshot = Path(descriptor["root"])
            renamed = snapshot.with_name(descriptor["protocol_fingerprint"])
            snapshot.rename(renamed)
            descriptor["root"] = str(renamed)
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            with mock.patch.object(controller_snapshot.subprocess, "run") as run, \
                    self.assertRaisesRegex(ValueError, "bootstrap"):
                controller_snapshot.trusted_command(
                    descriptor_path, "scripts/delivery_engine.py", ["select"]
                )

            run.assert_not_called()

    def legacy_descriptor(self, directory):
        control = Path(directory) / "control"
        temporary = control / "temporary"
        files = [
            *controller_snapshot.EXTENDED_CONTROLLER_FILES,
            *controller_snapshot.EXTENDED_CONTROL_RESOURCE_FILES,
            *controller_snapshot.provider_files(ROOT),
        ]
        for relative in (*files, "VERSION"):
            target = temporary / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)
        fingerprint = controller_snapshot.aggregate_fingerprint(temporary, files)
        snapshot = control / fingerprint
        temporary.rename(snapshot)
        for path in (snapshot, *snapshot.rglob("*")):
            path.chmod(0o555 if path.is_dir() else 0o444)
        return {
            "root": str(snapshot), "control_root": str(control), "source_root": str(ROOT),
            "package_version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
            "protocol_version": 16, "protocol_fingerprint": fingerprint,
            "profile": "extended", "files": files,
        }

    def test_legacy_v16_descriptor_can_launch_its_frozen_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = self.legacy_descriptor(directory)
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            command = controller_snapshot.trusted_command(
                descriptor_path, "scripts/delivery_engine.py", ["select"]
            )

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(Path(descriptor["root"]) / "scripts/delivery_engine.py"), command[1])

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
        for relative in controller_snapshot.EXTENDED_CONTROLLER_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        for relative in controller_snapshot.PROVIDER_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        for relative in controller_snapshot.EXTENDED_CONTROL_RESOURCE_FILES:
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
            descriptor = controller_snapshot.create_snapshot(
                source, Path(directory) / "control",
                extensions=("multimodel", "autonomy-eval"),
            )
            (source / controller_snapshot.CONTROLLER_FILES[0]).write_text("self modified\n", encoding="utf-8")

            identity = controller_snapshot.validate_snapshot(descriptor)
            self.assertTrue((Path(descriptor["root"]) / "scripts/delivery_next.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "scripts/tdd_impact_guard.py").is_file())
            self.assertFalse((Path(descriptor["root"]) / "scripts/fast_path.py").exists())
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
            self.assertTrue((Path(descriptor["root"]) / "scripts/multi_model_repo_eval.py").is_file())
            self.assertTrue((Path(descriptor["root"]) / "providers/native-v1.json").is_file())
            self.assertTrue((Path(descriptor["root"]) / "SKILL.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/state-schema.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/reporting.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/tdd-providers.md").is_file())
            self.assertTrue((Path(descriptor["root"]) / "references/worker-runners.md").is_file())
            self.assertNotIn("scripts/fast_path.py", descriptor["files"])
            self.assertIn("scripts/openai_compatible_runner.py", descriptor["files"])
            self.assertIn("scripts/tdd_impact_guard.py", descriptor["files"])
            self.assertIn("scripts/role_flow.py", descriptor["files"])
            self.assertIn("scripts/role_dispatch.py", descriptor["files"])
            self.assertIn("scripts/role_fanout.py", descriptor["files"])
            self.assertIn("scripts/role_result.py", descriptor["files"])
            self.assertIn("scripts/runner_launch.py", descriptor["files"])
            self.assertIn("scripts/runner_lifecycle.py", descriptor["files"])
            self.assertIn("scripts/multi_model_eval.py", descriptor["files"])
            self.assertIn("scripts/multi_model_repo_eval.py", descriptor["files"])
            for relative in REQUIRED_CONTROL_REFERENCES:
                self.assertIn(relative, descriptor["files"])
                self.assertEqual(f"{relative}\n", (Path(descriptor["root"]) / relative).read_text())

        self.assertEqual("1.0.0", identity["package_version"])
        self.assertEqual(["multimodel", "autonomy", "autonomy-eval"], identity["extensions"])
        self.assertNotEqual(str(source), descriptor["root"])

    def test_core_snapshot_omits_optional_workers_and_direct_test_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            self.assertEqual([], descriptor["extensions"])
            self.assertNotIn("scripts/autonomy_begin.py", descriptor["files"])
            self.assertNotIn("scripts/multi_model.py", descriptor["files"])
            self.assertNotIn("scripts/test_delivery_next.py", descriptor["files"])
            with self.assertRaisesRegex(ValueError, "not authorized"):
                controller_snapshot.trusted_command(
                    descriptor_path, "scripts/test_delivery_next.py", []
                )

    def test_core_snapshot_can_load_the_local_review_lifecycle_without_multimodel(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            snapshot = Path(descriptor["root"])
            result = subprocess.run([
                sys.executable, "-c", "import runner_lifecycle; import runner_launch",
            ], cwd=snapshot / "scripts", text=True, capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((snapshot / "scripts/multi_model.py").exists())
            self.assertFalse((snapshot / "scripts/openai_compatible_runner.py").exists())

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
