import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install.sh"
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()


class InstallTest(unittest.TestCase):
    def run_installer(self, home, *arguments):
        environment = os.environ | {"HOME": str(home)}
        return subprocess.run(
            ["bash", str(INSTALLER), "--source", str(ROOT), *arguments],
            text=True,
            capture_output=True,
            check=False,
            env=environment,
        )

    def test_install_version_and_uninstall_for_both_runtimes(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            result = self.run_installer(home, "--target", "all")
            self.assertEqual(0, result.returncode, result.stderr)

            codex = home / ".codex/skills/convergent-delivery"
            claude = home / ".claude/skills/convergent-delivery"
            self.assertTrue(codex.is_symlink())
            self.assertTrue(claude.is_symlink())
            self.assertEqual(ROOT, codex.resolve())
            self.assertEqual(ROOT, claude.resolve())

            result = self.run_installer(home, "--version", "--offline")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertIn(f"Codex:       {VERSION}", result.stdout)
            self.assertIn(f"Claude Code: {VERSION}", result.stdout)

            result = self.run_installer(home, "--uninstall", "--target", "all")
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertFalse(codex.exists() or codex.is_symlink())
            self.assertFalse(claude.exists() or claude.is_symlink())

    def test_install_refuses_to_replace_an_existing_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / ".codex/skills/convergent-delivery"
            target.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertTrue(target.is_dir())
            self.assertIn("refusing to replace existing directory", result.stderr)

    def test_install_refuses_when_another_install_is_in_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            lock = home / ".convergent-delivery/.install.lock"
            lock.mkdir(parents=True)

            result = self.run_installer(home, "--target", "codex")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("another installation is in progress", result.stderr)

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


if __name__ == "__main__":
    unittest.main()
