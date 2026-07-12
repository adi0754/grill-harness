---
name: grill-harness
entry_core_contract_version: 1
description: Use as the Grill Harness router when the user asks for workflow status, the next safe step, or does not name one of the seven human-intent entries explicitly.
---

# Grill Harness

以磁盘事实而非聊天记忆驱动软件工程工作流。本 Skill 是兜底 Router；七个薄入口负责执行各自的人类意图范围，共享此处的单一内核、状态机、脚本和产物契约。

## Router 每次进入都先核验

将 `<grh>` 解析为本 Skill 内 `scripts/grh.py` 的绝对路径，并按顺序使用 JSON CLI：

1. `python3 <grh> identify --project <项目绝对路径>`
2. `python3 <grh> preflight [--skill-root <已安装Skills根目录>]`
3. `python3 <grh> status --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`
4. 产物有冲突、被手工编辑或需要恢复时：`python3 <grh> reconcile --workflow <工作流或state.yaml绝对路径>`
5. 根据意图选出候选入口后：`python3 <grh> entry-check --entry <公开入口> --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>] [--requested-scope <更窄范围>]`

`status` 返回的状态、门禁和 `next_eligible_phase` 是路由依据。退出码 `1` 表示策略阻塞，`2` 表示输入或 I/O 失败；停止并原样报告 JSON，不推测成功。前一位 Agent 的总结不是事实或门禁证据。Router 本身不初始化、不迁移状态，也不执行完整阶段。

执行入口后若需变更机器状态，只能按主内核使用 `record`、`approve`、`transition`、`migrate`、`rollback` 等受保护命令。不要手工改写系统清单后继续执行。

## 意图路由

| 用户意图 | 推荐公开入口 | Router 动作 |
|---|---|---|
| 开始、澄清需求、需求基线、选择路线 | `grh-start` | 报告资格与缺失门禁后停止 |
| 调研、原型、仓库挑战、最终规格、拆分 | `grh-plan` | 报告资格与缺失门禁后停止 |
| 任务包、实施、修复 | `grh-run` | 报告资格与缺失门禁后停止 |
| 独立审查、集成检查、最终验收 | `grh-check` | 报告资格与缺失门禁后停止 |
| 中断、漂移、冲突、重复失败、路线失效 | `grh-recover` | 报告资格与需确认事项后停止 |
| 查经验、复盘、归档知识 | `grh-learn` | 报告可用的只读/写入范围后停止 |
| 依赖或上游兼容性检查 | `grh-upstream-check` | 给出只读入口建议后停止 |
| 状态、下一步、不确定该用哪个入口 | `grill-harness` | 只读报告并推荐一个入口 |

用户明确指定公开入口时尊重该意图，不用自然语言重新改道；仍须调用 `entry-check`，状态资格和硬门禁可以阻止该入口。自然语言未指定入口时，Router 根据真实 `status` / `reconcile` 结果推荐入口，但不执行完整阶段、不自动调用下一入口。用户指定比入口更窄的范围时，作为 `--requested-scope` 传入，只能缩小权限。

所有 references 都位于 `references/`，直接从本文件加载，不依赖嵌套查找。

## 不可突破的规则

- 所有 Harness 状态、文档、报告、任务包和启动提示词只能写入当前工作流的 `~/.grill-harness/` 目录。目标产品仓库不保存 Harness 文件。
- 在与当前阶段匹配的产品代码门禁通过前，目标仓库只读。最终规格未批准前，不修改产品代码，不派发实施，不创建实施分支或 worktree。
- 必需能力 `grilling`、`domain-modeling`、`codebase-design` 缺失时失败关闭；不假装调用，不静默替代，不自动安装。
- 需求基线、路线选择、最终规格是三个用户硬门禁。轻量模式可合并为一次明确授权，但不能零确认编码。
- 路线阶段只生成一至三张简洁路线卡；用户选择前不深化多份完整规格。
- 正式实施、审查、修复、集成和验收各自使用本地自包含任务包。由用户决定模型和 Agent，并在新本地会话发送短启动提示词。
- 不依据摘要宣称完成。必须读取真实文件、完整 diff、未提交状态和可复现测试证据。
- 并行安全不明确时按不安全处理；共享写路径、共享契约、迁移、生成物或同一 worktree 均禁止并行。

## 完成标准

只有独立最终验收对当前 Git 基线给出“验收通过”，且证据有效、需求与决策覆盖完整、没有阻塞问题时，才能声称工作流完成。之后写入项目经验并归档；长期知识只保留稳定决策、领域语言、仓库事实、踩坑和证据链接。
