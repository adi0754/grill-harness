import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "skills" / "grill-harness" / "assets" / "templates"
REFERENCES = ROOT / "skills" / "grill-harness" / "references"


class TemplateContractTests(unittest.TestCase):
    TEMPLATE_NAMES = {
        "需求基线.md",
        "决策账本.yaml",
        "路线卡.md",
        "仓库挑战.md",
        "规格.md",
        "任务图.yaml",
        "实施任务.md",
        "审查任务.md",
        "修复任务.md",
        "集成任务.md",
        "验收任务.md",
        "项目经验.md",
    }

    def read(self, name):
        return (TEMPLATES / name).read_text(encoding="utf-8")

    def test_all_focused_templates_and_references_exist(self):
        self.assertEqual({path.name for path in TEMPLATES.glob("*")}, self.TEMPLATE_NAMES)
        for name in (
            "工作流状态机.md",
            "文档与产物契约.md",
            "角色任务协议.md",
            "Codex运行时.md",
            "Claude-Code运行时.md",
            "测试与验收.md",
        ):
            self.assertTrue((REFERENCES / name).is_file(), name)

    def test_machine_records_use_stable_ascii_ids_and_required_fields(self):
        ledger = self.read("决策账本.yaml")
        for prefix in ("REQ", "DEC", "CON", "RISK", "CHG", "TASK", "ISSUE", "EVD"):
            self.assertRegex(ledger, rf"{prefix}-[0-9]{{3}}")
        task = self.read("实施任务.md")
        for field in (
            "角色与目标", "项目工作目录", "Git 基线", "必须读取", "相关需求与决策",
            "已确认仓库事实", "允许修改范围", "禁止修改范围", "工作步骤",
            "测试与证据", "验收标准", "停止条件", "输出路径", "输出格式",
        ):
            self.assertIn(field, task)

    def test_role_tasks_require_absolute_local_paths_outputs_and_stop_conditions(self):
        for name in ("实施任务.md", "审查任务.md", "修复任务.md", "集成任务.md", "验收任务.md"):
            text = self.read(name)
            self.assertIn("绝对路径", text, name)
            self.assertIn("输出路径", text, name)
            self.assertIn("停止条件", text, name)
            self.assertNotIn("完整聊天历史", text.replace("不得读取完整聊天历史", ""), name)

    def test_modes_and_three_human_gates_are_explicit(self):
        text = (REFERENCES / "工作流状态机.md").read_text(encoding="utf-8")
        for mode in ("轻量模式", "标准模式", "Wayfinding 模式"):
            self.assertIn(mode, text)
        for gate in ("requirements_baseline", "route_selection", "final_spec_approval"):
            self.assertIn(gate, text)
        self.assertIn("不得零确认编码", text)
        self.assertIn("每个新会话只解决一个调查或决策问题", text)

    def test_route_card_stops_before_selection_and_repository_challenge_is_conclusive(self):
        route = self.read("路线卡.md")
        self.assertIn("选择前停止", route)
        self.assertIn("不得生成完整规格", route)
        challenge = self.read("仓库挑战.md")
        for conclusion in ("成立", "部分成立", "不成立", "遗漏", "需要用户决策", "无法验证"):
            self.assertIn(conclusion, challenge)
        self.assertIn("真实路径", challenge)
        self.assertIn("符号", challenge)

    def test_review_has_independent_standards_and_spec_axes(self):
        review = self.read("审查任务.md")
        self.assertIn("Standards", review)
        self.assertIn("Spec", review)
        self.assertIn("完整文件", review)
        self.assertIn("真实 diff", review)

    def test_local_runtime_prompts_are_short_and_not_web_portable_templates(self):
        protocol = (REFERENCES / "角色任务协议.md").read_text(encoding="utf-8")
        self.assertIn("本地启动提示词", protocol)
        self.assertIn("读取任务包", protocol)
        self.assertIn("检查真实仓库", protocol)
        self.assertIn("写回报告", protocol)
        self.assertIn("不得附带原始聊天历史", protocol)
        self.assertIn("不生成网页模型便携提示词", protocol)
        names = {path.name.lower() for path in TEMPLATES.glob("*")}
        self.assertFalse(any("prompt" in name or "提示词" in name or "web" in name for name in names))


if __name__ == "__main__":
    unittest.main()
