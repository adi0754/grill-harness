import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "skills" / "grill-harness" / "assets" / "templates"
REFERENCES = ROOT / "skills" / "grill-harness" / "references"
SCRIPTS = ROOT / "skills" / "grill-harness" / "scripts"
MAIN_SKILL = ROOT / "skills" / "grill-harness" / "SKILL.md"
ACCEPTANCE_PROMPT = ROOT / "docs" / "acceptance-prompt-v2.md"
sys.path.insert(0, str(SCRIPTS))

import state
import task_graph


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
        "需求雷达.md",
        "问题与发现.yaml",
        "相似实现对照.md",
        "需求调查任务.md",
        "知识条目.yaml",
        "学习草稿.md",
        "知识变更预览.md",
    }

    def read(self, name):
        return (TEMPLATES / name).read_text(encoding="utf-8")

    def load_json_yaml(self, name):
        return json.loads(self.read(name))

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
        records = self.load_json_yaml("决策账本.yaml")["records"]
        state.validate_ledger(records)
        expected_non_radar = [
            state.create_ledger_record(prefix, 1, {"summary": ""})
            for prefix in state.LEDGER_RECORD_TYPES
            if prefix != "RAD"
        ]
        self.assertEqual(
            [record for record in records if record["type"] != "RAD"],
            expected_non_radar,
        )
        radar = next(record for record in records if record["type"] == "RAD")
        self.assertEqual(radar["id"], "RAD-001")
        task = self.read("实施任务.md")
        for field in (
            "角色与目标", "项目工作目录", "Git 基线", "输入产物", "相关需求与决策",
            "已确认仓库事实", "允许修改范围", "禁止修改范围", "工作步骤",
            "测试与证据", "验收标准", "停止条件", "输出路径", "输出格式",
        ):
            self.assertIn(field, task)

    def test_task_graph_template_is_consumable_by_all_task_graph_apis(self):
        tasks = self.load_json_yaml("任务图.yaml")["tasks"]
        required = {
            "id", "status", "currentness", "depends_on", "blockers", "write_paths",
            "shared_contracts", "migrations", "generated_files", "worktree", "branch",
            "acceptance_ids", "git_baseline", "task_package_path",
            "startup_prompt_path", "output_path",
            "review_required", "review", "review_history",
        }
        self.assertTrue(required.issubset(tasks[0]))
        self.assertTrue(task_graph.validate_dag(tasks)["valid"])
        self.assertEqual(task_graph.calculate_frontier(tasks)["frontier"], ["TASK-001"])

        peer = dict(tasks[0])
        peer.update({
            "id": "TASK-002", "write_paths": ["src/peer"],
            "worktree": "/absolute/worktrees/TASK-002", "branch": "task/TASK-002",
        })
        report = task_graph.analyze_task_conflict(tasks[0], peer)
        self.assertTrue(report["parallel_candidate"])
        self.assertTrue(report["executable_parallel"])

    def test_role_tasks_require_absolute_local_paths_outputs_and_stop_conditions(self):
        for name in ("实施任务.md", "审查任务.md", "修复任务.md", "集成任务.md", "验收任务.md"):
            text = self.read(name)
            self.assertIn("绝对路径", text, name)
            self.assertIn("输入产物（逐项绝对路径与版本/基线）", text, name)
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

    def test_main_skill_does_not_merge_or_preapprove_lightweight_gates(self):
        text = MAIN_SKILL.read_text(encoding="utf-8")
        self.assertIn("三个用户硬门禁", text)
        self.assertIn("仍分别批准", text)
        self.assertNotIn("可合并为一次明确授权", text)
        self.assertIn("预批", text)

    def test_acceptance_prompt_isolates_python_and_runtime_writes(self):
        text = ACCEPTANCE_PROMPT.read_text(encoding="utf-8")
        for marker in (
            "ACCEPT_TMP=$(mktemp -d",
            'export HOME="$ACCEPT_TMP/home"',
            'export CODEX_HOME="$ACCEPT_TMP/codex-home"',
            'export XDG_CONFIG_HOME="$ACCEPT_TMP/xdg-config"',
            'export XDG_DATA_HOME="$ACCEPT_TMP/xdg-data"',
            'export GRILL_HARNESS_TEST_ROOT="$ACCEPT_TMP/runtime"',
            'export PYTHONPYCACHEPREFIX="$ACCEPT_TMP/pycache"',
        ):
            self.assertIn(marker, text)

    def test_v2_workflow_references_document_the_enforced_runtime_contract(self):
        state_machine = (REFERENCES / "工作流状态机.md").read_text(encoding="utf-8")
        stage = (REFERENCES / "阶段执行协议.md").read_text(encoding="utf-8")
        artifacts = (REFERENCES / "文档与产物契约.md").read_text(encoding="utf-8")
        assurance = (REFERENCES / "测试与验收.md").read_text(encoding="utf-8")

        self.assertIn("自适应需求雷达", state_machine)
        self.assertLess(state_machine.index("自适应需求雷达"), state_machine.index("需求基线"))
        self.assertIn("三个门禁仍分别批准", state_machine)
        self.assertNotIn("将三者合并为一次明确授权", state_machine)
        self.assertIn("`design` 或 `repository_challenge`", state_machine)
        self.assertIn("研究/原型产物不得标记为机器 phase", state_machine)
        self.assertIn("也不得把所属必需 phase 标记为 `skipped`", state_machine)
        self.assertNotIn("研究与原型**：仅在所选路线依赖未验证事实时进入，可跳过", state_machine)

        for marker in (
            "需求雷达.md",
            "问题与发现.yaml",
            "相似实现对照.md",
            "用户选择调查 Agent",
            "不得自动串联",
            "最终规格批准后生成执行 Frontier 并停止",
            "grh-run",
            "grh-check",
        ):
            self.assertIn(marker, stage)

        for marker in (
            "过程产物/需求审问/需求雷达.md",
            "过程产物/需求审问/问题与发现.yaml",
            "过程产物/需求审问/相似实现对照.md",
            "过程产物/学习草稿/",
            "知识库/项目知识/",
            "知识库/通用知识/",
            "failures.yaml",
            "review_history",
        ):
            self.assertIn(marker, artifacts)

        for failure_class in (
            "implementation_failure",
            "route_failure",
            "evidence_failure",
            "workflow_integrity_failure",
        ):
            self.assertIn(failure_class, assurance)
        self.assertIn("第三次", assurance)
        self.assertIn("failure-record", assurance)
        self.assertIn("review_history", assurance)
        self.assertIn("可选建议", assurance)
        self.assertIn("失败或无法验证的工作流只保留真实结论", assurance)
        self.assertIn("不得完成正式归档", assurance)
        self.assertIn("仅确认的 `route_failure`", assurance)
        self.assertIn("项目级失败事实", assurance)
        self.assertIn("不能完成 `knowledge_archive`", assurance)

    def test_readme_documents_all_entries_verified_install_and_knowledge_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        for entry in (
            "grill-harness",
            "grh-start",
            "grh-plan",
            "grh-run",
            "grh-check",
            "grh-recover",
            "grh-learn",
            "grh-upstream-check",
        ):
            self.assertIn(entry, readme)
        self.assertIn("-s '*'", readme)
        self.assertIn("缺少主内核", readme)
        self.assertIn("knowledge-query", readme)
        self.assertIn("knowledge-draft", readme)
        self.assertIn("knowledge-promote", readme)
        self.assertIn("项目知识", readme)
        self.assertIn("通用知识", readme)
        self.assertIn("只读", readme)
        self.assertIn("不会安装或更新", readme)
        self.assertNotIn("合并三个门禁", readme)

    def test_route_card_stops_before_selection_and_repository_challenge_is_conclusive(self):
        route = self.read("路线卡.md")
        self.assertIn("选择前停止", route)
        self.assertIn("不得生成完整规格", route)
        challenge = self.read("仓库挑战.md")
        for conclusion in ("成立", "部分成立", "不成立", "遗漏", "需要用户决策", "无法验证"):
            self.assertIn(conclusion, challenge)
        self.assertIn("真实路径", challenge)
        self.assertIn("符号", challenge)

    def test_requirements_radar_templates_preserve_blockers_and_traceability(self):
        radar = self.read("需求雷达.md")
        for category in ("需求澄清", "需求遗漏", "需求牵连", "需求悖论", "相似实现"):
            self.assertIn(category, radar)
        for term in ("RAD-001", "低", "中", "高", "需求基线"):
            self.assertIn(term, radar)

        findings = self.load_json_yaml("问题与发现.yaml")
        self.assertEqual(findings["records"][0]["id"], "RAD-001")
        self.assertEqual(findings["records"][0]["blocking_level"], "baseline")

        analogue = self.read("相似实现对照.md")
        for field in (
            "路径", "符号", "相同点", "差异点", "可复用点", "不可复用原因",
            "公共契约", "可复用测试", "新增行为", "搜索范围", "查询依据",
        ):
            self.assertIn(field, analogue)

        investigation = self.read("需求调查任务.md")
        for field in ("调查理由", "调查问题", "角色", "预期产物", "是否阻塞需求基线"):
            self.assertIn(field, investigation)
        self.assertIn("用户选择", investigation)

        baseline = self.read("需求基线.md")
        for field in ("关联需求雷达", "阻塞项已清零", "规格前验证项"):
            self.assertIn(field, baseline)

    def test_review_has_independent_standards_and_spec_axes(self):
        review = self.read("审查任务.md")
        self.assertIn("Standards", review)
        self.assertIn("Spec", review)
        self.assertIn("完整文件", review)
        self.assertIn("真实 diff", review)

    def test_knowledge_templates_capture_boundaries_evidence_and_explicit_promotion(self):
        record = self.load_json_yaml("知识条目.yaml")
        self.assertEqual(record["id"], "KNW-001")
        for field in (
            "conclusion", "type", "applicability", "non_applicability", "evidence",
            "trust_status", "source_workflow", "formed_at", "invalidation_condition",
            "replaced_by",
        ):
            self.assertIn(field, record)

        draft = self.read("学习草稿.md")
        self.assertIn("暂定", draft)
        self.assertIn("过程产物/学习草稿", draft)

        preview = self.read("知识变更预览.md")
        for field in (
            "preview_id", "新增", "去重", "冲突", "replaced_by", "用户批准",
            "通用知识第二批准", "DEC-*", "knowledge-promote --preview",
        ):
            self.assertIn(field, preview)

        experience = self.read("项目经验.md")
        for field in ("最终目标和结果", "重要审查发现", "未解决", "可复用经验", "下次应避免"):
            self.assertIn(field, experience)
        self.assertIn("不保存完整对话", experience)

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
