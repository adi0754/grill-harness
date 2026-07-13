---
name: grh-start
entry_core_contract_version: 1
description: Use when starting or aligning substantial software work, clarifying requirements, establishing a requirements baseline, or choosing a route before detailed planning.
---

# GRH Start

触发：开始新工作、澄清需求、建立需求基线或选择路线。

- 允许：仓库侦察、需求澄清、需求基线、路线选择。
- 禁止：实施、最终验收、自动串联下一入口。
- 停止：用户选择路线后停止。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；完整读取其 `SKILL.md`，并校验 frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-start --project <项目绝对路径>`，用户范围更窄时追加 `--requested-scope`。资格检查通过后只按主内核契约执行允许范围。

执行需求雷达和需求基线时，读取主内核 `references/阶段执行协议.md` 的“面向用户的沟通协议”和“自适应需求雷达”。先用“谁要什么、遗漏什么、牵连哪里、哪里冲突、哪些先例能复用”五个自然语言问题汇报，再给 `RAD-*`、路径和机器状态；需求基线与路线选择门禁必须说明用户正在回答的真实问题。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
