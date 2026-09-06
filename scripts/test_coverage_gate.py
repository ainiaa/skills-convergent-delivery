"""Run the existing gate unchanged while pytest-cov measures its child processes."""
from pathlib import Path
import unittest

from evidence_contract import _run_command


ROOT = Path(__file__).resolve().parents[1]
GATE_TIMEOUT_SECONDS = 900


class CoverageGateTest(unittest.TestCase):
    def test_full_gate(self):
        exit_code, stdout, stderr = _run_command(
            ROOT, ['bash', 'scripts/check.sh', '--full'], GATE_TIMEOUT_SECONDS,
        )
        output = (stdout + stderr).decode('utf-8', 'replace')
        self.assertEqual(0, exit_code, output)
        self.assertIn('All checks passed.', output)
