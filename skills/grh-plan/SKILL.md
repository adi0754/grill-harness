---
name: grh-plan
entry_core_contract_version: 1
description: Use when a route is chosen and the work needs research, prototypes, repository challenge, a final specification, or vertical execution slices.
---

# GRH Plan

触发：路线已选，需要调研、原型、仓库挑战、最终规格或垂直切片。

- 允许：调研、原型、仓库挑战、编写规格、拆分任务。
- 禁止：实施、最终验收、自动串联下一入口。
- 停止：等待最终规格批准；批准后生成执行 Frontier 并停止。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；完整读取其 `SKILL.md`，并校验 frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-plan --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`，用户范围更窄时追加 `--requested-scope`。项目存在多个工作流时必须显式传 `--workflow`，先用 `status`/`overview` 列出候选并让用户选择，不得替用户猜测。资格检查通过后只按主内核契约执行允许范围。

最终规格必须包含外部依赖表，将每项外部合同标为 `verified`、`provisional` 或 `blocked`；所有 `provisional`/`blocked` 项都登记 `blocking_level: implementation` 的 `RAD-*`。等待最终规格批准时，先用 30 秒结论说明所选路线、仓库挑战结论、关键未验证假设和验证边界，再逐条点名未验证外部合同及风险，明确告诉用户正在回答“这份实施合同是否足以授权写代码”。不得只展示 `final_spec_approval`、产物版本或批准命令而不解释授权含义。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
