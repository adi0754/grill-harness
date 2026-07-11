# Grill Harness

面向 Codex 与 Claude Code 的单入口、持久化软件工程工作流 Skill。工作流事实来自磁盘状态，不依赖对话记忆。

## 依赖

- Node.js 与 `npx`
- Python 3（只使用标准库）
- 必需 Skills：`grilling`、`domain-modeling`、`codebase-design`

在隔离 HOME 中实际验证过以下依赖安装命令：

```bash
npx skills add mattpocock/skills -g -a codex claude-code -s grilling domain-modeling codebase-design -y --copy
```

## 安装

进入本仓库根目录后执行：

```bash
npx skills add "$PWD" -g -a codex claude-code -s grill-harness -y --copy
```

当前 `skills` CLI 会把 canonical 副本安装到 `~/.agents/skills/grill-harness`，并为 Claude Code 建立 `~/.claude/skills/grill-harness` 入口。仓库发现、Codex/Claude Code 安装和卸载均已在临时 HOME 中验证。

安装只复制 Skill，不创建 `~/.grill-harness/`。首次需要写入持久状态时才会创建该目录；测试使用 `GRILL_HARNESS_TEST_ROOT` 将它重定向到临时目录。

卸载命令也已在隔离环境执行验证，且不会删除工作流数据：

```bash
npx skills remove grill-harness -g -a codex claude-code -y
```

## 更新

当前 CLI 顶层帮助已验证以下语法，但为保护现有安装与用户数据，测试未实际执行 `update`：

```bash
npx skills update grill-harness -g
```

更新前先备份 `~/.grill-harness/`。安装包与运行时数据分离；隔离更新 fixture 已验证不会覆盖工作流数据。

## 状态与恢复

```bash
GRH="$HOME/.agents/skills/grill-harness/scripts/grh.py"
python3 "$GRH" preflight --skill-root "$HOME/.agents/skills"
python3 "$GRH" status --project "$PWD"
python3 "$GRH" reconcile --workflow /绝对路径/state.yaml
```

`preflight` 只检查能力并给出建议，不自动安装或更新。`status` 是只读命令；恢复检查使用 `reconcile`，发生冲突时不会替用户选择版本。

## 上游检查

```bash
python3 "$GRH" upstream-check \
  --previous /绝对路径/previous-manifest.json \
  --facts /绝对路径/current-facts.json \
  --checked-at 2026-07-12T00:00:00Z \
  --offline
```

此命令只生成兼容性报告，不安装、更新或接受上游变化。

## 验证状态

安装、目录隔离、只读 CLI、卸载数据保留和本地 update fixture 已验证。运行时行为未验证：隔离 Codex 返回 `401 Unauthorized`，隔离 Claude Code 返回 `Not logged in`，因此未声称模型路由、场景执行或启动提示词通过。其他 Agent 也未做同等级验证。

```bash
tests/integration/test_skills_install.sh
tests/integration/test_runtime_data.sh
python3 -m unittest discover -s tests -p 'test_*.py'
```

许可证：MIT，见 [LICENSE](LICENSE)。
