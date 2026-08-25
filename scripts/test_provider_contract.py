import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("provider_contract.py")
SPEC = importlib.util.spec_from_file_location("provider_contract", MODULE_PATH)
provider_contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(provider_contract)


class ProviderContractTest(unittest.TestCase):
    def fixture(self, directory):
        root = Path(directory) / "provider"
        (root / "skills/demo").mkdir(parents=True)
        (root / "skills/demo/SKILL.md").write_text("entry\n", encoding="utf-8")
        (root / "skills/demo/REFERENCE.md").write_text("closure\n", encoding="utf-8")
        manifest = {
            "schema_version": 2,
            "provider": {"id": "demo-v1", "source_id": "demo/source", "version": "1", "role": "workflow"},
            "capabilities": {"task_kinds": ["feature"], "stages": ["tdd", "implement", "review"]},
            "task_contracts": {"feature": {"entrypoint": "demo/SKILL.md", "closure": ["demo/REFERENCE.md"], "preserve_external_behavior": False}},
            "authorization": {"stop_for": ["business_rules", "public_contracts", "permissions", "release", "irreversible_actions"], "forbidden_actions": ["commit", "tag", "push", "publish", "install"]},
            "outputs": {"progress_protocol": 1, "required_evidence": ["tests"]},
        }
        digest = hashlib.sha256()
        for relative in ("demo/SKILL.md", "demo/REFERENCE.md"):
            digest.update(relative.encode("utf-8") + b"\0" + (root / "skills" / relative).read_bytes())
        manifest["task_contracts"]["feature"]["source_fingerprint"] = digest.hexdigest()
        path = root / "manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return root, path, manifest

    def test_binding_freezes_manifest_task_contract_entrypoint_and_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path, manifest = self.fixture(directory)
            reference = provider_contract.build_reference(manifest, path, "feature", root)

        self.assertEqual("demo-v1", reference["id"])
        self.assertEqual(64, len(reference["contract_fingerprint"]))
        self.assertEqual(2, len(reference["sources"]))
        self.assertEqual("entrypoint", reference["sources"][0]["kind"])
        self.assertEqual("closure", reference["sources"][1]["kind"])

    def test_any_frozen_source_or_task_contract_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path, manifest = self.fixture(directory)
            reference = provider_contract.build_reference(manifest, path, "feature", root)
            provider_contract.validate_reference(reference, "feature")

            (root / "skills/demo/REFERENCE.md").write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "source.*changed"):
                provider_contract.validate_reference(reference, "feature")

            (root / "skills/demo/REFERENCE.md").write_text("closure\n", encoding="utf-8")
            changed = copy.deepcopy(manifest)
            changed["task_contracts"]["feature"]["preserve_external_behavior"] = True
            path.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest.*changed"):
                provider_contract.validate_reference(reference, "feature")

    def test_workflow_reference_must_match_the_contract_source_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path, manifest = self.fixture(directory)
            (root / "skills/demo/SKILL.md").write_text("forged entry\n", encoding="utf-8")
            reference = provider_contract.build_reference(manifest, path, "feature", root)

            with self.assertRaisesRegex(ValueError, "source fingerprint"):
                provider_contract.validate_reference(reference, "feature")

    def test_declared_entrypoint_cannot_be_replaced_by_an_unrelated_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root, path, manifest = self.fixture(directory)
            reference = provider_contract.build_reference(manifest, path, "feature", root)
            replacement = Path(directory) / "unrelated"
            replacement.write_text("not the provider entrypoint\n", encoding="utf-8")
            reference["sources"][0]["path"] = str(replacement.resolve())
            reference["sources"][0]["fingerprint"] = hashlib.sha256(
                replacement.read_bytes()
            ).hexdigest()

            with self.assertRaisesRegex(ValueError, "entrypoint|source"):
                provider_contract.validate_reference(reference, "feature")

    def test_stage_provider_cannot_drop_its_only_real_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "generic-tdd/SKILL.md"
            source.parent.mkdir(parents=True)
            source.write_text("test first red green\n", encoding="utf-8")
            manifest = {
                "provider": {"id": "generic", "version": "1", "role": "stage"},
                "task_contracts": {"feature": {"required_terms": ["test first", "red", "green"]}},
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            reference = provider_contract.build_reference(
                manifest, manifest_path, "feature", source_path=source
            )
            reference["sources"] = []

            with self.assertRaisesRegex(ValueError, "source"):
                provider_contract.validate_reference(reference, "feature", "stage")

    def test_generic_stage_source_is_rechecked_when_the_binding_is_resumed(self):
        manifest_path = MODULE_PATH.parent.parent / "providers/generic-tdd-v1.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            for content in ("ordinary documentation\n", "test first red green then publish\n"):
                with self.subTest(content=content):
                    source = Path(directory) / "SKILL.md"
                    source.write_text(content, encoding="utf-8")
                    reference = provider_contract.build_reference(
                        manifest, manifest_path, "feature", source_path=source
                    )

                    with self.assertRaisesRegex(ValueError, "stage provider source"):
                        provider_contract.validate_reference(
                            reference, "feature", "stage"
                        )


if __name__ == "__main__":
    unittest.main()
