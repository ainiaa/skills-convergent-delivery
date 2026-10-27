"""Author: Jeff.Liu. Native Rust mutation evidence must prove fresh, scoped tests."""
from pathlib import Path
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import evidence_contract as evidence


def command():
    return ["cargo", "mutants", "--manifest-path", "crate/Cargo.toml", "--no-config",
            "--baseline", "run", "--no-shuffle", "--all-logs", "--caught", "--jobs", "1",
            "--timeout", "180", "--re", "^src/lib.rs:1:1: replace allowed with false$",
            "--output", "/tmp/fresh-mutants", "--cargo-arg=--locked", "--cargo-arg=--offline",
            "--", "--lib", "boundary", "--", "--test-threads=2"]


OUTPUT = b"""Found 1 mutant to test
ok       Unmutated baseline in 0s build + 0s test

*** baseline
*** /toolchain/bin/cargo test --verbose --package=fixture@0.1.0 --locked --offline --lib boundary -- --test-threads=2
test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
*** result: Success

caught   src/lib.rs:1:1: replace allowed with false in 0s build + 0s test
*** src/lib.rs:1:1: replace allowed with false
*** /toolchain/bin/cargo test --verbose --package=fixture@0.1.0 --locked --offline --lib boundary -- --test-threads=2
test result: FAILED. 0 passed; 1 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.00s
*** result: Failure(101)
1 mutant tested in 1s: 1 caught
"""


class RustMutationTests(unittest.TestCase):
    def test_native_cargo_mutants_proves_a_nonempty_baseline_and_caught_mutation(self):
        self.assertEqual(evidence.mutation_execution_result(command(), OUTPUT),
                         {"selector": "boundary", "generated": 1, "killed": 1, "tests": 1})

    def test_summary_without_baseline_or_assertion_execution_is_rejected(self):
        for old, new in [(b"1 passed; 0 failed", b"0 passed; 0 failed"),
                         (b"0 passed; 1 failed", b"0 passed; 0 failed"),
                         (b"*** baseline", b"*** skipped baseline"),
                         (b"1 caught\n", b"1 missed\n"),
                         (b"1 caught\n", b"1 unviable\n"),
                         (b"1 caught\n", b"1 timeout\n"),
                         (b"Found 1 mutant", b"Found 2 mutants"),
                         (b"1 mutant tested", b"0 mutants tested")]:
            with self.subTest(old=old, new=new):
                self.assertIsNone(evidence.mutation_execution_result(command(), OUTPUT.replace(old, new)))

    def test_selection_and_execution_flags_cannot_be_weakened(self):
        variants = [command() + ["--iterate"], command() + ["--list"],
                    ["echo", *command()[1:]], command()[:-1],
                    ["--no-all-logs" if x == "--all-logs" else x for x in command()],
                    ["skip" if x == "run" else x for x in command()],
                    ["../Cargo.toml" if x == "crate/Cargo.toml" else x for x in command()],
                    ["missing" if x == "boundary" else x for x in command()]]
        for argv in variants:
            with self.subTest(argv=argv):
                self.assertIsNone(evidence.mutation_execution_result(argv, OUTPUT))

    def test_counts_and_mutant_identity_must_match_the_frozen_filter(self):
        for output in [OUTPUT + OUTPUT, OUTPUT.replace(b"src/lib.rs:1:1", b"src/other.rs:2:2"),
                       OUTPUT.replace(b"1 caught\n", b"1 caught, 1 missed\n"),
                       OUTPUT.replace(b"*** result: Failure(101)", b"*** result: Timeout")]:
            with self.subTest(output=output[-100:]):
                self.assertIsNone(evidence.mutation_execution_result(command(), output))

    def test_mutation_scope_is_a_finite_identity_set_not_a_wildcard(self):
        argv = command()
        argv[15] = r"^src/.+\.rs:1:1: replace allowed with false$"
        self.assertIsNone(evidence.mutation_execution_result(argv, OUTPUT))

    def test_frozen_diff_filter_can_limit_all_native_mutant_genres(self):
        argv = command()
        argv[16:16] = ["--in-diff", "scope.diff"]
        self.assertEqual(evidence.mutation_execution_result(argv, OUTPUT),
                         {"selector": "boundary", "generated": 1, "killed": 1, "tests": 1})
        argv[17] = "../outside.diff"
        self.assertIsNone(evidence.mutation_execution_result(argv, OUTPUT))

    def test_finite_union_preserves_literal_identities_and_requires_every_member(self):
        name = "src/lib.rs:1:1: replace allowed with false"
        other = name.replace("false", "true")
        argv = command()
        argv[15] = "^(?:" + "|".join(map(re.escape, [name, other])) + ")$"
        start = OUTPUT.index(b"caught   ")
        end = OUTPUT.index(b"1 mutant tested")
        block = OUTPUT[start:end]
        baseline = OUTPUT[:start].replace(b"Found 1 mutant", b"Found 2 mutants")
        output = baseline + block + block.replace(b"with false", b"with true") + b"2 mutants tested in 1s: 2 caught\n"
        self.assertEqual(evidence.mutation_execution_result(argv, output),
                         {"selector": "boundary", "generated": 2, "killed": 2, "tests": 1})
        self.assertIsNone(evidence.mutation_execution_result(argv, output.replace(b"with true", b"with false")))

    def test_public_runner_checks_the_tool_version_and_binds_current_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "crate").mkdir()
            (root / "crate/Cargo.toml").write_text("[package]\nname='fixture'\nversion='0.1.0'\n")
            subprocess.run(["git", "init", "-q", directory], check=True)
            subprocess.run(["git", "-C", directory, "add", "."], check=True)
            subprocess.run(["git", "-C", directory, "-c", "user.name=Jeff.Liu", "-c",
                            "user.email=fixture@example.invalid", "-c", "commit.gpgsign=false",
                            "commit", "-qm", "fixture"], check=True)
            with patch.object(evidence, "_run_command", side_effect=[
                    (0, b"cargo-mutants 27.1.0\n", b""), (0, OUTPUT, b"")]) as run:
                receipt = evidence.run_evidence(root, "HEAD", command(), 30)
            self.assertEqual(run.call_count, 2)
            try:
                evidence.validate_observed_evidence_receipt(receipt)
            except ValueError as error:
                self.fail(f"Fresh Rust mutation receipt must be consumable: {error}")
            self.assertEqual(receipt.get("mutation_check"),
                             {"selector": "boundary", "generated": 1, "killed": 1, "tests": 1})
            filtered = command()
            filtered[16:16] = ["--in-diff", "scope.diff"]
            (root / "scope.diff").write_text("frozen locations\n")
            with patch.object(evidence, "_run_command", side_effect=[
                    (0, b"cargo-mutants 27.1.0\n", b""), (0, OUTPUT, b"")]):
                self.assertIn("mutation_check", evidence.run_evidence(root, "HEAD", filtered, 30))
            (root / "scope.diff").unlink()
            (root / "scope.diff").symlink_to("/tmp/outside/scope.diff")
            with self.assertRaisesRegex(ValueError, "workspace"):
                evidence.run_evidence(root, "HEAD", filtered, 30)
            with patch.object(evidence, "_run_command", return_value=(0, b"cargo-mutants 1.0.0\n", b"")):
                with self.assertRaisesRegex(ValueError, "27.1.0"):
                    evidence.run_evidence(root, "HEAD", command(), 30)
            (root / "crate/Cargo.toml").unlink()
            (root / "crate/Cargo.toml").symlink_to("/tmp/outside/Cargo.toml")
            with self.assertRaisesRegex(ValueError, "workspace"):
                evidence.run_evidence(root, "HEAD", command(), 30)


if __name__ == "__main__":
    unittest.main()
