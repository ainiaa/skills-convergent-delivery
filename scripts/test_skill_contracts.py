import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        raise AssertionError(f"missing frontmatter: {path}")
    return text, match.group(1)


class SkillContractTest(unittest.TestCase):
    def test_three_skills_have_distinct_names_and_triggers(self):
        paths = {
            "converge": ROOT / "SKILL.md",
            "converge-review": ROOT / "skills/converge-review/SKILL.md",
            "converge-batch": ROOT / "skills/converge-batch/SKILL.md",
        }
        descriptions = {}
        for name, path in paths.items():
            text, header = frontmatter(path)
            self.assertIn(f"name: {name}", header)
            description = next(line for line in header.splitlines() if line.startswith("description:"))
            descriptions[name] = description
            self.assertGreater(len(text), len(header))

        self.assertIn("implement", descriptions["converge"].lower())
        self.assertIn("read-only", descriptions["converge-review"].lower())
        self.assertIn("batch", descriptions["converge-batch"].lower())

    def test_root_skill_no_longer_owns_plan_or_review_modes(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertNotIn("使用 `plan`", text)
        self.assertNotIn("使用 `review`", text)
        self.assertIn("converge-review", text)
        self.assertIn("converge-batch", text)
        self.assertIn('"$CONVERGE_SKILL_DIR/scripts/delivery_engine.py"', text)

    def test_activation_is_discoverable_but_never_edits_user_configuration(self):
        skill, header = frontmatter(ROOT / "SKILL.md")
        activation = (ROOT / "references/activation.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents/openai.yaml").read_text(encoding="utf-8")
        for marker in ("实现", "修复", "重构", "按方案修改", "修复已知问题"):
            self.assertIn(marker, header)
        self.assertIn("references/activation.md", skill)
        self.assertIn("AGENTS.md", activation)
        self.assertIn("不自动修改", activation)
        self.assertIn("allow_implicit_invocation: true", metadata)

    def test_review_skill_is_read_only_and_freshness_bound(self):
        skill = (ROOT / "skills/converge-review/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "skills/converge-review/references/review-contract.md").read_text(
            encoding="utf-8"
        )
        for marker in ("只读", "不得修改", "source_fingerprint", "independent"):
            self.assertIn(marker, skill + contract)
        for marker in ("intent", "blind", "finding", "closure"):
            self.assertIn(marker, contract)

    def test_batch_skill_is_scheduler_only_and_has_full_contract(self):
        skill = (ROOT / "skills/converge-batch/SKILL.md").read_text(encoding="utf-8")
        contract = (ROOT / "skills/converge-batch/references/batch-contract.md").read_text(
            encoding="utf-8"
        )
        runtime = (ROOT / "skills/converge-batch/references/runtime-adapters.md").read_text(
            encoding="utf-8"
        )
        for marker in ("不读取业务代码", "不做代码评审", "$converge", "预检"):
            self.assertIn(marker, skill)
        self.assertIn('"$CONVERGE_BATCH_SKILL_DIR/scripts/batch_state.py"', skill)
        self.assertIn("runtime-adapters.md", skill)
        for marker in (
            "dispatch_id",
            "context capsule",
            "receipt",
            "final_acceptance",
            "pause",
            "resume",
            "stop",
        ):
            self.assertIn(marker, contract)
        for marker in (
            "Codex",
            "Claude Code",
            "worker_ref",
            "先查询原任务",
            "不重复派发",
            "手工交接",
        ):
            self.assertIn(marker, runtime)


if __name__ == "__main__":
    unittest.main()
