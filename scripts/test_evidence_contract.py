import json
import subprocess
import sys
import tempfile
import unittest
import os
import time
from pathlib import Path
from unittest.mock import patch

import evidence_contract


class EvidenceContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q", str(self.workspace)], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(self.workspace), "config", "user.email", "test@example.com"],
            check=True,
        )
        (self.workspace / "seed.txt").write_text("seed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "seed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "seed"],
            check=True,
        )
        self.baseline = subprocess.run(
            ["git", "-C", str(self.workspace), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    def tearDown(self):
        self.temporary.cleanup()

    def test_jacoco_warning_on_stderr_cannot_pass_with_exit_zero(self):
        from tdd_impact_guard import coverage_receipt
        executable = self.workspace / 'gradle'
        stdout = "> Task :jacocoTestCoverageVerification\n[ant:jacocoReport] Loading execution data file build/test.exec\n[ant:jacocoReport] Writing bundle 'demo' with 1 classes\nBUILD SUCCESSFUL\n"
        stderr = "[ant:jacocoReport] Rule violated for bundle demo: lines covered ratio is 0.66, but expected minimum is 0.85"
        executable.write_text(f'#!{sys.executable}\nimport sys\nprint({stdout!r})\nprint({stderr!r}, file=sys.stderr)\n')
        executable.chmod(0o700)
        observed = evidence_contract.run_evidence(self.workspace, self.baseline,
                                                 [str(executable), 'jacocoTestCoverageVerification'])
        self.assertEqual(0, observed['exit_code'])
        with self.assertRaisesRegex(ValueError, 'coverage'):
            coverage_receipt({'status': 'covered', 'threshold': 85, 'receipt': observed}, observed['source'])

    def test_jacoco_coverage_requires_an_executed_nonempty_check(self):
        from tdd_impact_guard import coverage_receipt
        gradle_good = "> Task :jacocoTestCoverageVerification\n[ant:jacocoReport] Loading execution data file build/test.exec\n[ant:jacocoReport] Writing bundle 'demo' with 1 classes\nBUILD SUCCESSFUL\n"
        maven_good = "[INFO] --- jacoco:0.8.13:check (default-cli) @ demo ---\n[INFO] Loading execution data file target/jacoco.exec\n[INFO] Analyzed bundle 'demo' with 1 classes\n[INFO] All coverage checks have been met.\n[INFO] BUILD SUCCESS\n"
        cases = [
            ('gradle', gradle_good, 0, True), ('mvn', maven_good, 0, True),
            ('gradle', '> Task :jacocoTestCoverageVerification SKIPPED\nBUILD SUCCESSFUL\n', 0, False),
            ('gradle', gradle_good.replace('Verification\n', 'Verification UP-TO-DATE\n'), 0, False),
            ('gradle', gradle_good.replace('Verification', 'Report'), 0, False),
            ('gradle', gradle_good + '> Task :other:jacocoTestCoverageVerification SKIPPED\n', 0, False),
            ('mvn', maven_good.replace('check (', 'report ('), 0, False),
            ('mvn', maven_good.replace('Loading execution data file target/jacoco.exec', 'Skipping JaCoCo execution due to missing execution data file.'), 0, False),
            ('mvn', maven_good.replace('1 classes', '0 classes'), 0, False),
            ('mvn', maven_good.replace('All coverage checks have been met.', 'Coverage checks have not been met.'), 0, False),
            ('gradle', gradle_good, 1, False), ('mvn', '[INFO] BUILD SUCCESS\n', 0, False),
        ]
        for runner, output, exit_code, expected in cases:
            with self.subTest(runner=runner, output=output, exit_code=exit_code):
                executable = self.workspace / runner
                # Real process receipt; output is a protocol fixture, not a real Java coverage claim.
                executable.write_text(f'#!{sys.executable}\nprint({output!r})\nraise SystemExit({exit_code})\n')
                executable.chmod(0o700)
                argv = [str(executable), 'jacoco:check' if runner == 'mvn' else 'jacocoTestCoverageVerification']
                observed = evidence_contract.run_evidence(self.workspace, self.baseline, argv)
                coverage = {'status': 'covered', 'threshold': 85, 'receipt': observed}
                if expected:
                    self.assertTrue(coverage_receipt(coverage, observed['source']))
                    self.assertEqual({'checks': 1, 'classes': 1}, observed['jacoco_check'])
                else:
                    with self.assertRaisesRegex(ValueError, 'coverage'):
                        coverage_receipt(coverage, observed['source'])

    def test_source_receipt_is_versioned_and_uses_the_frozen_baseline(self):
        (self.workspace / "committed.txt").write_text("committed\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(self.workspace), "add", "committed.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(self.workspace), "commit", "-q", "-m", "task"],
            check=True,
        )
        (self.workspace / "working.txt").write_text("working\n", encoding="utf-8")

        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertEqual(2, source["schema_version"])
        self.assertEqual(self.baseline, source["baseline_commit"])
        self.assertEqual(["committed.txt", "working.txt"], source["changed_paths"])
        self.assertEqual(
            ["committed.txt", "working.txt"],
            [entry["path"] for entry in source["changed_entries"]],
        )

    def test_source_identity_includes_file_type_and_mode(self):
        path = self.workspace / "tool.sh"
        path.write_text("#!/bin/sh\n", encoding="utf-8")
        before = evidence_contract.workspace_source(self.workspace, self.baseline)

        os.chmod(path, 0o755)
        after = evidence_contract.workspace_source(self.workspace, self.baseline)

        self.assertNotEqual(before["source_fingerprint"], after["source_fingerprint"])
        self.assertEqual("100755", after["changed_entries"][0]["mode"])

    def test_pass_receipt_is_created_by_running_argv_and_matches_the_exact_source(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "print('verified')"]
        )

        self.assertEqual(receipt, evidence_contract.validate_observed_evidence_receipt(receipt))
        self.assertTrue(evidence_contract.valid_evidence_receipts([receipt], source))
        self.assertEqual(2, receipt["schema_version"])
        self.assertEqual([sys.executable, "-c", "print('verified')"], receipt["argv"])
        self.assertFalse(
            evidence_contract.valid_evidence_receipts(
                [{**receipt, "receipt_fingerprint": "0" * 64}], source
            )
        )

    def test_observed_receipt_keeps_a_real_failure_for_tdd_red_evidence(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "raise SystemExit(1)"]
        )

        self.assertEqual(1, evidence_contract.validate_observed_evidence_receipt(receipt)["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], receipt["source"]))

    def test_source_changed_after_assertion_cannot_receive_a_fresh_receipt(self):
        command = [sys.executable, "-c", (
            "from pathlib import Path; p=Path('seed.txt'); "
            "assert p.read_text() == 'seed\\n'; p.write_text('broken\\n')"
        )]
        with self.assertRaisesRegex(ValueError, "changed.*source"):
            evidence_contract.run_evidence(self.workspace, self.baseline, command)
        self.assertEqual("broken\n", (self.workspace / "seed.txt").read_text())

    def test_cli_rejects_source_drift_instead_of_returning_a_pass_receipt(self):
        result = subprocess.run(
            [sys.executable, str(Path(evidence_contract.__file__)), "run",
             "--workspace", str(self.workspace), "--baseline", self.baseline, "--",
             sys.executable, "-c", "from pathlib import Path; Path('seed.txt').unlink()"],
            capture_output=True, text=True, check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertEqual("", result.stdout)
        self.assertIn("source", result.stderr)

    def test_nonexistent_command_cannot_be_turned_into_a_passing_receipt(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)

        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, ["definitely-not-a-real-command"]
        )

        self.assertEqual(127, receipt["exit_code"])
        self.assertFalse(evidence_contract.valid_evidence_receipts([receipt], source))

    def test_timeout_becomes_a_non_passing_receipt(self):
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, "-c", "import time; time.sleep(1)"],
            timeout_seconds=0.01,
        )

        self.assertEqual(124, receipt["exit_code"])

    def test_timeout_cleans_up_descendants_before_returning(self):
        child = "import time;from pathlib import Path;time.sleep(.7);Path('late.txt').write_text('late')"
        parent = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
            "print('started',flush=True);time.sleep(5)"
        )
        receipt = evidence_contract.run_evidence(
            self.workspace, self.baseline, [sys.executable, '-c', parent], timeout_seconds=.3,
        )
        self.assertEqual(124, receipt['exit_code'])
        import hashlib
        self.assertEqual(hashlib.sha256(b'started\n').hexdigest(), receipt['stdout_fingerprint'])
        time.sleep(.8)
        self.assertFalse((self.workspace / 'late.txt').exists())

    def test_exited_command_cannot_leave_a_background_writer(self):
        child = "import time;from pathlib import Path;time.sleep(.4);Path('late.txt').write_text('late')"
        for exit_code in (0, 1):
            parent = (
                'import subprocess,sys;'
                f'subprocess.Popen([sys.executable,"-c",{child!r}],'
                'stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL);'
                f'raise SystemExit({exit_code})'
            )
            receipt = evidence_contract.run_evidence(self.workspace, self.baseline, [sys.executable, '-c', parent])
            self.assertEqual(exit_code, receipt['exit_code'])
            time.sleep(.5)
            self.assertFalse((self.workspace / 'late.txt').exists())

    def test_cleanup_failure_cannot_issue_an_evidence_receipt(self):
        with patch('codex_exec_runner._terminate_process', side_effect=PermissionError('cleanup denied')):
            with self.assertRaises(PermissionError):
                evidence_contract.run_evidence(self.workspace, self.baseline, [sys.executable, '-c', 'pass'])


    def test_cli_executes_the_command_without_a_shell(self):
        marker = self.workspace / ".git" / "marker.txt"
        result = subprocess.run(
            [
                sys.executable,
                str(Path(evidence_contract.__file__)),
                "run",
                "--workspace",
                str(self.workspace),
                "--baseline",
                self.baseline,
                "--",
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ],
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("ran", marker.read_text(encoding="utf-8"))
        self.assertEqual(0, json.loads(result.stdout)["exit_code"])

    def test_sensitive_command_arguments_are_rejected_before_execution(self):
        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["tool", "--api-key=secret-value"]
            )

        with self.assertRaisesRegex(ValueError, "sensitive"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, ["curl", "Authorization: Bearer secret-value"]
            )

    def test_receipts_reject_oversized_argv_values(self):
        with self.assertRaisesRegex(ValueError, "argv"):
            evidence_contract.run_evidence(
                self.workspace, self.baseline, [sys.executable, "-c", "x" * 4097]
            )

    def test_source_receipt_validator_rejects_tampered_metadata(self):
        source = evidence_contract.workspace_source(self.workspace, self.baseline)
        source["changed_paths"] = ["invented.txt"]

        with self.assertRaisesRegex(ValueError, "paths|fingerprint"):
            evidence_contract.validate_source_receipt(source)


if __name__ == "__main__":
    unittest.main()
