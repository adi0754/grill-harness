---
name: grh-check
entry_core_contract_version: 1
description: Use when implementation needs independent review, integration checking, final acceptance, or an evidence-based release decision.
---

# GRH Check

触发：需要独立审查、集成检查、最终验收或发布判断。

- 允许：审查、集成检查、最终验收。
- 禁止：实施、修复、切换路线、自动串联下一入口。
- 停止：只依据当前证据给出验收结论后停止。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；完整读取其 `SKILL.md`，并校验 frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-check --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`，用户范围更窄时追加 `--requested-scope`。项目存在多个工作流时必须显式传 `--workflow`，先用 `status`/`overview` 列出候选并让用户选择，不得替用户猜测。资格检查通过后只按主内核契约执行允许范围。

验收是用户的决定。给出“有条件通过”或存在未解决限制时，按主内核“用户决策协议”逐条讲清限制与代价，一次只问一个需要用户拍板的问题并附推荐答案，再等待最终验收决定。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
