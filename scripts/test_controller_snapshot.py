import importlib.util
import io
import json
import os
import py_compile
import shutil
import subprocess
import sys
import tempfile
import unittest
import stat
import venv
from unittest import mock
from pathlib import Path

from delivery_engine import controller_identity


MODULE_PATH = Path(__file__).with_name("controller_snapshot.py")
ROOT = MODULE_PATH.parent.parent
SPEC = importlib.util.spec_from_file_location("controller_snapshot", MODULE_PATH)
controller_snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(controller_snapshot)
REQUIRED_CONTROL_REFERENCES = (
    "extensions/converge-multimodel/SKILL.md",
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


def python_with_startup_marker(root):
    environment = root / "python-env"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(environment)
    python = environment / "bin" / "python"
    purelib = subprocess.check_output(
        [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True,
    ).strip()
    marker = root / "site-startup-ran"
    (Path(purelib) / "converge-test.pth").write_text(
        f"import pathlib; pathlib.Path({str(marker)!r}).touch()\n", encoding="utf-8",
    )
    subprocess.run([str(python), "-c", "pass"], check=True)
    marker.unlink()  # A normal startup must have processed the marker.
    return python, marker


class ControllerSnapshotTest(unittest.TestCase):
    def test_core_snapshot_can_follow_root_guidance_and_run_topology_check(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            frozen = Path(descriptor["root"])
            for name in ("execution-topology.md", "reference-alignment.md", "host-capabilities.md"):
                path = Path("references") / name
                with self.subTest(path=path):
                    self.assertEqual((ROOT / path).read_bytes(), (frozen / path).read_bytes())

            topology = {
                "schema_version": 1, "mode": "sequential",
                "writers": [{"id": "controller", "workspace": directory, "allowed_paths": ["src"],
                             "isolation_evidence": ["single writer"]}],
                "integrator": None, "joint_verification": [],
            }
            result = subprocess.run([sys.executable, str(frozen / "scripts/execution_topology.py")],
                                    input=json.dumps(topology), cwd=directory, capture_output=True, text=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_protocol_25_without_the_added_resources_remains_readable(self):
        resources = tuple(path for path in controller_snapshot.CORE_CONTROL_RESOURCE_FILES if path not in {
            "references/execution-topology.md", "references/reference-alignment.md", "references/host-capabilities.md",
        })
        scripts = tuple(path for path in controller_snapshot.CORE_CONTROLLER_FILES
                        if path != "scripts/execution_topology.py")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(controller_snapshot, "PROTOCOL_VERSION", 25), \
                    mock.patch.object(controller_snapshot, "CORE_CONTROL_RESOURCE_FILES", resources), \
                    mock.patch.object(controller_snapshot, "CORE_CONTROLLER_FILES", scripts):
                frozen = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            self.assertNotIn("scripts/execution_topology.py", frozen["files"])
            self.assertEqual(frozen, controller_snapshot.validate_snapshot(frozen))

    def test_inline_tdd_is_readable_from_core_and_host_eval_snapshots(self):
        relative = "references/inline-tdd.md"
        for extensions in ((), ("host-eval",)):
            with self.subTest(extensions=extensions), tempfile.TemporaryDirectory() as directory:
                frozen = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control", extensions)
                path = Path(frozen["root"]) / relative
                self.assertTrue(path.is_file(), "frozen simple tasks must be able to read Inline TDD")
                self.assertIn(relative, frozen["files"])
                result = subprocess.run([sys.executable, "-c",
                    "from pathlib import Path; import sys; print(Path(sys.argv[1]).read_text(), end='')",
                    str(path)], capture_output=True, text=True, check=False)
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual((ROOT / relative).read_text(), result.stdout)

    def test_inline_tdd_remains_frozen_when_the_live_reference_changes(self):
        relative = "references/inline-tdd.md"
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            live = source / relative
            live.write_text("original inline guidance\n")
            frozen = controller_snapshot.create_snapshot(source, Path(directory) / "control")
            path = Path(frozen["root"]) / relative
            self.assertTrue(path.is_file(), "the inline reference must be part of the snapshot")
            live.write_text("changed live guidance\n")
            self.assertEqual("original inline guidance\n", path.read_text())
            self.assertEqual(frozen, controller_snapshot.validate_snapshot(frozen))
            changed = controller_snapshot.create_snapshot(source, Path(directory) / "control")
            self.assertNotEqual(frozen["protocol_fingerprint"], changed["protocol_fingerprint"])

    def test_missing_inline_tdd_blocks_snapshot_creation_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            path = source / "references/inline-tdd.md"
            path.write_text("inline guidance\n")
            path.unlink()
            control = Path(directory) / "control"
            with self.assertRaisesRegex(ValueError, "references/inline-tdd.md"):
                controller_snapshot.create_snapshot(source, control)
            self.assertFalse(control.exists())

    def test_protocol_23_without_inline_tdd_remains_readable(self):
        resources = tuple(path for path in controller_snapshot.CORE_CONTROL_RESOURCE_FILES
                          if path != "references/inline-tdd.md")
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(controller_snapshot, "PROTOCOL_VERSION", 23), \
                    mock.patch.object(controller_snapshot, "CORE_CONTROL_RESOURCE_FILES", resources):
                frozen = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control", ("host-eval",))
            self.assertNotIn("references/inline-tdd.md", frozen["files"])
            self.assertEqual(frozen, controller_snapshot.validate_snapshot(frozen))

    def test_protocol_21_and_22_snapshots_remain_readable_without_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            for version in (21,22):
                with self.subTest(version=version),mock.patch.object(controller_snapshot, 'PROTOCOL_VERSION', version):
                    frozen = controller_snapshot.create_snapshot(ROOT, Path(directory) / 'control', ('multimodel',))
                self.assertEqual(frozen, controller_snapshot.validate_snapshot(frozen))

    def test_protocol_18_and_19_profile_descriptors_remain_readable(self):
        with tempfile.TemporaryDirectory() as directory:
            for version in (18,19):
                with mock.patch.object(controller_snapshot,'PROTOCOL_VERSION',version):
                    frozen=controller_snapshot.create_snapshot(ROOT,Path(directory)/'control',())
                legacy={key:value for key,value in frozen.items() if key!='extensions'}
                legacy['profile']='core'
                self.assertEqual(legacy,controller_snapshot.validate_snapshot(legacy))

    def test_multimodel_snapshot_freezes_the_extension_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            frozen = controller_snapshot.create_snapshot(ROOT, Path(directory) / 'control', ('multimodel',))
            relative = 'extensions/converge-multimodel/SKILL.md'
            self.assertIn(relative, frozen['files'])
            self.assertEqual((ROOT / relative).read_bytes(), (Path(frozen['root']) / relative).read_bytes())

    def test_protocol_20_snapshot_without_extension_entry_remains_readable(self):
        registry = dict(controller_snapshot.EXTENSIONS)
        scripts, resources = registry['multimodel']
        registry['multimodel'] = (scripts, tuple(p for p in resources if not p.startswith('extensions/')))
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(controller_snapshot, 'PROTOCOL_VERSION', 20), \
                    mock.patch.object(controller_snapshot, 'EXTENSIONS', registry):
                old = controller_snapshot.create_snapshot(ROOT, Path(directory) / 'control', ('multimodel',))
            self.assertEqual(old, controller_snapshot.validate_snapshot(old))

    def test_malformed_collection_elements_and_protocol_are_validation_errors(self):
        for value in ([{}], [[]], [None], [1]):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    controller_snapshot.normalize_extensions(value)
                for protocol in (controller_snapshot.PROTOCOL_VERSION, 17):
                    with self.assertRaises(ValueError):
                        controller_snapshot.snapshot_extensions({"protocol_version": protocol, "extensions": value})
                self.assertFalse(controller_snapshot.frozen_files_are_valid(value))
        with self.assertRaises(ValueError):
            controller_snapshot.snapshot_extensions({"profile": {}})
        descriptor = {
            "root": "/control/frozen", "control_root": "/control", "source_root": "/source",
            "package_version": "0.8.0", "protocol_fingerprint": "a" * 64,
            "extensions": [], "files": [],
        }
        for protocol in ([], {}, None, True, "18"):
            with self.subTest(protocol=protocol), self.assertRaises(ValueError):
                controller_snapshot.validate_snapshot({**descriptor, "protocol_version": protocol})

    def test_frozen_controller_can_select_independent_work_without_live_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(__file__).resolve().parents[1]
            frozen = controller_snapshot.create_snapshot(source, Path(directory) / "control")
            root = Path(frozen["root"])
            result = subprocess.run([sys.executable, "-c",
                "from plan_execution import select_task; "
                "tasks=[{'task_id':'T1','depends_on':[],'owned_paths':['a']},"
                "{'task_id':'T2','depends_on':[],'owned_paths':['b']}]; "
                "assert select_task(tasks, {'T1':'blocked'})['task_id']=='T2'"],
                cwd=directory, env={**os.environ, "PYTHONPATH": str(root / "scripts")},
                text=True, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr)

    def test_snapshot_validator_rejects_missing_version_and_mutable_frozen_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            (source / "VERSION").unlink()
            with self.assertRaisesRegex(ValueError, "VERSION"):
                controller_snapshot.create_snapshot(source, Path(directory) / "control")

        with tempfile.TemporaryDirectory() as directory:
            control = Path(directory) / "control"
            descriptor = controller_snapshot.create_snapshot(ROOT, control)
            snapshot = Path(descriptor["root"])

            invalid = json.loads(json.dumps(descriptor))
            invalid["files"] = []
            with self.assertRaises(ValueError):
                controller_snapshot.validate_snapshot(invalid)

            invalid = json.loads(json.dumps(descriptor))
            invalid["source_root"] = str(snapshot.parent)
            with self.assertRaisesRegex(ValueError, "isolated"):
                controller_snapshot.validate_snapshot(invalid)

            snapshot.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "writable"):
                controller_snapshot.validate_snapshot(descriptor)
            snapshot.chmod(0o500)

            script_dir = snapshot / "scripts"
            script_dir.chmod(0o700)
            with self.assertRaisesRegex(ValueError, "directory is writable"):
                controller_snapshot.validate_snapshot(descriptor)
            script_dir.chmod(0o500)

            source_file = snapshot / "scripts" / "delivery_engine.py"
            source_file.chmod(0o600)
            with self.assertRaisesRegex(ValueError, "file is writable"):
                controller_snapshot.validate_snapshot(descriptor)

    def test_snapshot_cli_reports_missing_create_and_run_inputs_without_writing(self):
        with mock.patch.object(sys, "argv", [str(MODULE_PATH), "create"]), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(2, controller_snapshot.main())
        self.assertIn("create requires", stderr.getvalue())
        with mock.patch.object(sys, "argv", [str(MODULE_PATH), "run"]), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(2, controller_snapshot.main())
        self.assertIn("run requires", stderr.getvalue())

    def test_snapshot_validation_ignores_inherited_pythonpath(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = controller_snapshot.create_snapshot(ROOT, root / "control")
            marker = root / "inherited-module-ran"
            (root / "subprocess.py").write_text(f"open({str(marker)!r}, 'w').close()\nraise SystemExit(0)\n")

            with mock.patch.dict(os.environ, {"PYTHONPATH": str(root)}):
                self.assertEqual(descriptor, controller_snapshot.validate_launch_snapshot(descriptor))

            self.assertFalse(marker.exists())

    def test_snapshot_validation_skips_site_startup_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = controller_snapshot.create_snapshot(ROOT, root / "control")
            python, marker = python_with_startup_marker(root)

            with mock.patch.object(sys, "executable", str(python)):
                self.assertEqual(descriptor, controller_snapshot.validate_launch_snapshot(descriptor))

            self.assertFalse(marker.exists())

    def test_snapshot_validation_refuses_unlisted_imports_before_executing(self):
        for bytecode in (False, True):
            with self.subTest(bytecode=bytecode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                descriptor = controller_snapshot.create_snapshot(ROOT, root / "control")
                scripts = Path(descriptor["root"]) / "scripts"
                marker = root / "unlisted-module-ran"
                source = root / "payload.py"
                source.write_text(f"open({str(marker)!r}, 'w').close()\nraise SystemExit(0)\n")
                scripts.chmod(0o700)
                if bytecode:
                    injected = Path(importlib.util.cache_from_source(str(scripts / "provider_contract.py")))
                    py_compile.compile(str(source), cfile=str(injected), doraise=True,
                                       invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
                    injected.parent.chmod(0o500)
                else:
                    injected = scripts / "subprocess.py"
                    shutil.copyfile(source, injected)
                injected.chmod(0o400)
                scripts.chmod(0o500)

                with self.assertRaisesRegex(ValueError, "unlisted"):
                    controller_snapshot.validate_launch_snapshot(descriptor)
                self.assertFalse(marker.exists())

    def test_snapshot_error_boundaries_reject_tampering_and_unmanaged_state(self):
        with tempfile.TemporaryDirectory() as directory:
            source = self.source(directory)
            (source / "VERSION").write_text("\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "empty"):
                controller_snapshot.create_snapshot(source, Path(directory) / "control")

            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            for mutation in (
                lambda value: value.update(protocol_version=99),
                lambda value: value.update(files=["../escape"]),
                lambda value: value.update(source_root=value["root"]),
            ):
                invalid = json.loads(json.dumps(descriptor))
                mutation(invalid)
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    controller_snapshot.validate_launch_snapshot(invalid)

            with self.assertRaisesRegex(ValueError, "unreadable"):
                controller_snapshot.managed_state_snapshot(Path(directory) / "missing.json")
            state = Path(directory) / "state.json"
            state.write_text(json.dumps({"schema_version": 11}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "identity"):
                controller_snapshot.managed_state_snapshot(state)

            removable = Path(directory) / "remove"
            (removable / "nested").mkdir(parents=True)
            controller_snapshot.remove_tree(removable)
            self.assertFalse(removable.exists())

        with mock.patch.object(sys, "argv", [str(MODULE_PATH), "validate", "unexpected"]), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(2, controller_snapshot.main())
        self.assertIn("unexpected", stderr.getvalue())
        with mock.patch.object(sys, "argv", [str(MODULE_PATH), "validate"]), \
                mock.patch("sys.stdin", io.StringIO("{")), \
                mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            self.assertEqual(2, controller_snapshot.main())
        self.assertIn("blocked", stderr.getvalue())

    def test_snapshot_rejects_unavailable_version_and_provenance_tampering(self):
        with mock.patch.object(controller_snapshot, "snapshot_files", return_value=()), \
                mock.patch.object(controller_snapshot, "aggregate_fingerprint", return_value="fingerprint"):
            with self.assertRaisesRegex(ValueError, "VERSION is unavailable"):
                controller_snapshot.create_snapshot("/missing", "/tmp/control")

        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            for mutation, message in (
                (lambda value: value.update(control_root=str(Path(directory) / "other")), "provenance"),
                (lambda value: value.update(protocol_version=99), "protocol changed"),
                (lambda value: value.update(package_version="other"), "version changed"),
            ):
                invalid = json.loads(json.dumps(descriptor))
                mutation(invalid)
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, message):
                    controller_snapshot.validate_snapshot(invalid)
            with self.assertRaisesRegex(ValueError, "descriptor"):
                controller_snapshot.validate_launch_snapshot([])

    def test_managed_snapshot_requires_a_frozen_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "state"
            state = {"schema_version": 11, "repo_id": "repo", "task_key": "task", "run_id": "run", "controller": {}}
            path = root / controller_snapshot.hashlib.sha256(b"repo").hexdigest() \
                / controller_snapshot.hashlib.sha256(b"task").hexdigest() \
                / f"{controller_snapshot.hashlib.sha256(b'run').hexdigest()}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(state), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no frozen"):
                controller_snapshot.managed_state_snapshot(path)

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
            self.assertIn("scripts/desktop_task_bridge.py", multi["files"])
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

    def test_extension_normalization_rejects_unknown_duplicate_and_malformed_requests(self):
        self.assertEqual(
            ("autonomy", "autonomy-eval"),
            controller_snapshot.normalize_extensions(("autonomy-eval",)),
        )
        for requested in ("autonomy", ("autonomy", "autonomy"), ("unknown",)):
            with self.subTest(requested=requested), self.assertRaisesRegex(ValueError, "extensions"):
                controller_snapshot.normalize_extensions(requested)
        with self.assertRaisesRegex(ValueError, "descriptor"):
            controller_snapshot.snapshot_extensions([])
        with self.assertRaisesRegex(ValueError, "incomplete"):
            controller_snapshot.aggregate_fingerprint(ROOT, ["missing-file"])

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

    def test_host_evaluation_freezes_the_bridge_and_its_multimodel_dependency(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(
                ROOT, Path(directory) / "control", extensions=("host-eval",)
            )

        self.assertEqual(["multimodel", "host-eval"], descriptor["extensions"])
        self.assertIn("scripts/host_bridge.py", descriptor["files"])
        self.assertIn("scripts/interaction_replay.py", descriptor["files"])
        self.assertIn("scripts/skillopt_adapter.py", descriptor["files"])
        self.assertIn("scripts/multi_model.py", descriptor["files"])

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

    def test_snapshot_recovery_dispatches_through_live_entry_points(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = controller_snapshot.create_snapshot(ROOT, root / "control", ("autonomy", "multimodel"))
            descriptor = root / "snapshot.json"
            descriptor.write_text(json.dumps(snapshot))
            for name, arguments in (
                ("delivery_state.py", ["doctor", "--workspace", "/workspace"]),
                ("delivery_state.py", ["--workspace", "/workspace", "doctor"]),
                ("autonomy_service.py", ["--state", "/managed/state.json"]),
                ("autonomy_service.py", ["--serve", "--state-root", "/managed"]),
            ):
                with self.subTest(name=name):
                    command = controller_snapshot.trusted_command(descriptor, f"scripts/{name}", arguments)
                    self.assertEqual([sys.executable, str(ROOT / "scripts" / name), *arguments], command)

            for flag in ("--frozen-runtime", "--frozen-runt"):
                with self.subTest(flag=flag):
                    arguments = ["--state", "/managed/state.json", flag]
                    command = controller_snapshot.trusted_command(descriptor, "scripts/autonomy_service.py", arguments)
                    self.assertEqual(
                        [sys.executable, str(Path(snapshot["root"]) / "scripts/autonomy_service.py"), *arguments],
                        command,
                    )
            arguments = ["path", "--task-key", "doctor"]
            command = controller_snapshot.trusted_command(descriptor, "scripts/delivery_state.py", arguments)
            self.assertEqual([sys.executable, str(Path(snapshot["root"]) / "scripts/delivery_state.py"), *arguments],
                             command)

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

    def test_frozen_begin_starts_service_from_live_installation_and_keeps_hook_begin_frozen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "suite"
            extensions = ("autonomy", "multimodel")
            for relative in (*controller_snapshot.snapshot_files(ROOT, extensions), "VERSION"):
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            (source / "scripts/autonomy_begin.py").write_text(
                "import subprocess, sys\n"
                "from pathlib import Path\n"
                "def main():\n"
                "    print('frozen begin ' + sys.argv[1], flush=True)\n"
                "    if sys.argv[1] == 'service':\n"
                "        with subprocess.Popen([sys.executable, str(Path(__file__).with_name('autonomy_service.py')),\n"
                "                               '--serve', '--help']) as process:\n"
                "            return process.wait()\n"
                "if __name__ == '__main__':\n"
                "    raise SystemExit(main())\n"
            )
            (source / "scripts/autonomy_service.py").write_text("print('frozen background process')\n")
            snapshot = controller_snapshot.create_snapshot(source, root / "control", extensions)
            descriptor = root / "snapshot.json"
            descriptor.write_text(json.dumps(snapshot))
            for mode in ("service", "hook"):
                with self.subTest(mode=mode):
                    result = subprocess.run([
                        sys.executable, str(MODULE_PATH), "run", "--descriptor", str(descriptor),
                        "--script", "scripts/autonomy_begin.py", "--", mode,
                    ], capture_output=True, text=True, check=False, timeout=10)
                    self.assertEqual(0, result.returncode, result.stderr)
                    self.assertTrue(result.stdout.startswith(f"frozen begin {mode}\n"))
                    self.assertNotIn("frozen background process", result.stdout)
                    if mode == "service":
                        self.assertIn("--state-root", result.stdout)

    def test_saved_recovery_replays_only_the_original_next_check_through_the_live_launcher(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = controller_snapshot.create_snapshot(ROOT, root / "control")
            repo, task, run = "/repo/.git", "task", "run"
            repo_hash, task_hash, run_hash = (controller_snapshot.hashlib.sha256(key.encode()).hexdigest()
                                             for key in (repo, task, run))
            descriptor = root / "state" / repo_hash / task_hash / f"{run_hash}.json"
            descriptor.parent.mkdir(parents=True)
            descriptor.write_text(json.dumps({"schema_version": 11, "repo_id": repo, "task_key": task, "run_id": run,
                                              "controller": {"snapshot": snapshot}}))
            args = ["--state", str(descriptor), "--run-id", "run", "--writer-id", "writer", "--revision", "2"]
            old = ["/old/python", str(Path(snapshot["root"]) / "scripts/controller_snapshot.py"), "run",
                   "--descriptor", str(descriptor), "--script", "scripts/delivery_next.py", "--", *args]
            command = controller_snapshot.replay_next_command(old, lease_root=root / "leases")
            self.assertEqual([sys.executable, str(Path(snapshot["root"]) / "scripts/delivery_next.py"),
                              *args, "--lease-root", str((root / "leases").resolve())], command)
            with_lease = [*old[:10], "--lease-root", str(root / "leases"), *old[10:]]
            self.assertEqual(with_lease[8:], controller_snapshot.replay_next_command(with_lease, lease_root=root / "leases")[2:])
            with self.assertRaisesRegex(ValueError, "different lease root"):
                controller_snapshot.replay_next_command(with_lease, lease_root=root / "other")
            for invalid in ([*old, "--format", "legacy"], [*old[:6], "scripts/delivery_state.py", *old[7:]],
                            [*old[:9], str(root / "other.json"), *old[10:]]):
                with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "saved next_command"):
                    controller_snapshot.replay_next_command(invalid)
            descriptor.write_text(json.dumps(snapshot))
            with self.assertRaisesRegex(ValueError, "managed state identity"):
                controller_snapshot.replay_next_command(old)
            payload = {"schema_version": 11, "repo_id": repo, "task_key": task, "run_id": run,
                       "controller": {"snapshot": snapshot}}
            with mock.patch.object(Path, "read_text", return_value=json.dumps(payload)), \
                    self.assertRaisesRegex(ValueError, "must be the managed state path"):
                controller_snapshot.managed_state_snapshot("/state.json")

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

    def legacy_descriptor(self, directory, profile="extended"):
        control = Path(directory) / "control"
        temporary = control / "temporary"
        if profile == "core":
            controller_files = list(controller_snapshot.CORE_CONTROLLER_FILES)
            controller_files[controller_files.index("scripts/runner_contract.py"):controller_files.index("scripts/runner_contract.py")] = (
                "scripts/runner_launch.py", "scripts/runner_lifecycle.py",
                "scripts/codex_exec_runner.py", "scripts/claude_exec_runner.py",
            )
            resource_files = controller_snapshot.CORE_CONTROL_RESOURCE_FILES
        else:
            controller_files = controller_snapshot.EXTENDED_CONTROLLER_FILES
            resource_files = controller_snapshot.EXTENDED_CONTROL_RESOURCE_FILES
        files = [*controller_files, *resource_files, *controller_snapshot.provider_files(ROOT)]
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
            "profile": profile, "files": files,
        }

    def legacy_v17_descriptor(self, directory, extensions=(), include_runner_lifecycle=True):
        control = Path(directory) / "control"
        temporary = control / "temporary"
        files = list(controller_snapshot.CORE_CONTROLLER_FILES)
        if include_runner_lifecycle:
            files[files.index("scripts/runner_contract.py"):files.index("scripts/runner_contract.py")] = (
                "scripts/runner_launch.py", "scripts/runner_lifecycle.py",
                "scripts/codex_exec_runner.py", "scripts/claude_exec_runner.py",
            )
        resources = list(controller_snapshot.CORE_CONTROL_RESOURCE_FILES)
        extensions = controller_snapshot.normalize_extensions(extensions)
        for extension in extensions:
            extension_files, extension_resources = controller_snapshot.EXTENSIONS[extension]
            files.extend(extension_files)
            resources.extend(extension_resources)
        files = [*dict.fromkeys(files), *dict.fromkeys(resources), *controller_snapshot.provider_files(ROOT)]
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
            "protocol_version": 17, "protocol_fingerprint": fingerprint,
            "extensions": list(extensions), "files": files,
        }

    def test_legacy_v17_core_descriptor_remains_valid_for_managed_state_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = self.legacy_v17_descriptor(directory)
            state = Path(directory) / "state"
            path = state / controller_snapshot.hashlib.sha256(b"repo").hexdigest() \
                / controller_snapshot.hashlib.sha256(b"task").hexdigest() \
                / f"{controller_snapshot.hashlib.sha256(b'run').hexdigest()}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema_version": 11, "repo_id": "repo", "task_key": "task", "run_id": "run",
                "controller": {"snapshot": descriptor},
            }), encoding="utf-8")

            self.assertEqual(descriptor, controller_snapshot.managed_state_snapshot(path))
            self.assertEqual(17, controller_identity(snapshot=descriptor)["protocol_version"])

    def test_transitional_v17_core_descriptor_remains_valid_for_managed_state_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = self.legacy_v17_descriptor(directory, include_runner_lifecycle=False)
            state = Path(directory) / "state"
            path = state / controller_snapshot.hashlib.sha256(b"repo").hexdigest() \
                / controller_snapshot.hashlib.sha256(b"task").hexdigest() \
                / f"{controller_snapshot.hashlib.sha256(b'run').hexdigest()}.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "schema_version": 11, "repo_id": "repo", "task_key": "task", "run_id": "run",
                "controller": {"snapshot": descriptor},
            }), encoding="utf-8")

            self.assertEqual(descriptor, controller_snapshot.managed_state_snapshot(path))

    def test_legacy_v17_descriptor_ignores_later_surface_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = self.legacy_v17_descriptor(directory, ("multimodel",))
            extensions = dict(controller_snapshot.EXTENSIONS)
            files, resources = extensions["multimodel"]
            extensions["multimodel"] = (
                (*files, "scripts/future_multimodel_runner.py"),
                (*resources, "references/future-multimodel.md"),
            )
            dependencies = dict(controller_snapshot.EXTENSION_DEPENDENCIES)
            dependencies["multimodel"] = ("autonomy",)
            with mock.patch.object(
                    controller_snapshot, "CORE_CONTROL_RESOURCE_FILES",
                    (*controller_snapshot.CORE_CONTROL_RESOURCE_FILES, "references/future-core.md")), \
                    mock.patch.object(controller_snapshot, "EXTENSIONS", extensions), \
                    mock.patch.object(controller_snapshot, "EXTENSION_DEPENDENCIES", dependencies):
                self.assertEqual(descriptor, controller_snapshot.validate_snapshot(descriptor))
                self.assertEqual(("multimodel",), controller_snapshot.snapshot_extensions(descriptor))

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

    def test_legacy_v16_core_descriptor_can_launch_its_frozen_helper(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = self.legacy_descriptor(directory, profile="core")
            descriptor_path = Path(directory) / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor), encoding="utf-8")

            command = controller_snapshot.trusted_command(
                descriptor_path, "scripts/delivery_engine.py", ["select"]
            )

            self.assertEqual(sys.executable, command[0])
            self.assertEqual(str(Path(descriptor["root"]) / "scripts/delivery_engine.py"), command[1])

    def test_frozen_host_eval_adds_proxy_only_to_the_legacy_app_server_launch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "suite"
            evaluator = "skills/converge-eval/scripts/eval_contract.py"
            for relative in (*controller_snapshot.snapshot_files(ROOT, ("host-eval",)), "VERSION"):
                target = source / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            (source / "scripts/host_bridge.py").write_text(
                "import subprocess\n"
                "def launch(binary, *args):\n"
                "    with subprocess.Popen([binary, *args], stdout=subprocess.PIPE, text=True) as process:\n"
                "        return process.communicate()[0].strip()\n"
            )
            (source / evaluator).write_text(
                "import json, subprocess, sys\n"
                "from pathlib import Path\n"
                "sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))\n"
                "from host_bridge import launch\n"
                "args = ('app-server', '--stdio')\n"
                "flag = ('-c', 'features.respect_system_proxy=true')\n"
                "binary = sys.argv[1]\n"
                "print(json.dumps([launch(binary, *args), launch(binary, *args, *flag),\n"
                "                  launch(binary, 'app-server', 'generate-json-schema'),\n"
                "                  subprocess.check_output([binary, *args], text=True).strip()]))\n"
            )
            descriptor = controller_snapshot.create_snapshot(source, root / "control", extensions=("host-eval",))
            descriptor_path = root / "snapshot.json"
            descriptor_path.write_text(json.dumps(descriptor))
            result = subprocess.run([
                sys.executable, str(MODULE_PATH), "run", "--descriptor", str(descriptor_path),
                "--script", evaluator, "--", "/bin/echo",
            ], capture_output=True, text=True, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            expected = "app-server --stdio -c features.respect_system_proxy=true"
            self.assertEqual([expected, expected, "app-server generate-json-schema", "app-server --stdio"],
                             json.loads(result.stdout))
            self.assertEqual(descriptor, controller_snapshot.validate_launch_snapshot(descriptor))

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
        for relative in set((*controller_snapshot.CORE_CONTROLLER_FILES, *controller_snapshot.EXTENDED_CONTROLLER_FILES,
                             *controller_snapshot.AUTONOMY_CONTROLLER_FILES)):
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"{relative}\n", encoding="utf-8")
        for relative in controller_snapshot.PROVIDER_FILES:
            path = source / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}\n", encoding="utf-8")
        for relative in set((*controller_snapshot.CORE_CONTROL_RESOURCE_FILES,
                             *controller_snapshot.EXTENDED_CONTROL_RESOURCE_FILES)):
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
            self.assertTrue((Path(descriptor["root"]) / "scripts/native_tdd_policy.py").is_file())
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
            self.assertTrue((Path(descriptor["root"]) / "scripts/desktop_task_bridge.py").is_file())
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
            self.assertIn("scripts/native_tdd_policy.py", descriptor["files"])
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

    def test_core_snapshot_omits_the_multimodel_runner_lifecycle(self):
        with tempfile.TemporaryDirectory() as directory:
            descriptor = controller_snapshot.create_snapshot(ROOT, Path(directory) / "control")
            snapshot = Path(descriptor["root"])
            for name in (
                "runner_launch.py", "runner_lifecycle.py", "codex_exec_runner.py", "claude_exec_runner.py",
            ):
                self.assertFalse((snapshot / "scripts" / name).exists())
            self.assertFalse((snapshot / "scripts/multi_model.py").exists())
            self.assertFalse((snapshot / "scripts/openai_compatible_runner.py").exists())
            result = subprocess.run(
                [sys.executable, "-c", "import trigger_eval"], cwd=snapshot / "scripts",
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)

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
            descriptor["protocol_version"] = 16
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

    def test_snapshot_helpers_normalize_dependencies_and_reject_invalid_extensions(self):
        self.assertEqual(("autonomy", "autonomy-eval"), controller_snapshot.normalize_extensions(
            ("autonomy-eval",)
        ))
        self.assertEqual(("multimodel",), controller_snapshot.normalize_extensions(["multimodel"]))
        with self.assertRaisesRegex(ValueError, "extensions"):
            controller_snapshot.normalize_extensions(["multimodel", "multimodel"])
        with self.assertRaisesRegex(ValueError, "descriptor"):
            controller_snapshot.snapshot_extensions({"profile": "unknown"})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, "incomplete"):
                controller_snapshot.aggregate_fingerprint(root, ["missing"])
            descriptor = controller_snapshot.descriptor(root, "a" * 64, "1.0", files=["x"], extensions=())
            self.assertEqual([], descriptor["extensions"])
            self.assertEqual(["x"], descriptor["files"])


if __name__ == "__main__":
    unittest.main()
