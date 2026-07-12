# Grill Harness

面向 Codex 与 Claude Code 的单入口、可恢复软件工程工作流 Skill。它按角色组织需求澄清、路线选择、仓库挑战、拆分、实施、审查、修复、集成和验收；用户自行选择每个角色使用的模型或 Agent。

工作流事实来自本地文件和真实仓库，不依赖长对话记忆。只发布一个公开 Skill：`grill-harness`。

## 安装

依赖 Node.js、`npx` 和只使用标准库的 Python 3。先安装必需能力：

```bash
npx skills add mattpocock/skills -g -a codex claude-code -s grilling domain-modeling codebase-design -y --copy
```

从本仓库根目录安装 Grill Harness：

```bash
npx skills add "$PWD" -g -a codex claude-code -s grill-harness -y --copy
```

以上依赖安装与本地仓库安装命令已在隔离 HOME 中验证。当前 `skills` CLI 会把 canonical 副本安装到 `~/.agents/skills/grill-harness`，并为 Claude Code 建立 `~/.claude/skills/grill-harness` 入口。

安装只复制 Skill，不创建运行时目录。首次开始工作流时才创建 `~/.grill-harness/`。卸载 Skill 不删除用户工作流数据：

```bash
npx skills remove grill-harness -g -a codex claude-code -y
```

## 三种使用深度

- **轻量模式**：低风险局部修改。合并三个门禁为一次明确授权，仍保留只读侦察、最小规格、真实测试/diff 和独立验收。
- **标准模式**：默认。经过需求基线、路线选择、仓库挑战、最终规格、垂直切片、独立审查和验收。
- **Wayfinding 模式**：巨大或方向模糊、单会话无法建立可信地图。先把调查与决策拆成独立新会话任务包，路线清楚后回到标准模式。

直接对 Agent 说“用 Grill Harness 规划这个功能”“继续上次工作流”“把最终规格拆成可并行任务”“独立审查并验收”即可，不需要记阶段命令。

## 三个用户门禁

标准模式中，Agent 必须停下来等待用户：

1. 确认具体版本的需求基线；
2. 从一至三张简洁路线卡中选择路线；
3. 批准只深化选中路线后形成的最终规格。

最终规格批准前，产品仓库只读：不修改产品代码，不派发实施，不创建实施分支或 worktree。轻量模式可以合并门禁，但不能零确认编码。

## 多模型与新会话协作

Grill Harness 为实施、审查、修复、集成和验收生成：

- `~/.grill-harness/` 内的自包含任务包；
- 一条简短的本地启动提示词；
- 约定的本地报告路径和证据格式。

用户决定把启动提示词交给哪个本地模型或 Agent。新会话读取任务包和真实仓库，不需要原聊天历史，也不提供 Web 便携提示词。实施者不能最终批准自己；并行结果必须集成检查；最终验收必须由新的独立会话执行。

## 文件与安全边界

所有 Harness 状态、文档、提示词和报告只写入：

```text
~/.grill-harness/
```

当前工作流按以下用途区分：

- `核心文档/`：需求基线、决策账本、领域词汇、当前规格、任务图；
- `过程产物/`：需求审问、路线评估、研究与原型、仓库挑战、任务交接、实施报告、审查修复；
- `最终产物/`：最终规格、集成报告、验收报告、项目经验；
- `系统/`：状态、产物、任务和证据索引。

目标产品仓库不保存 Harness 状态或文档。预检和上游检查不会自动安装、更新或覆盖第三方 Skill；缺少必需能力时失败关闭。并行安全不明确时按不安全处理。

## 状态与恢复

```bash
GRH="$HOME/.agents/skills/grill-harness/scripts/grh.py"
python3 "$GRH" preflight --skill-root "$HOME/.agents/skills"
python3 "$GRH" init --project "$PWD" --workflow-name 发布检查 --created-date 2026-07-12
python3 "$GRH" status --project "$PWD"
python3 "$GRH" reconcile --workflow /绝对路径/工作流目录 --project "$PWD"
```

`preflight` 只检查能力并给出建议。`init` 原子、幂等地创建工作流，不覆盖已有用户数据。`status` 只读。`reconcile` 在文件冲突、手工编辑或中断恢复时列出矛盾，不替用户选择“最完整”的版本。

受保护的状态更新入口：

```bash
python3 "$GRH" record --workflow /绝对路径/工作流目录 --kind artifact --record /绝对路径/产物记录.yaml
python3 "$GRH" record --workflow /绝对路径/工作流目录 --kind evidence --record /绝对路径/证据记录.yaml --project "$PWD"
python3 "$GRH" approve --workflow /绝对路径/工作流目录 --gate final_spec_approval --approval-id DEC-003 --artifact-version ART-003=1
python3 "$GRH" transition --workflow /绝对路径/工作流目录 --phase tasking --to in_progress
python3 "$GRH" task-transition --workflow /绝对路径/工作流目录 --task TASK-001 --to in_progress --project "$PWD"
python3 "$GRH" migrate --workflow /绝对路径/工作流目录
python3 "$GRH" rollback --report /绝对路径/迁移报告.yaml
```

这些写命令只接受 `~/.grill-harness/` 内的工作流和输出路径，并同步机器清单；不要手工编辑系统文件后绕过 `reconcile`。

测试可通过 `GRILL_HARNESS_TEST_ROOT` 把运行时根目录重定向到临时目录。

## 上游适配与更新

Grill Harness 实际组合 `grilling`、`domain-modeling`、`codebase-design`；`grill-with-docs` 仅作为兼容参考。上游检查会比较固定清单、路径、内容、行为契约、本地差异和兼容风险，但不自动接受变化。

```bash
python3 "$GRH" upstream-check \
  --checked-at 2026-07-11T00:00:00Z
```

在线模式默认读取 Skill 自带的 `references/上游清单.yaml`，在临时目录只读 clone 上游并删除临时副本。离线比较已采集事实时增加 `--offline --facts /绝对路径/current-facts.json`；迁移旧清单时可显式传 `--previous`。网络失败只报告 unavailable，不安装、更新或接受任何变化。

当前 CLI 顶层帮助列出 `npx skills update grill-harness -g`，但真实更新行为及本地目录安装的更新追踪尚未验证。不要把帮助检查当作更新验证；执行任何真实更新前先备份 `~/.grill-harness/`，运行兼容检查，并人工评估报告。

## 验证状态

已验证：仓库发现、隔离 Codex/Claude Code 安装、运行时目录隔离、只读 CLI、初始化幂等/冲突保护、卸载保留数据，以及 Python 单元与集成测试。

运行时行为未验证：真实 update 行为和已登录模型的端到端角色执行仍缺证据。隔离 Codex 返回 `401 Unauthorized`，隔离 Claude Code 返回 `Not logged in`，因此不声称模型行为或启动提示词已通过线上验证。

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
tests/integration/test_skills_install.sh
tests/integration/test_runtime_data.sh
```

许可证：MIT，见 [LICENSE](LICENSE)。
