import json
import tempfile
import unittest
from abc import ABC, abstractmethod
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import skillopt_adapter


class EnvContract(ABC):
    @abstractmethod
    def build_train_env(self, batch_size, seed, **kwargs): pass
    @abstractmethod
    def build_eval_env(self, env_num, split, seed, **kwargs): pass
    @abstractmethod
    def rollout(self, env_manager, skill_content, out_dir, **kwargs): pass
    @abstractmethod
    def get_task_types(self): pass
    def setup(self, cfg): self._cfg = dict(cfg)
    def reflect(self, *args, **kwargs): return "inherited"


class SkillOptAdapterTest(unittest.TestCase):
    def adapter(self, **kwargs):
        with patch.dict("sys.modules", {"skillopt.envs.base": SimpleNamespace(EnvAdapter=EnvContract)}):
            return skillopt_adapter.adapter_class()(**kwargs)

    def test_optional_dependency_is_not_silently_faked(self):
        with patch.dict("sys.modules", {"skillopt.envs.base": None}):
            with self.assertRaisesRegex(RuntimeError, "SkillOpt"):
                skillopt_adapter.adapter_class()

    def test_adapter_implements_real_contract_and_separates_splits(self):
        adapter = self.adapter()
        self.assertEqual("inherited", adapter.reflect([], "policy", "/tmp"))
        train = adapter.build_train_env(3, 42)
        heldout = adapter.build_eval_env(3, "valid_unseen", 42)
        self.assertTrue(set(train).isdisjoint(heldout))
        self.assertEqual(set(skillopt_adapter.HELD_OUT), set(heldout))
        self.assertTrue(adapter.get_task_types())
        with self.assertRaises(ValueError): adapter.build_train_env(0, 42)
        with self.assertRaises(ValueError): adapter.build_eval_env(1, "unknown", 42)

    def test_real_host_execution_is_opt_in(self):
        adapter = self.adapter()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "allow_execute"):
                adapter.rollout(["review-defect"], "policy", directory)

    def test_invalid_batch_and_timeout_do_not_launch_host(self):
        for options, batch in (({}, []), ({}, ["unknown"]), ({"exec_timeout": float("nan")}, ["review-defect"]),
                               ({"exec_timeout": 0}, ["review-defect"])):
            adapter = self.adapter(allow_execute=True, **options)
            with patch.object(skillopt_adapter, "CodexSession") as session, self.assertRaises(ValueError):
                adapter.rollout(batch, "policy", "/tmp")
            session.assert_not_called()

    def test_rollout_scores_frozen_evidence_and_persists_only_synthetic_trajectory(self):
        adapter = self.adapter(allow_execute=True)
        observed = {"result": "pass", "automatic_repairs": 1,
                    "synthetic_trajectory": [{"role": "assistant", "content": "synthetic result"}]}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(skillopt_adapter, "CodexSession"), \
                patch.object(skillopt_adapter, "replay", return_value=observed):
            rows = adapter.rollout(["review-defect"], "candidate", directory)
            path = Path(directory) / "predictions" / rows[0]["id"] / "conversation.json"
            self.assertEqual(observed["synthetic_trajectory"], json.loads(path.read_text()))
            evidence = json.loads(path.with_name("result.json").read_text())
            self.assertEqual("pass", evidence["result"])
            self.assertNotIn("synthetic_trajectory", evidence)
        self.assertEqual(0, rows[0]["hard"])
        self.assertEqual("controller_repair_required", rows[0]["fail_reason"])
        self.assertEqual(0.5, rows[0]["soft"])

    def test_direct_success_and_expected_budget_stop_pass_hard_gate(self):
        adapter = self.adapter(allow_execute=True)
        for case, result, repairs in (("review-defect", "pass", 0), ("no-progress", "blocked", 1)):
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(skillopt_adapter, "CodexSession"), \
                    patch.object(skillopt_adapter, "replay", return_value={"result": result, "automatic_repairs": repairs}):
                self.assertEqual(1, adapter.rollout([case], "policy", directory)[0]["hard"])

    def test_uncovered_host_cannot_be_scored_as_success(self):
        adapter = self.adapter(allow_execute=True)
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(skillopt_adapter, "CodexSession"), \
                patch.object(skillopt_adapter, "replay", return_value={"result": "uncovered"}):
            with self.assertRaisesRegex(ValueError, "uncovered"):
                adapter.rollout(["review-defect"], "candidate", directory)


if __name__ == "__main__":
    unittest.main()
