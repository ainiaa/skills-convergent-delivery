import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autonomy_service_config


ROOT = Path(__file__).parent.parent


class AutonomyServiceConfigTest(unittest.TestCase):

    def test_service_uses_the_interpreter_that_installed_it(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            with patch.object(autonomy_service_config.Path, "home", return_value=home), \
                    patch.object(autonomy_service_config.subprocess, "run"), \
                    patch.object(sys, "argv", ["autonomy_service_config.py", "--source", str(ROOT)]):
                self.assertEqual(0, autonomy_service_config.main())

            with (home / "Library/LaunchAgents/com.convergent-delivery.autonomy.plist").open("rb") as file:
                payload = plistlib.load(file)

        self.assertEqual(
            [sys.executable, str(ROOT / "scripts/autonomy_service.py"), "--serve"],
            payload["ProgramArguments"],
        )


if __name__ == "__main__":
    unittest.main()
