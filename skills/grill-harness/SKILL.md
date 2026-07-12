---
name: grill-harness
description: Use when planning, splitting, implementing, reviewing, verifying, continuing, recovering, or checking the status of substantial software-engineering work, especially when requirements are unclear, multiple approaches exist, work spans agents or sessions, parallel execution may conflict, or completion needs independent evidence.
---

# Grill Harness

以磁盘事实而非聊天记忆驱动软件工程工作流。只公开这一个 Skill；阶段名称是内部路由，不要求用户记忆。

## 每次进入都先核验

将 `<grh>` 解析为本 Skill 内 `scripts/grh.py` 的绝对路径，并按顺序使用 JSON CLI：

1. `python3 <grh> identify --project <项目绝对路径>`
2. `python3 <grh> preflight [--skill-root <已安装Skills根目录>]`
3. `python3 <grh> status --project <项目绝对路径> [--workflow <工作流或state.yaml绝对路径>]`
4. 产物有冲突、被手工编辑或需要恢复时：`python3 <grh> reconcile --workflow <工作流或state.yaml绝对路径>`
5. 仅当状态为 `not_started` 且用户明确要开始时：`python3 <grh> init --project <项目绝对路径> --workflow-name <中文简称> --created-date <YYYY-MM-DD> [--workflow-key <稳定键>]`

`status` 返回的状态、门禁和 `next_eligible_phase` 是路由依据。退出码 `1` 表示策略阻塞，`2` 表示输入或 I/O 失败；停止并原样报告 JSON，不推测成功。前一位 Agent 的总结不是事实或门禁证据。

机器状态只能通过 `record`、`approve`、`transition`、`migrate`、`rollback` 这些受保护命令变更；具体参数读取 `python3 <grh> <command> --help` 和 `阶段执行协议.md`。不要手工改写系统清单后继续执行。

## 意图路由

| 用户意图 | 动作 | 按需读取 |
|---|---|---|
| 开始、规划、设计功能 | 初始化后进入最早未完成阶段 | `工作流状态机.md`、`阶段执行协议.md`、`文档与产物契约.md` |
| 继续、恢复、中断后接手 | 从 reconcile 后的下一合法阶段继续 | `工作流状态机.md`、当前阶段 reference |
| 拆任务、并行、生成执行包 | 只在最终规格门禁通过后进行 | `阶段执行协议.md`、`角色任务协议.md` |
| 实施、修复、集成 | 核对任务包、基线和授权范围 | `角色任务协议.md`、对应运行时 reference |
| 审查、验收、发布判断 | 使用独立新会话和真实证据 | `测试与验收.md`、`角色任务协议.md` |
| 状态、下一步、冲突 | 只读报告身份、阶段、门禁、冲突和下一动作 | `工作流状态机.md` |
| 上游或依赖检查 | 只读比较，不安装、不更新 | `上游适配契约.md` |

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
