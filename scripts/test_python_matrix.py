import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent


class PythonMatrixScriptTest(unittest.TestCase):
    def test_reuses_versioned_uv_environments_and_runs_both_ci_runtimes_in_parallel(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory).resolve()
            scripts = workspace / "scripts"
            tools = workspace / "tools"
            scripts.mkdir()
            tools.mkdir()
            shutil.copy2(ROOT / "scripts" / "test_python_matrix.sh", scripts)
            (workspace / "requirements-dev.txt").write_text("PyYAML==6.0.3\n", encoding="utf-8")
            log = workspace / "commands.log"

            uv = tools / "uv"
            uv.write_text(
                "#!/usr/bin/env bash\n"
                "while ! mkdir \"${MATRIX_LOG}.lock\" 2>/dev/null; do sleep 0.001; done\n"
                "{ printf 'uv'; printf ' <%s>' \"$@\"; printf '\\n'; } >> \"$MATRIX_LOG\"\n"
                "rmdir \"${MATRIX_LOG}.lock\"\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            for name in ("py311", "py314"):
                python = workspace / ".venv" / name / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.write_text(
                    "#!/usr/bin/env bash\n"
                    "while ! mkdir \"${MATRIX_LOG}.lock\" 2>/dev/null; do sleep 0.001; done\n"
                    "{ printf 'python:%s' \"$0\"; printf ' <%s>' \"$@\"; printf '\\n'; } >> \"$MATRIX_LOG\"\n"
                    "rmdir \"${MATRIX_LOG}.lock\"\n"
                    "if [[ $0 == */py311/bin/python ]]; then\n"
                    "  touch \"$MATRIX_311_STARTED\"\n"
                    "  for _ in {1..100}; do [[ -f \"$MATRIX_314_STARTED\" ]] && break; sleep 0.01; done\n"
                    "  [[ -f \"$MATRIX_314_STARTED\" ]] || exit 99\n"
                    "else\n"
                    "  touch \"$MATRIX_314_STARTED\"\n"
                    "fi\n"
                    "if [[ ${MATRIX_FAIL_311:-0} == 1 && $0 == */py311/bin/python ]]; then exit 1; fi\n",
                    encoding="utf-8",
                )
                python.chmod(0o755)

            result = subprocess.run(
                ["bash", "scripts/test_python_matrix.sh"], cwd=workspace,
                env={
                    **os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "MATRIX_LOG": str(log),
                    "MATRIX_311_STARTED": str(workspace / "py311.started"),
                    "MATRIX_314_STARTED": str(workspace / "py314.started"),
                },
                text=True, capture_output=True, check=False,
                timeout=3,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            commands = log.read_text(encoding="utf-8")
            self.assertIn("<install> <3.11>", commands)
            self.assertIn("<install> <3.14>", commands)
            self.assertIn(
                f"python:{workspace}/.venv/py311/bin/python <-m> <pytest> <scripts/test_coverage_gate.py> <--cov> <--cov-fail-under=90>", commands,
            )
            self.assertIn(
                f"python:{workspace}/.venv/py314/bin/python <-m> <pytest> <scripts/test_coverage_gate.py> <--cov> <--cov-fail-under=90>", commands,
            )

            log.write_text("", encoding="utf-8")
            for marker in (workspace / "py311.started", workspace / "py314.started"):
                marker.unlink()
            failure = subprocess.run(
                ["bash", "scripts/test_python_matrix.sh"], cwd=workspace,
                env={
                    **os.environ, "PATH": f"{tools}:{os.environ['PATH']}",
                    "MATRIX_LOG": str(log), "MATRIX_FAIL_311": "1",
                    "MATRIX_311_STARTED": str(workspace / "py311.started"),
                    "MATRIX_314_STARTED": str(workspace / "py314.started"),
                },
                text=True, capture_output=True, check=False,
                timeout=3,
            )

            self.assertNotEqual(0, failure.returncode)
            self.assertIn(
                f"python:{workspace}/.venv/py314/bin/python <-m> <pytest>",
                log.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
