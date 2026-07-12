---
name: grh-upstream-check
entry_core_contract_version: 1
description: Use when checking required capabilities, upstream skill changes, or entry-core compatibility without installing or updating anything.
---

# GRH Upstream Check

触发：检查依赖、上游变化或入口—内核兼容性。

- 允许：检查依赖、比较上游、兼容性判断。
- 禁止：安装、更新、接受上游变化、自动串联下一入口。
- 停止：给出只读兼容性报告和建议后停止。

先通过 Agent Skill 元数据、`npx skills list --json` / `npx skills list -g --json` 和真实安装目录发现名为 `grill-harness` 的主内核；校验其 `SKILL.md` frontmatter、`scripts/grh.py` 与 `references/入口内核契约.json`。不要假设主内核位于固定兄弟目录。

找到内核后运行 `python3 <主内核>/scripts/grh.py entry-check --entry grh-upstream-check --project <项目绝对路径>`，用户范围更窄时追加 `--requested-scope`。资格检查通过后只按主内核契约执行允许范围。

缺少 grill-harness 主内核时失败关闭，不创建 `~/.grill-harness/`，并建议完整安装：`npx skills add <Grill-Harness仓库或URL> -g -a codex claude-code -s '*' -y --copy`。契约不兼容、入口不完整或 `entry-check` 非零退出时原样报告并停止。
