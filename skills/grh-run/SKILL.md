---
name: grh-run
entry_core_contract_version: 1
description: Use when an approved final specification is ready for task packaging, implementation, or evidence-driven repair loops.
---

# GRH Run

触发：最终规格已批准，需要任务包、实施或修复循环。

- 允许：任务拆分、实施、修复。
- 禁止：切换路线、最终验收、自动串联下一入口。
- 停止：最终验收前停止；路线问题转由用户选择 `grh-recover`。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；完整读取其 `SKILL.md`，并校验 frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-run --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`，用户范围更窄时追加 `--requested-scope`。项目存在多个工作流时必须显式传 `--workflow`，先用 `status`/`overview` 列出候选并让用户选择，不得替用户猜测。资格检查通过后只按主内核契约执行允许范围。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
