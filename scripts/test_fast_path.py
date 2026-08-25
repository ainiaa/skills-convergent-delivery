#!/usr/bin/env python3
"""Regression tests for the deterministic fast-path eligibility receipt."""

import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from fast_path import validate_fast_path


SCRIPT = ROOT / "scripts" / "fast_path.py"


class FastPathTest(unittest.TestCase):
    def test_rejects_every_generic_fast_path_request(self):
        with self.assertRaisesRegex(ValueError, "formatter-specific"):
            validate_fast_path(object(), object(), object(), object())

    def test_cli_blocks_without_evaluating_the_workspace_or_check_command(self):
        blocked = subprocess.run([sys.executable, str(SCRIPT)], text=True, capture_output=True, check=False)
        self.assertEqual(2, blocked.returncode)
        self.assertIn("formatter-specific", blocked.stderr)

if __name__ == "__main__":
    unittest.main()
