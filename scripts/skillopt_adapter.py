"""Optional SkillOpt EnvAdapter for explicit, synthetic Converge experiments.

Importing this module never loads SkillOpt or launches a model. Register the class
returned by adapter_class() in SkillOpt's two CLI registries for an offline run.
"""

import json
import random
import tempfile
import time
from pathlib import Path

from host_bridge import CodexSession
from interaction_replay import CASES, replay


TRAIN = ("review-defect", "known-decision")
HELD_OUT = ("clean-review", "new-decision", "no-progress")


def adapter_class():
    try:
        from skillopt.envs.base import EnvAdapter
    except ImportError as error:
        raise RuntimeError("SkillOpt is not installed; install/register it only for an explicitly requested experiment") from error

    class ConvergeAdapter(EnvAdapter):
        def __init__(self, *, allow_execute=False, codex_bin="codex", model="gpt-6.1-sol",
                     exec_timeout=300, analyst_workers=1, failure_only=True, minibatch_size=1, edit_budget=1):
            self.allow_execute, self.codex_bin, self.model = allow_execute, codex_bin, model
            self.exec_timeout = exec_timeout
            self.analyst_workers, self.failure_only = analyst_workers, failure_only
            self.minibatch_size, self.edit_budget = minibatch_size, edit_budget

        def _batch(self, cases, count, seed):
            if type(count) is not int or not 1 <= count <= 3:
                raise ValueError("offline batch size must be 1..3")
            rng = random.Random(seed)
            ordered = list(cases)
            rng.shuffle(ordered)
            return [ordered[index % len(ordered)] for index in range(count)]

        def build_train_env(self, batch_size, seed, **kwargs):
            return self._batch(TRAIN, batch_size, seed)

        def build_eval_env(self, env_num, split, seed, **kwargs):
            if split not in {"valid_seen", "valid_unseen", "test"}:
                raise ValueError("invalid offline split")
            return self._batch(TRAIN if split == "valid_seen" else HELD_OUT, env_num, seed)

        def get_task_types(self):
            return list(CASES)

        def rollout(self, env_manager, skill_content, out_dir, **kwargs):
            if self.allow_execute is not True:
                raise ValueError("offline rollout requires allow_execute=true")
            if not isinstance(env_manager, list) or not 1 <= len(env_manager) <= 3 \
                    or any(case not in CASES for case in env_manager):
                raise ValueError("invalid offline batch")
            if type(self.exec_timeout) not in (int, float) or not 0 < self.exec_timeout <= 600:
                raise ValueError("offline total timeout must be in (0, 600]")
            deadline = time.monotonic() + self.exec_timeout
            rows = []
            for index, case in enumerate(env_manager):
                with tempfile.TemporaryDirectory(prefix="converge-skillopt-") as directory:
                    session = CodexSession(directory, skill_content, codex_bin=self.codex_bin,
                                           model=self.model, deadline=deadline)
                    result = replay(case, Path(directory), session, controlled=True, capture_synthetic=True)
                if result["result"] == "uncovered":
                    raise ValueError("offline host evidence is uncovered; do not train on this batch")
                expected = "blocked" if case == "no-progress" else "pass"
                success = int(result["result"] == expected)
                repaired = case != "no-progress" and result.get("automatic_repairs", 0) > 0
                hard = int(success and not repaired)
                identifier = f"{case}-{index}"
                path = Path(out_dir) / "predictions" / identifier / "conversation.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result.get("synthetic_trajectory", []), ensure_ascii=False))
                path.with_name("result.json").write_text(json.dumps(
                    {key: value for key, value in result.items() if key != "synthetic_trajectory"},
                    ensure_ascii=False))
                rows.append({"id": identifier, "task_type": case, "task_description": case,
                             "hard": hard, "soft": success / (1 + result.get("automatic_repairs", 0)),
                             "fail_reason": "" if hard else "controller_repair_required" if repaired
                             else result.get("reason", "behavior_failed")})
            return rows

    return ConvergeAdapter
