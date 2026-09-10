#!/usr/bin/env python3
"""Tests for named and per-run multi-model delivery profiles."""

import json
import os
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from multi_model import audit_request, desktop_task_action, main, resolve


def delivery_profile(*, router="gpt-5.6-terra", reviewer="gpt-5.6-terra"):
    return {
        "router": {"model": router, "reasoning_effort": "medium"},
        "scout": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
        "specifier": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "implementer": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
        "reviewer": {"model": reviewer, "reasoning_effort": "high" if reviewer == "glm-5.2" else "high"},
        "adjudicator": {"model": "gpt-6-astra", "reasoning_effort": "low"},
    }


def claude_profile():
    return {
        "router": {"model": "haiku", "reasoning_effort": "medium"},
        "scout": {"model": "haiku", "reasoning_effort": "medium"},
        "specifier": {"model": "sonnet", "reasoning_effort": "high"},
        "implementer": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
        "reviewer": {"model": "sonnet", "reasoning_effort": "high"},
        "adjudicator": {"model": "opus", "reasoning_effort": "xhigh"},
    }


def config(*, default="default", profiles=None):
    return {"schema_version": 4, "default_profile": default, "profiles": profiles or {"default": delivery_profile()}}


class MultiModelTest(unittest.TestCase):
    def test_default_profile_assigns_each_model_backed_role(self):
        with tempfile.TemporaryDirectory() as directory:
            value = resolve(None, workspace=Path(directory) / "repo", home=Path(directory) / "home")
        self.assertEqual("default", value["profile_name"])
        self.assertEqual("gpt-5.6-terra", value["roles"]["router"]["effective"]["model"])
        self.assertEqual("medium", value["roles"]["scout"]["effective"]["reasoning_effort"])
        self.assertEqual("high", value["roles"]["specifier"]["effective"]["reasoning_effort"])
        self.assertEqual("gpt-5.6-luna", value["roles"]["implementer"]["effective"]["model"])
        self.assertEqual("high", value["roles"]["implementer"]["effective"]["reasoning_effort"])
        self.assertEqual("gpt-6-astra", value["roles"]["adjudicator"]["effective"]["model"])
        self.assertEqual("low", value["roles"]["adjudicator"]["effective"]["reasoning_effort"])
        self.assertNotIn("verifier", value["roles"])

    def test_selects_named_profile_and_allows_per_run_role_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={
                "default": delivery_profile(),
                "fast": delivery_profile(router="gpt-5.6-luna"),
            })), encoding="utf-8")
            value = resolve(path, profile_name="fast", role_overrides={
                "reviewer": {"model": "glm-5.2", "reasoning_effort": "high"},
            })
        self.assertEqual("fast", value["profile_name"])
        self.assertEqual("gpt-5.6-luna", value["roles"]["router"]["effective"]["model"])
        self.assertEqual("glm-5.2", value["roles"]["reviewer"]["effective"]["model"])
        self.assertEqual("openai-compatible-v1", value["roles"]["reviewer"]["runner_id"])

    def test_builtin_claude_code_profile_keeps_writes_on_the_sandboxed_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            value = resolve(
                None, workspace=Path(directory) / "repo", home=Path(directory) / "home",
                profile_name="claude-code",
            )
        self.assertEqual("claude-code", value["profile_name"])
        self.assertEqual("haiku", value["roles"]["router"]["effective"]["model"])
        self.assertEqual("gpt-5.6-luna", value["roles"]["implementer"]["effective"]["model"])
        self.assertEqual("codex-exec-v1", value["roles"]["implementer"]["runner_id"])
        self.assertEqual("opus", value["roles"]["adjudicator"]["effective"]["model"])
        self.assertEqual("claude-code-v1", value["roles"]["reviewer"]["runner_id"])

    def test_configured_haiku_alias_uses_the_claude_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(
                default="claude-code", profiles={"claude-code": claude_profile()}
            )), encoding="utf-8")
            value = resolve(path)

        self.assertEqual("haiku", value["roles"]["scout"]["effective"]["model"])
        self.assertEqual("claude-code-v1", value["roles"]["scout"]["runner_id"])

    def test_rejects_claude_as_an_implementer(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            invalid = claude_profile()
            invalid["implementer"] = {"model": "sonnet", "reasoning_effort": "high"}
            path.write_text(json.dumps(config(default="claude-code", profiles={"claude-code": invalid})), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "implementer"):
                resolve(path, profile_name="claude-code")

    def test_read_only_roles_do_not_receive_shell_access_for_either_cli_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "repo"
            home = Path(directory) / "home"
            codex = resolve(None, workspace=workspace, home=home)
            claude = resolve(None, workspace=workspace, home=home, profile_name="claude-code")

        for profiles in (codex, claude):
            for role in ("router", "scout", "specifier", "reviewer", "adjudicator"):
                self.assertFalse(profiles["roles"][role]["permissions"]["shell"])
            self.assertTrue(profiles["roles"]["implementer"]["permissions"]["shell"])

    def test_rejects_the_previous_fixed_pipeline_profile_and_requires_v4(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            value = config()
            value["schema_version"] = 3
            path.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "schema_version 4"):
                resolve(path)

    def test_project_overrides_user_and_unknown_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            project = root / "repo" / ".converge"
            home.mkdir()
            project.mkdir(parents=True)
            user_path = home / ".convergent-delivery" / "multi-model.json"
            user_path.parent.mkdir()
            user_path.write_text(json.dumps(config(profiles={"default": delivery_profile(router="gpt-5.6-luna")})), encoding="utf-8")
            project_path = project / "multi-model.json"
            project_path.write_text(json.dumps(config(profiles={"default": delivery_profile(router="gpt-5.6-terra")})), encoding="utf-8")
            value = resolve(None, workspace=root / "repo", home=home)
            with self.assertRaisesRegex(ValueError, "profile"):
                resolve(project_path, profile_name="missing")
        self.assertEqual(str(project_path.resolve()), value["config_source"])
        self.assertEqual("gpt-5.6-terra", value["roles"]["router"]["effective"]["model"])

    def test_rejects_invalid_audit_and_never_stores_a_glm_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={"default": delivery_profile(reviewer="glm-5.2")})), encoding="utf-8")
            result = audit_request(resolve(path), "Audit this diff")
            broken = config(profiles={"default": delivery_profile(reviewer="glm-5.2")})
            broken["profiles"]["default"]["reviewer"]["reasoning_effort"] = "xhigh"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reviewer model"):
                resolve(path)
        self.assertEqual("planned", result["launch"]["status"])
        self.assertEqual("diagnostic", result["status"])
        self.assertNotIn("Audit this diff", str(result))

    def test_missing_glm_credential_returns_a_receipt_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={"default": delivery_profile(reviewer="glm-5.2")})), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = audit_request(resolve(path), "Audit this diff", execute=True)
        self.assertEqual("missing_credential", result["receipt"]["error_type"])
        self.assertEqual("diagnostic", result["status"])
        self.assertIsNone(result["content"])

    def test_desktop_task_action_uses_the_frozen_implementer_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            profiles = resolve(None, workspace=Path(directory) / "repo", home=Path(directory) / "home")
            action = desktop_task_action(
                profiles, "Implement the bounded task.", project_id="project-1", title="Bridge task",
            )

        self.assertEqual("desktop-task-v1", action["adapter"])
        self.assertEqual("gpt-5.6-luna", action["arguments"]["model"])
        self.assertEqual("high", action["arguments"]["thinking"])
        self.assertEqual("requested", action["model_binding"]["status"])
        self.assertEqual(
            profiles["roles"]["implementer"]["profile_fingerprint"],
            action["model_binding"]["profile_fingerprint"],
        )

    def test_desktop_task_command_outputs_a_host_action_without_launching_a_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prompt = root / "prompt.txt"
            prompt.write_text("Implement the bounded task.", encoding="utf-8")
            output = io.StringIO()
            with patch.object(sys, "argv", [
                "multi_model.py", "desktop-task", "--workspace", str(root / "repo"),
                "--project-id", "project-1", "--title", "Bridge task", "--input", str(prompt),
            ]), redirect_stdout(output):
                main()

        action = json.loads(output.getvalue())
        self.assertEqual("create", action["kind"])
        self.assertEqual("gpt-5.6-luna", action["arguments"]["model"])


if __name__ == "__main__":
    unittest.main()
