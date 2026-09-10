import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parent.parent


class PythonMatrixScriptTest(unittest.TestCase):
    def test_reuses_versioned_uv_environments_for_both_ci_runtimes(self):
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
                "#!/usr/bin/env bash\n{ printf 'uv'; printf ' <%s>' \"$@\"; printf '\\n'; } >> \"$MATRIX_LOG\"\n",
                encoding="utf-8",
            )
            uv.chmod(0o755)
            for name in ("py311", "py314"):
                python = workspace / ".venv" / name / "bin" / "python"
                python.parent.mkdir(parents=True)
                python.write_text(
                    "#!/usr/bin/env bash\n{ printf 'python:%s' \"$0\"; printf ' <%s>' \"$@\"; printf '\\n'; } >> \"$MATRIX_LOG\"\n"
                    "if [[ ${MATRIX_FAIL_311:-0} == 1 && $0 == */py311/bin/python ]]; then exit 1; fi\n",
                    encoding="utf-8",
                )
                python.chmod(0o755)

            result = subprocess.run(
                ["bash", "scripts/test_python_matrix.sh"], cwd=workspace,
                env={**os.environ, "PATH": f"{tools}:{os.environ['PATH']}", "MATRIX_LOG": str(log)},
                text=True, capture_output=True, check=False,
            )

            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual(
                [
                    "uv <python> <install> <3.11>",
                    "uv <venv> <--allow-existing> <--python> <3.11> <.venv/py311>",
                    "uv <pip> <install> <--python> <.venv/py311/bin/python> <-r> <requirements-dev.txt>",
                    f"python:{workspace}/.venv/py311/bin/python <-m> <pytest> <scripts/test_coverage_gate.py> <--cov> <--cov-fail-under=85>",
                    "uv <python> <install> <3.14>",
                    "uv <venv> <--allow-existing> <--python> <3.14> <.venv/py314>",
                    "uv <pip> <install> <--python> <.venv/py314/bin/python> <-r> <requirements-dev.txt>",
                    f"python:{workspace}/.venv/py314/bin/python <-m> <pytest> <scripts/test_coverage_gate.py> <--cov> <--cov-fail-under=85>",
                ],
                log.read_text(encoding="utf-8").splitlines(),
            )

            log.write_text("", encoding="utf-8")
            failure = subprocess.run(
                ["bash", "scripts/test_python_matrix.sh"], cwd=workspace,
                env={
                    **os.environ, "PATH": f"{tools}:{os.environ['PATH']}",
                    "MATRIX_LOG": str(log), "MATRIX_FAIL_311": "1",
                },
                text=True, capture_output=True, check=False,
            )

            self.assertNotEqual(0, failure.returncode)
            self.assertIn(
                f"python:{workspace}/.venv/py314/bin/python <-m> <pytest>",
                log.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
