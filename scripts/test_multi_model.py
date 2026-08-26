#!/usr/bin/env python3
"""Tests for named and per-run multi-model delivery profiles."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multi_model import audit_request, resolve


def delivery_profile(*, router="gpt-5.6-terra", reviewer="gpt-5.6-terra"):
    return {
        "router": {"model": router, "reasoning_effort": "medium"},
        "scout": {"model": "gpt-5.6-terra", "reasoning_effort": "medium"},
        "specifier": {"model": "gpt-5.6-terra", "reasoning_effort": "high"},
        "implementer": {"model": "gpt-5.6-luna", "reasoning_effort": "high"},
        "reviewer": {"model": reviewer, "reasoning_effort": "high" if reviewer == "glm-5.2" else "high"},
        "adjudicator": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
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
        self.assertEqual("gpt-5.6-sol", value["roles"]["adjudicator"]["effective"]["model"])
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

    def test_builtin_claude_code_profile_uses_claude_model_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            value = resolve(
                None, workspace=Path(directory) / "repo", home=Path(directory) / "home",
                profile_name="claude-code",
            )
        self.assertEqual("claude-code", value["profile_name"])
        self.assertEqual("fable", value["roles"]["router"]["effective"]["model"])
        self.assertEqual("sonnet", value["roles"]["implementer"]["effective"]["model"])
        self.assertEqual("opus", value["roles"]["adjudicator"]["effective"]["model"])
        self.assertEqual("claude-code-v1", value["roles"]["reviewer"]["runner_id"])

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
        self.assertNotIn("Audit this diff", str(result))

    def test_missing_glm_credential_returns_a_receipt_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={"default": delivery_profile(reviewer="glm-5.2")})), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = audit_request(resolve(path), "Audit this diff", execute=True)
        self.assertEqual("missing_credential", result["receipt"]["error_type"])
        self.assertIsNone(result["content"])


if __name__ == "__main__":
    unittest.main()
