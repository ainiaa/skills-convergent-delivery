"""Run the existing gate unchanged while pytest-cov measures its child processes."""
from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CoverageGateTest(unittest.TestCase):
    def test_full_gate(self):
        result = subprocess.run(['bash', 'scripts/check.sh', '--full'], cwd=ROOT,
                                text=True, capture_output=True, timeout=900)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn('All checks passed.', result.stdout)
