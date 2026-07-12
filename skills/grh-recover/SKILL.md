---
name: grh-recover
entry_core_contract_version: 1
description: Use when work is interrupted, drifting, repeatedly failing, or blocked by conflicting evidence or an invalid route assumption.
---

# GRH Recover

触发：中断、漂移、重复失败、证据冲突或路线假设失效。

- 允许：诊断漂移、对账、提出新路线。
- 禁止：自动换路、自动串联下一入口。
- 停止：改变路线前等待用户确认。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；校验其 `SKILL.md` frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-recover --project <项目绝对路径>`，用户范围更窄时追加 `--requested-scope`。资格检查通过后只按主内核契约执行允许范围。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
