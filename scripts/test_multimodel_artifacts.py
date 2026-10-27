"""Exercise file delivery and evidence ingestion across the real result boundary."""
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from multi_model import resolve
from role_result import prompt_for_role
from runner_contract import freeze_launch, validate_recovery_launch
from runner_lifecycle import _completed_execution
from test_multimodel_recovery import receipt


class MultiModelArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.artifact = self.root / 'prd.md'
        self.artifact.write_text('# PRD\n' + '完整的产品规则与验收。\n' * 100)
        profile = resolve(None, workspace=self.root, home=self.root / 'home')['roles']['scout']
        self.launch = freeze_launch(profile, 'Inspect prd.md', {'workspace': str(self.root)})

    def finish(self, *, summary='The artifact covers the requested workflow.', reference='prd.md',
               kind='artifact', digest=None):
        payload = {'findings': [{'summary': summary, 'evidence': [{
            'kind': kind, 'reference': reference,
            'content_fingerprint': digest or hashlib.sha256(self.artifact.read_bytes()).hexdigest(),
        }]}], 'next_action': 'verify'}
        return _completed_execution(self.launch, {
            'receipt': receipt(self.launch),
            'output': {'status': 'available', 'content': json.dumps(payload)},
        })

    def test_long_artifact_is_delivered_as_file_with_short_verified_observation(self):
        self.assertGreater(self.artifact.stat().st_size, 300)
        observed, result = self.finish()
        self.assertEqual('completed', observed['status'])
        self.assertEqual('available', result['status'])
        self.assertNotIn(self.artifact.read_text(), json.dumps(observed))
        self.assertEqual('available', self.finish(kind='file', reference='prd.md:101')[1]['status'])

    def test_reused_hash_missing_file_and_nonexistent_line_are_not_accepted(self):
        (self.root / 'other.md').write_text('Different bytes\n')
        for kwargs in ({'digest': '0' * 64}, {'reference': 'other.md'},
                       {'reference': 'missing.md'}, {'kind': 'file', 'reference': 'prd.md:102'}):
            with self.subTest(kwargs=kwargs):
                observed, result = self.finish(**kwargs)
                self.assertEqual('completed', observed['status'])
                self.assertEqual('invalid', result['status'])
                self.assertEqual('evidence_mismatch', result['reason'])

    def test_summary_boundary_reports_length_without_truncating_or_reusing_output(self):
        self.assertEqual('available', self.finish(summary='界' * 300)[1]['status'])
        for size in (301, 304, 7190):
            with self.subTest(size=size):
                result = self.finish(summary='界' * size)[1]
                self.assertEqual('invalid_contract', result['reason'])
                self.assertIn(str(size), result['diagnostic'])
                self.assertIn('300', result['diagnostic'])

    def test_symlink_escape_and_directory_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            target = Path(outside) / 'secret.md'
            target.write_text('outside\n')
            (self.root / 'escape').symlink_to(outside, target_is_directory=True)
            for reference in ('escape/secret.md', '.'):
                with self.subTest(reference=reference):
                    self.assertEqual('invalid', self.finish(reference=reference)[1]['status'])

    def test_readonly_prompt_uses_observation_instead_of_document_authoring(self):
        prompt = prompt_for_role('scout', 'Inspect prd.md')
        self.assertIn('160', prompt)
        self.assertIn('complete documents', prompt)
        self.assertIn('whole file', prompt)

    def test_evidence_failure_cannot_be_retried_as_a_format_correction(self):
        observed, result = self.finish(digest='0' * 64)
        retry = freeze_launch(self.launch['profile'], 'Shorter format', {
            **self.launch['configuration'], 'recovery_of': self.launch['launch_fingerprint'],
        })
        with self.assertRaisesRegex(ValueError, 'format recovery'):
            validate_recovery_launch(retry, [self.launch], [observed])

    def test_nonlocal_claims_are_never_executed_and_large_or_empty_files_fail(self):
        for kind, reference in [('command', 'touch dangerous'), ('url', 'https://example.com')]:
            self.assertEqual('available', self.finish(kind=kind, reference=reference)[1]['status'])
        self.assertFalse((self.root / 'dangerous').exists())
        self.artifact.write_bytes(b'')
        self.assertEqual('invalid', self.finish(kind='file', reference='prd.md:1')[1]['status'])
        self.artifact.write_bytes(b'x' * (8 * 1024 * 1024 + 1))
        self.assertEqual('invalid', self.finish()[1]['status'])

    def test_controller_observes_artifact_before_dispatch_and_detects_later_drift(self):
        command = [sys.executable, str(Path(__file__).with_name('role_result.py')), 'observe',
                   '--workspace', str(self.root), '--kind', 'artifact', '--reference', 'prd.md']
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertTrue(completed.stdout.strip(), 'The controller needs a file reference, not a document in summary')
        evidence = json.loads(completed.stdout)
        self.assertEqual('prd.md', evidence['reference'])
        self.assertEqual('available', self.finish(digest=evidence['content_fingerprint'])[1]['status'])
        self.artifact.write_text('changed\n')
        self.assertEqual('evidence_mismatch', self.finish(digest=evidence['content_fingerprint'])[1]['reason'])


if __name__ == '__main__':
    unittest.main()
