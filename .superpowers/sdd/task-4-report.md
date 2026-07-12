# Task 4 实施报告：证据驱动知识生命周期

## 完成范围

- 新增 `knowledge.py` 六个接口：记录验证、只读查询、学习草稿、变更预览、项目归档、通用晋升。
- 新增长期目录：`知识库/项目知识/<project-id>/knowledge.yaml` 与 `知识库/通用知识/knowledge.yaml`。
- 新增受保护 CLI：`knowledge-query`、`knowledge-draft`、`knowledge-promote`。
- 新增 `知识条目.yaml`、`学习草稿.md`、`知识变更预览.md`，并更新 `项目经验.md`。
- 未实现或修改 Task 5 的 `failure_control`。

## 关键安全语义

- 查询不调用任何布局初始化函数；空存储、未启动工作流和任意阶段均只读，不创建目录、不改 hash、不推进 phase。
- 学习草稿只能写当前工作流的 `过程产物/学习草稿/`，写入时强制 `trust_status=tentative`。
- 正式归档采用两步协议：
  1. 生成工作流内 `KPV-*` 内容哈希预览，长期知识库不写入；
  2. apply 必须引用绑定该 `preview_id` 的持久化用户 `DEC-*` / `CHG-*`。
- preview 的 records 与 store hash 来自同一锁内原始 bytes 快照；apply 按固定锁序重新校验目标库 hash、当前 workflow、批准和证据。
- knowledge、state、artifacts/tasks/evidence manifests 和 ledger 使用同一 workflow journal 事务；目标替换后的失败会恢复全部原始 bytes。
- 项目正式归档在锁内重新检查独立保障完成、当前最终验收证据、Git baseline 和批准，并通过 `state.transition_state()` 合法完成 `knowledge_archive`。
- 通用晋升只接受项目库中仍为 verified 的同一 `KNW-*`，并要求与项目归档批准不同、绑定通用预览的第二个用户批准；apply 再检查项目源库 hash。
- 冲突知识不能覆盖历史；旧记录改为 `trust_status=replaced` 并用 `replaced_by` 指向新记录。invalidated/replaced 记录只进入历史结果，不指导规划。
- 路线失败例外仅允许项目级 `route_failure` 事实；要求当前工作流内存在、当前有效、归属一致且分类为 route failure 的真实 evidence，以及绑定预览的用户分类批准。该路径不完成 archive phase，也不能进入通用知识。

## TDD 与审查

- 初始 RED：`knowledge.py`、知识目录 API 和模板缺失；随后按 storage → state prerequisite → knowledge core → templates → CLI 的顺序逐项 GREEN。
- 第一轮审查发现 preview/apply 顺序、第二批准、跨文件事务、phase 绕过和路线失败证据五项 Important，均先补回归测试再修复。
- 第二轮审查发现 preview 快照竞态、通用源知识 TOCTOU、knowledge target 未被回滚测试覆盖三项 Important，均以稳定 RED 复现后修复。
- 最终实现不再从 `knowledge.py` 调用 `workflow_ops` 私有 API；使用公开 `commit_knowledge_update()`。

## 验证

- 定向：`python3 -m unittest tests.unit.test_knowledge tests.unit.test_storage tests.unit.test_grh_cli tests.unit.test_templates tests.unit.test_workflow_ops tests.unit.test_state_machine tests.unit.test_entry_contract -v`
- 全量：`python3 -m unittest discover -s tests/unit -v`
- 编译：`python3 -m compileall -q skills/grill-harness/scripts tests/unit`
- 差异检查：`git diff --check`

最终一次验证结果见提交前终端证据；所有命令均要求零失败后才提交。

## 独立审查追加修复

主会话在首个 Task 4 提交后又确认三项边界问题，本次追加修复：

- apply 不再信任 preview 内的路径。`knowledge.py` 按 `scope + project_id` 重新推导并比对规范目标与通用知识项目源；`workflow_ops.commit_knowledge_update()` 也只接收 scope/project ID，自行推导存储路径。
- preview 持久化本轮 `candidate_ids`。路线失败 apply 只解析这些候选对应的 evidence，不再把长期库中的历史路线失败证据带入本轮门禁。
- `state.current_project_baseline()` 成为 CLI 与事务共享的唯一 baseline provider。正式 apply 必须传入项目路径，并在原子锁区内重新计算 current baseline；workflow baseline 与最终验收 evidence baseline 缺失、布尔或不匹配时一律失败关闭。

以上三项均先以独立回归测试观察 RED，再实现最小修复并观察 GREEN。
