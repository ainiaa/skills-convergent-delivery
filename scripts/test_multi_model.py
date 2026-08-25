#!/usr/bin/env python3
"""Tests for named and per-run multi-model delivery profiles."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from multi_model import audit_request, resolve


def delivery_profile(*, design="gpt-5.6-sol", implementation="gpt-5.6-luna", audit="gpt-5.6-terra"):
    return {
        "design": {"model": design, "reasoning_effort": "high"},
        "design_review": {"model": "gpt-5.6-terra", "reasoning_effort": "xhigh"},
        "implementation": {"model": implementation, "reasoning_effort": "max"},
        "audit": {"model": audit, "reasoning_effort": "high" if audit == "glm-5.2" else "xhigh"},
    }


def config(*, default="default", profiles=None):
    return {"schema_version": 3, "default_profile": default, "profiles": profiles or {"default": delivery_profile()}}


class MultiModelTest(unittest.TestCase):
    def test_default_profile_is_the_requested_sol_luna_terra_sequence(self):
        with tempfile.TemporaryDirectory() as directory:
            value = resolve(None, workspace=Path(directory) / "repo", home=Path(directory) / "home")
        self.assertEqual("default", value["profile_name"])
        self.assertEqual("gpt-5.6-sol", value["design"]["effective"]["model"])
        self.assertEqual("gpt-5.6-terra", value["design_review"]["effective"]["model"])
        self.assertEqual("gpt-5.6-luna", value["implementation"]["effective"]["model"])
        self.assertEqual("max", value["implementation"]["effective"]["reasoning_effort"])
        self.assertEqual("gpt-5.6-terra", value["audit"]["effective"]["model"])
        self.assertEqual("codex-exec-v1", value["audit"]["runner_id"])

    def test_selects_named_profile_and_allows_per_run_role_override(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={
                "default": delivery_profile(),
                "fast": delivery_profile(design="gpt-5.6-terra", implementation="gpt-5.6-luna"),
            })), encoding="utf-8")
            value = resolve(path, profile_name="fast", role_overrides={
                "audit": {"model": "glm-5.2", "reasoning_effort": "high"},
            })
        self.assertEqual("fast", value["profile_name"])
        self.assertEqual("gpt-5.6-terra", value["design"]["effective"]["model"])
        self.assertEqual("glm-5.2", value["audit"]["effective"]["model"])
        self.assertEqual("openai-compatible-v1", value["audit"]["runner_id"])

    def test_project_overrides_user_and_unknown_profile_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "home"
            project = root / "repo" / ".converge"
            home.mkdir()
            project.mkdir(parents=True)
            user_path = home / ".convergent-delivery" / "multi-model.json"
            user_path.parent.mkdir()
            user_path.write_text(json.dumps(config(profiles={"default": delivery_profile(design="gpt-5.6-luna")})), encoding="utf-8")
            project_path = project / "multi-model.json"
            project_path.write_text(json.dumps(config(profiles={"default": delivery_profile(design="gpt-5.6-terra")})), encoding="utf-8")
            value = resolve(None, workspace=root / "repo", home=home)
            with self.assertRaisesRegex(ValueError, "profile"):
                resolve(project_path, profile_name="missing")
        self.assertEqual(str(project_path.resolve()), value["config_source"])
        self.assertEqual("gpt-5.6-terra", value["design"]["effective"]["model"])

    def test_rejects_invalid_audit_and_never_stores_a_glm_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={"default": delivery_profile(audit="glm-5.2")})), encoding="utf-8")
            result = audit_request(resolve(path), "Audit this diff")
            broken = config(profiles={"default": delivery_profile(audit="glm-5.2")})
            broken["profiles"]["default"]["audit"]["reasoning_effort"] = "xhigh"
            path.write_text(json.dumps(broken), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "audit model"):
                resolve(path)
        self.assertEqual("planned", result["launch"]["status"])
        self.assertNotIn("Audit this diff", str(result))

    def test_missing_glm_credential_returns_a_receipt_without_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "multi-model.json"
            path.write_text(json.dumps(config(profiles={"default": delivery_profile(audit="glm-5.2")})), encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                result = audit_request(resolve(path), "Audit this diff", execute=True)
        self.assertEqual("missing_credential", result["receipt"]["error_type"])
        self.assertIsNone(result["content"])


if __name__ == "__main__":
    unittest.main()
