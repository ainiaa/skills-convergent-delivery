import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomy_service_config


ROOT = Path(__file__).parent.parent


class AutonomyServiceConfigTest(unittest.TestCase):

    def test_service_install_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(autonomy_service_config.Path, "home", return_value=home), \
                    patch.object(sys, "argv", ["autonomy_service_config.py", "--source", str(ROOT)]):
                with self.assertRaisesRegex(ValueError, "no longer supported"):
                    autonomy_service_config.main()
        self.assertFalse((home / "Library/LaunchAgents").exists())

    def test_remove_clears_the_plist_and_ignores_bootout_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            target = home / "Library/LaunchAgents/com.convergent-delivery.autonomy.plist"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"<plist></plist>")
            with patch.object(autonomy_service_config.Path, "home", return_value=home), \
                    patch.object(autonomy_service_config.subprocess, "run") as launchctl, \
                    patch.object(sys, "argv", ["autonomy_service_config.py", "--source", str(ROOT), "--remove"]):
                self.assertEqual(0, autonomy_service_config.main())
        self.assertFalse(target.exists())
        self.assertEqual(["launchctl"], [call.args[0][0] for call in launchctl.call_args_list])

    def test_cli_remove_runs_from_a_host_shell(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / "home"
            shim = Path(directory) / "bin"
            shim.mkdir()
            launchctl = shim / "launchctl"
            launchctl.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            launchctl.chmod(0o755)
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/autonomy_service_config.py"),
                 "--source", str(ROOT), "--remove"],
                text=True, capture_output=True, check=False,
                env=os.environ | {"HOME": str(home), "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
            )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
