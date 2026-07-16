---
name: grh-learn
entry_core_contract_version: 1
description: Use when searching prior experience, conducting a retrospective, or archiving accepted project knowledge with explicit confirmation.
---

# GRH Learn

触发：查找经验、复盘或正式归档已验收项目知识。

- 允许：只读查经验、复盘；满足验收和确认门禁后归档知识。
- 禁止：实施、自动串联下一入口；未经确认写入长期知识。
- 停止：长期知识写入前等待用户确认。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；完整读取其 `SKILL.md`，并校验 frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-learn --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`，用户范围更窄时追加 `--requested-scope`。项目存在多个工作流时必须显式传 `--workflow`，先用 `status`/`overview` 列出候选并让用户选择，不得替用户猜测。资格检查通过后只按主内核契约执行允许范围。

学习草稿提升为项目知识、项目知识晋升为通用知识是两次独立的用户决定：按主内核“用户决策协议”分别单独确认，不合并提问、不预设同意。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
