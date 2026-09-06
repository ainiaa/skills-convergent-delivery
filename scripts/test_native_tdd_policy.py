import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("native_tdd_policy.py")
SPEC = importlib.util.spec_from_file_location("native_tdd_policy", MODULE_PATH)
native_tdd_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native_tdd_policy)


def maven_config(minimum="0.92"):
    return (
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
        '<build><plugins><plugin><groupId>org.jacoco</groupId><artifactId>jacoco-maven-plugin</artifactId>'
        '<configuration><rules><rule><element>BUNDLE</element><limits><limit>'
        '<counter>LINE</counter><value>COVEREDRATIO</value>'
        f'<minimum>{minimum}</minimum></limit></limits></rule></rules></configuration>'
        '</plugin></plugins></build></project>'
    )


class NativeTddPolicyTest(unittest.TestCase):
    def test_informational_commands_cannot_supply_coverage_evidence(self):
        for command in (
            "mvn --help jacoco:check", "mvn -h jacoco:check", "mvn --version jacoco:check",
            "mvn -v jacoco:check", "mvn --fail-never jacoco:check",
            "pytest --cov --cov-fail-under=85 --help", "pytest --cov --version --cov-fail-under=85",
            "python3 -m coverage report --fail-under=85 --help",
            "npx vitest run --coverage --coverage.thresholds.lines=85 --help",
            "gradle test jacocoTestCoverageVerification --help",
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                standard = root / "docs/00_standards"
                standard.mkdir(parents=True)
                (standard / "test-commands.yml").write_text(f"coverage: {command}\n")
                (root / "pom.xml").write_text(maven_config())
                (root / "build.gradle").write_text("counter = 'LINE'\nminimum = 0.92")
                self.assertEqual("uncovered", native_tdd_policy.resolve(root)["status"])

    def test_maven_threshold_must_belong_to_an_active_jacoco_ratio_rule(self):
        valid = maven_config()
        for content in (
            "<counter>LINE</counter><minimum>0.92</minimum>",
            "<project><!-- <counter>LINE</counter><minimum>0.92</minimum> --></project>",
            valid.replace("<plugins>", "<pluginManagement><plugins>").replace("</plugins>", "</plugins></pluginManagement>"),
            valid.replace("<build>", "<profiles><profile><build>").replace("</build>", "</build></profile></profiles>"),
            valid.replace("org.jacoco", "other.plugin"),
            valid.replace("COVEREDRATIO", "MISSEDCOUNT"),
            valid.replace("<configuration>", "<configuration><skip>true</skip>"),
            valid.replace("<configuration>", "<configuration><haltOnFailure>false</haltOnFailure>"),
            valid.replace("</plugin>", "<executions><execution><id>default-cli</id>"
                          "<configuration><skip>true</skip></configuration>"
                          "</execution></executions></plugin>"),
        ):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                standard = root / "docs/00_standards"
                standard.mkdir(parents=True)
                (standard / "test-commands.yml").write_text("coverage: mvn test jacoco:check\n")
                (root / "pom.xml").write_text(content)
                self.assertEqual("uncovered", native_tdd_policy.resolve(root)["status"])

    def test_maven_show_version_preserves_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            standard = root / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text("coverage: mvn -V test jacoco:check\n")
            (root / "pom.xml").write_text(maven_config())
            self.assertEqual("ready", native_tdd_policy.resolve(root)["status"])

    def test_gradle_comments_cannot_supply_a_threshold(self):
        for content in ("// counter = 'LINE'\n// minimum = 0.92", "/* counter = 'LINE'\nminimum = 0.92 */"):
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                standard = root / "docs/00_standards"
                standard.mkdir(parents=True)
                (standard / "test-commands.yml").write_text("coverage: gradle test jacocoTestCoverageVerification\n")
                (root / "build.gradle").write_text(content)
                self.assertEqual("uncovered", native_tdd_policy.resolve(root)["status"])

    def test_conflicting_thresholds_and_inactive_gates_are_rejected(self):
        commands = (
            'pytest --cov --cov-fail-under=85 --cov-fail-under=1',
            'pytest --cov --cov-fail-under 1 --cov-fail-under 85',
            'pytest --cov --cov-fail-under=85 --cov-fail-under=85',
            'pytest --cov --cov-fail-under=85 --collect-only',
            'pytest --cov --cov-fail-under=85 --co',
            'pytest --cov --cov-reset --cov-fail-under=85',
            'pytest --cov --cov-fail-under=85.5',
            'pytest --cov --cov-fail-under=invalid',
            'pytest --cov -- --cov-fail-under=85',
            'npx vitest run --coverage.thresholds.lines=85',
            'npx vitest run --coverage.enabled=false --coverage.thresholds.lines=85',
            'npx vitest run --coverage.enabled false --coverage.thresholds.lines=85',
            'gradle test jacocoTestCoverageVerification --exclude-task=jacocoTestCoverageVerification',
        )
        for command in commands:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                standard = workspace / 'docs/00_standards'
                standard.mkdir(parents=True)
                (standard / 'test-commands.yml').write_text(f'coverage: {command}\n')
                (workspace / 'build.gradle').write_text("counter = 'LINE'\nminimum = 0.85")
                self.assertEqual('uncovered', native_tdd_policy.resolve(workspace)['status'])

    def test_enabled_collection_and_exact_threshold_values_remain_supported(self):
        commands = (
            'pytest --cov-reset --cov=src --cov-fail-under 85',
            'pytest --cov --cov-fail-under=1',
            'pytest --cov --cov-fail-under=100',
            'npx vitest run --coverage.enabled --coverage.thresholds.lines=85',
            'npx vitest run --coverage.enabled=true --coverage.thresholds.lines=85',
        )
        for command in commands:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                standard = Path(directory) / 'docs/00_standards'
                standard.mkdir(parents=True)
                (standard / 'test-commands.yml').write_text(f'coverage: {command}\n')
                self.assertEqual('ready', native_tdd_policy.resolve(directory)['status'])

    def test_runner_arguments_and_disabled_collection_cannot_claim_coverage(self):
        commands = (
            'echo pytest --cov-fail-under=85',
            'python3 -c pass pytest --cov-fail-under=85',
            'pytest --cov --cov-fail-under=85 --no-cov',
            'pytest --cov-fail-under=85',
            'dotnet build /p:Threshold=85',
            'dotnet test /p:CollectCoverage=false /p:Threshold=85',
            'npx vitest run --coverage=false --coverage.thresholds.lines=85',
            'mvn test jacoco:check -Djacoco.skip=true',
            'gradle test jacocoTestCoverageVerification --dry-run',
        )
        for command in commands:
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                standard = workspace / 'docs/00_standards'
                standard.mkdir(parents=True)
                (standard / 'test-commands.yml').write_text(f'coverage: {command}\n')
                (workspace / 'pom.xml').write_text('<counter>LINE</counter><minimum>0.85</minimum>')
                (workspace / 'build.gradle').write_text("counter = 'LINE'\nminimum = 0.85")
                self.assertEqual('uncovered', native_tdd_policy.resolve(workspace)['status'])

    def test_coverage_command_has_priority_and_is_split_into_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: python3 -m pytest --cov --cov-fail-under=91\n", encoding="utf-8"
            )
            (standard / "quality-targets.yml").write_text("coverage: 92\n", encoding="utf-8")

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("test-commands.yml", policy["source"])
        self.assertEqual(91, policy["threshold"])
        self.assertEqual("argv", policy["threshold_source"])
        self.assertEqual(["python3", "-m", "pytest", "--cov", "--cov-fail-under=91"], policy["argv"])

    def test_quality_target_overrides_the_default_when_no_command_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "quality-targets.yml").write_text("coverage: 92\n", encoding="utf-8")

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("quality-targets.yml", policy["source"])
        self.assertEqual("uncovered", policy["status"])
        self.assertEqual(92, policy["threshold"])
        self.assertEqual("quality-targets.yml", policy["threshold_source"])
        self.assertIsNone(policy["argv"])

    def test_pytest_and_vitest_commands_receive_the_resolved_threshold(self):
        for command, expected in (
            ("python3 -m pytest --cov", "--cov-fail-under=92"),
            ("npx vitest run --coverage", "--coverage.thresholds.lines=92"),
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                standard = workspace / "docs/00_standards"
                standard.mkdir(parents=True)
                (standard / "test-commands.yml").write_text(
                    f"coverage: {command}\n", encoding="utf-8"
                )
                (standard / "quality-targets.yml").write_text("coverage: 92\n", encoding="utf-8")

                policy = native_tdd_policy.resolve(workspace)

            self.assertEqual("adapter", policy["threshold_source"])
            self.assertEqual(expected, policy["argv"][-1])

    def test_unadaptable_command_without_an_explicit_gate_stays_uncovered(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: mvn test\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("cannot enforce", policy["reason"])

    def test_runner_without_coverage_collection_is_not_adapted(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: python3 -m pytest\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("cannot enforce", policy["reason"])

    def test_existing_jacoco_gate_is_accepted_only_when_its_project_threshold_is_sufficient(self):
        for command, config, content in (
            ("mvn test jacoco:check", "pom.xml", maven_config()),
            ("gradle test jacocoTestCoverageVerification", "build.gradle", "counter = 'LINE'\nminimum = 0.92\n"),
        ):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as directory:
                workspace = Path(directory)
                standard = workspace / "docs/00_standards"
                standard.mkdir(parents=True)
                (standard / "test-commands.yml").write_text(
                    f"coverage: {command}\n", encoding="utf-8"
                )
                (workspace / config).write_text(content, encoding="utf-8")

                policy = native_tdd_policy.resolve(workspace)

            self.assertEqual("ready", policy["status"])
            self.assertEqual(92, policy["threshold"])
            self.assertEqual("project-coverage-config", policy["threshold_source"])

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: mvn test jacoco:check\n", encoding="utf-8"
            )
            (standard / "quality-targets.yml").write_text("coverage: 90\n", encoding="utf-8")
            (workspace / "pom.xml").write_text(
                maven_config("0.85"), encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("below", policy["reason"])

        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: mvn test jacoco:check\n", encoding="utf-8"
            )
            (standard / "quality-targets.yml").write_text("coverage: 90\n", encoding="utf-8")
            (workspace / "pom.xml").write_text(
                maven_config("0.85").replace("<limits>", "<limits><limit><counter>BRANCH</counter><minimum>0.95</minimum></limit>"),
                encoding="utf-8",
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("below", policy["reason"])

    def test_no_project_configuration_uses_the_85_percent_default(self):
        with tempfile.TemporaryDirectory() as directory:
            policy = native_tdd_policy.resolve(Path(directory))

        self.assertEqual("default", policy["source"])
        self.assertEqual("uncovered", policy["status"])
        self.assertEqual(85, policy["threshold"])
        self.assertEqual("default", policy["threshold_source"])
        self.assertIsNone(policy["argv"])

    def test_shell_syntax_is_not_treated_as_an_executable_argv(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: pytest --cov | tee coverage.log\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("shell syntax", policy["reason"])

    def test_dotnet_explicit_threshold_is_an_executable_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: dotnet test /p:CollectCoverage=true /p:Threshold=90\n",
                encoding="utf-8",
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("ready", policy["status"])
        self.assertEqual(90, policy["threshold"])
        self.assertEqual("argv", policy["threshold_source"])

    def test_unrelated_threshold_argument_does_not_claim_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: npm test --threshold=90\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])

    def test_explicit_threshold_requires_a_supported_coverage_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: echo --fail-under=90\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("uncovered", policy["status"])
        self.assertIn("cannot enforce", policy["reason"])

    def test_coverage_dot_py_explicit_threshold_is_a_coverage_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            standard = workspace / "docs/00_standards"
            standard.mkdir(parents=True)
            (standard / "test-commands.yml").write_text(
                "coverage: coverage.py report --fail-under=90\n", encoding="utf-8"
            )

            policy = native_tdd_policy.resolve(workspace)

        self.assertEqual("ready", policy["status"])
        self.assertEqual(90, policy["threshold"])


if __name__ == "__main__":
    unittest.main()
