import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SKILL_SOURCES = {
    "converge": ROOT,
    "converge-review": ROOT / "skills/converge-review",
    "converge-batch": ROOT / "skills/converge-batch",
}


class InstallTest(unittest.TestCase):
    def run_installer_from(self, home, source, *arguments):
        environment = os.environ | {"HOME": str(home)}
        return subprocess.run(
            ["bash", str(INSTALLER), "--source", str(source), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def run_installer(self, home, *arguments):
        return self.run_installer_from(home, ROOT, *arguments)

    def test_install_version_and_uninstall_for_both_runtimes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = self.run_installer(home, "--target", "all")
            self.assertEqual(0, result.returncode, result.stderr)

            for runtime in ("codex", "claude"):
                for name, source in SKILL_SOURCES.items():
                    target = home / f".{runtime}/skills/{name}"
                    self.assertTrue(target.is_symlink(), target)
                    self.assertEqual(source, target.resolve())

            result = self.run_installer(home, "--version", "--offline")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"Codex:       {VERSION}", result.stdout)
            self.assertIn(f"Claude Code: {VERSION}", result.stdout)

            result = self.run_installer(home, "--uninstall", "--target", "all")
            self.assertEqual(0, result.returncode, result.stderr)
            for runtime in ("codex", "claude"):
                for name in SKILL_SOURCES:
                    target = home / f".{runtime}/skills/{name}"
                    self.assertFalse(target.exists() or target.is_symlink())

    def test_install_refuses_to_replace_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / ".codex/skills/converge"
            target.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(target.is_dir())
            self.assertIn("refusing to replace existing directory", result.stderr)

    def test_install_preflights_the_whole_suite_before_creating_links(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            conflict = home / ".codex/skills/converge-batch"
            conflict.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(conflict.is_dir())
            for name in ("converge", "converge-review"):
                target = home / f".codex/skills/{name}"
                self.assertFalse(target.exists() or target.is_symlink())

    def test_suite_conflict_does_not_migrate_the_legacy_install(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            legacy = home / ".codex/skills/convergent-delivery"
            legacy.parent.mkdir(parents=True)
            legacy.symlink_to(ROOT)
            conflict = home / ".codex/skills/converge-batch"
            conflict.mkdir()

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(legacy.is_symlink())
            self.assertEqual(ROOT, legacy.resolve())

    def test_install_rejects_a_suite_missing_mandatory_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            source = root / "source"
            for path in (
                source / "SKILL.md",
                source / "VERSION",
                source / "skills/converge-review/SKILL.md",
                source / "skills/converge-batch/SKILL.md",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("0.7.0\n" if path.name == "VERSION" else "---\nname: test\n---\n")

            result = self.run_installer_from(home, source, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("mandatory Suite file", result.stderr)
            self.assertFalse((home / ".codex/skills/converge").exists())

    def test_install_refuses_when_another_install_is_in_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            lock = home / ".convergent-delivery/.install.lock"
            lock.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("another installation is in progress", result.stderr)

    def test_install_migrates_known_legacy_skill_links(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for runtime in ("codex", "claude"):
                legacy = home / f".{runtime}/skills/convergent-delivery"
                legacy.parent.mkdir(parents=True)
                legacy.symlink_to(ROOT)

            result = self.run_installer(home, "--target", "all")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse((home / ".codex/skills/convergent-delivery").exists())
            self.assertFalse((home / ".claude/skills/convergent-delivery").exists())
            self.assertTrue((home / ".codex/skills/converge").is_symlink())
            self.assertTrue((home / ".claude/skills/converge").is_symlink())

    def test_install_backs_up_a_known_legacy_skill_directory_before_replacing_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            legacy = home / ".codex/skills/convergent-delivery"
            legacy.mkdir(parents=True)
            (legacy / "SKILL.md").write_text(
                "---\nname: convergent-delivery\ndescription: legacy\n---\n", encoding="utf-8"
            )

            result = self.run_installer(home, "--target", "codex")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((home / ".codex/skills/converge").is_symlink())
            self.assertFalse(legacy.exists())
            backups = list((home / ".convergent-delivery/legacy-backups").rglob("SKILL.md"))
            self.assertEqual(1, len(backups))

    def test_readme_current_version_matches_version_file(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(f"当前开发版本：[{VERSION}](VERSION)", readme)

    def test_readme_links_to_the_usage_guide_and_changelog(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        self.assertTrue((ROOT / "docs/usage-guide.md").is_file())
        self.assertTrue((ROOT / "CHANGELOG.md").is_file())
        self.assertIn("[使用与维护指南](docs/usage-guide.md)", readme)
        self.assertIn("[变更日志](CHANGELOG.md)", readme)
        self.assertIn("## [Unreleased]", changelog)

    def test_public_project_documents_are_linked_from_readme(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for name in ("LICENSE", "CONTRIBUTING.md", "SECURITY.md"):
            self.assertTrue((ROOT / name).is_file(), name)
            self.assertIn(f"]({name})", readme)
        self.assertIn("## 3 步快速开始", readme)
        self.assertIn("前置条件", (ROOT / "docs/usage-guide.md").read_text(encoding="utf-8"))

    def test_readme_documents_explicit_and_keyword_triggers_for_both_runtimes(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("## 调用当前 Skill", readme)
        self.assertIn("$converge", readme)
        self.assertIn("/converge", readme)
        self.assertIn("### 关键词触发", readme)
        self.assertIn("按闭环开发", readme)
        self.assertIn("不要反复确认", readme)

    def test_documentation_uses_shared_state_and_strict_resume_identity(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        usage = (ROOT / "docs/usage-guide.md").read_text(encoding="utf-8")

        self.assertIn("--writer-id <writer-id>", readme)
        self.assertIn("--revision <revision>", readme)
        self.assertIn("~/.convergent-delivery/state/", usage)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("pdlc-v1", skill)
        self.assertIn("native-v1", skill)


if __name__ == "__main__":
    unittest.main()
