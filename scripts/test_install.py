import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
SKILL_SOURCES = {
    "converge": ROOT,
    "converge-plan": ROOT / "skills/converge-plan",
    "converge-review": ROOT / "skills/converge-review",
    "converge-batch": ROOT / "skills/converge-batch",
    "converge-eval": ROOT / "skills/converge-eval",
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

    def run_installer_without_source(self, home, *arguments):
        return subprocess.run(
            ["bash", str(INSTALLER), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=os.environ | {"HOME": str(home)},
        )

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

    def test_version_and_doctor_detect_an_incomplete_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            root = home / ".claude/skills/converge"
            root.parent.mkdir(parents=True)
            root.symlink_to(ROOT)

            version = self.run_installer(home, "--version", "--offline")
            doctor = self.run_installer(home, "--doctor", "--target", "claude", "--offline")

            self.assertEqual(0, version.returncode, version.stderr)
            self.assertIn(f"Claude Code: {VERSION} (incomplete", version.stdout)
            self.assertIn("converge-review", version.stdout)
            self.assertIn("converge-batch", version.stdout)
            self.assertIn("converge-plan", version.stdout)
            self.assertNotEqual(0, doctor.returncode)
            self.assertIn("Suite: incomplete", doctor.stdout)
            self.assertIn("Repair:", doctor.stdout)

    def test_doctor_accepts_a_complete_suite(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            installed = self.run_installer(home, "--target", "codex")
            doctor = self.run_installer_without_source(
                home, "--doctor", "--target", "codex", "--offline"
            )

            self.assertEqual(0, installed.returncode, installed.stderr)
            self.assertEqual(0, doctor.returncode, doctor.stderr)
            self.assertIn("Suite: complete", doctor.stdout)
            self.assertIn("Python:", doctor.stdout)
            self.assertIn("Provider:", doctor.stdout)
            self.assertIn("Activation:", doctor.stdout)
            self.assertIn("$converge", doctor.stdout)
            self.assertIn("AGENTS.md", doctor.stdout)
            self.assertNotIn('"binding"', doctor.stdout)

    def test_version_and_doctor_reject_a_linked_suite_with_missing_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            source = root / "partial-source"
            (source / "skills/converge-review").mkdir(parents=True)
            (source / "skills/converge-batch").mkdir(parents=True)
            (source / "SKILL.md").write_text("---\nname: converge\n---\n", encoding="utf-8")
            (source / "VERSION").write_text(VERSION + "\n", encoding="utf-8")
            (source / "skills/converge-plan").mkdir(parents=True)
            for name in ("converge-plan", "converge-review", "converge-batch"):
                (source / f"skills/{name}/SKILL.md").write_text(
                    f"---\nname: {name}\n---\n", encoding="utf-8"
                )
                target = home / f".codex/skills/{name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(source / f"skills/{name}")
            (home / ".codex/skills/converge").symlink_to(source)

            version = self.run_installer(home, "--version", "--offline")
            doctor = self.run_installer(home, "--doctor", "--target", "codex", "--offline")

            self.assertIn("incomplete", version.stdout)
            self.assertNotEqual(0, doctor.returncode)
            self.assertIn("Suite: incomplete", doctor.stdout)

    def test_doctor_runs_the_installed_engine_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            source = root / "installed-source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git", ".claude", ".codex", ".codegraph", "__pycache__", "25761b*"
                ),
            )
            (source / "scripts/delivery_engine.py").write_text(
                "print('engine failed after partial output')\nraise SystemExit(2)\n",
                encoding="utf-8",
            )
            for name, relative in (
                ("converge", "."),
                ("converge-plan", "skills/converge-plan"),
                ("converge-review", "skills/converge-review"),
                ("converge-batch", "skills/converge-batch"),
            ):
                target = home / f".codex/skills/{name}"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to((source / relative).resolve())

            doctor = self.run_installer_without_source(
                home, "--doctor", "--target", "codex", "--offline"
            )

            self.assertNotEqual(0, doctor.returncode)
            self.assertIn("Provider: engine failed after partial output", doctor.stdout)

    def test_install_refuses_to_replace_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / ".codex/skills/converge"
            target.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(target.is_dir())
            self.assertIn("refusing to replace existing directory", result.stderr)

    def test_upgrade_replaces_an_existing_managed_skill_link(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            old_source = home / "old-converge"
            old_source.mkdir()
            (old_source / "SKILL.md").write_text(
                "---\nname: converge\n---\n", encoding="utf-8"
            )
            target = home / ".codex/skills/converge"
            target.parent.mkdir(parents=True)
            target.symlink_to(old_source)

            result = self.run_installer(home, "--upgrade", "--target", "codex")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(ROOT, target.resolve())

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
                source / "skills/converge-plan/SKILL.md",
                source / "skills/converge-review/SKILL.md",
                source / "skills/converge-batch/SKILL.md",
            ):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("0.7.0\n" if path.name == "VERSION" else "---\nname: test\n---\n")

            result = self.run_installer_from(home, source, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("mandatory Suite file", result.stderr)
            self.assertFalse((home / ".codex/skills/converge").exists())

    def test_install_rejects_a_suite_missing_review_orchestration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            source = root / "source"
            shutil.copytree(
                ROOT,
                source,
                ignore=shutil.ignore_patterns(
                    ".git", ".claude", ".codex", ".codegraph", "__pycache__"
                ),
            )
            (source / "references/review-orchestration.md").unlink()

            result = self.run_installer_from(home, source, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("references/review-orchestration.md", result.stderr)
            self.assertFalse((home / ".codex/skills/converge").exists())

    def test_install_refuses_when_another_install_is_in_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            lock = home / ".convergent-delivery/.install.lock"
            lock.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("another installation is in progress", result.stderr)

    def test_install_recovers_a_stale_install_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            lock = home / ".convergent-delivery/.install.lock"
            lock.mkdir(parents=True)
            (lock / "pid").write_text("999999999\n", encoding="utf-8")

            result = self.run_installer(home, "--target", "codex")

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue((home / ".codex/skills/converge-eval").is_symlink())

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
        self.assertNotIn("三个 Skill", changelog)
        self.assertNotIn("三个入口", changelog)

    def test_readme_puts_newcomer_install_and_skill_choice_before_the_overview(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertLess(readme.index("## 3 步快速开始"), readme.index("## 为什么会有它"))
        for marker in (
            "bash install.sh --target all",
            "重启或刷新", "不确定时，先用 `converge`",
            "`converge-plan`", "`converge-review`", "`converge-batch`", "`converge-eval`",
        ):
            self.assertIn(marker, readme)

    def test_readme_introduces_opt_in_multi_model_workflow_and_its_boundary(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for marker in (
            "## 多模型协作", "使用多模型配合开发", "默认不启用",
            "Sol high", "Luna max", "Terra xhigh", "[多模型协作](references/multi-model.md)",
            "不能替代真实测试",
        ):
            self.assertIn(marker, readme)

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
