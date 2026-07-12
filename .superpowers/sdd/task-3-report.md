# Task 3 实施报告：自适应需求雷达与相似实现对照

## 状态

完成。实现范围仅限 Task 3；未修改知识或失败归档模块。

## 实现

- 新增 `requirements_radar.py`，提供：
  - `validate_radar_record()`：验证五类 `RAD-*` 记录、公共字段、追踪与高风险调查的用户控制契约。
  - `classify_escalation()`：低/中/高风险升级；公共契约、Schema、约束冲突、影响未知或高返工成本进入高风险独立调查候选。
  - `unresolved_baseline_blockers()`：按稳定 ID 的最新版本筛选当前开放的需求基线阻塞项。
  - `validate_analogue_comparison()`：验证 found 候选的逐项对照，或 not_found 的搜索范围与证据。
  - `traceability_report()`：检查路线卡、仓库挑战、最终规格、任务、验收与知识沉淀的 `RAD-*` 引用。
- `state.LEDGER_RECORD_TYPES` 新增 `RAD`，决策账本模板同步稳定记录。
- `state.validate_ledger()` 通过集中 subtype registry 验证 RAD payload，使所有 Ledger 调用方共享同一契约。
- `workflow_ops.approve_gate()` 仅在 `requirements_baseline` 门禁写入前检查开放 baseline blocker，并在错误中返回稳定 ID；原有三门禁不变，检查发生在事务写入前。
- 新增 `需求雷达.md`、`问题与发现.yaml`、`相似实现对照.md`、`需求调查任务.md`，并更新 `需求基线.md` 的 RAD 关联、阻塞清零声明和规格前验证项。

## TDD 证据

1. RED：`python3 -m unittest tests.unit.test_requirements_radar -v`
   - 预期失败：`ModuleNotFoundError: No module named 'requirements_radar'`。
2. GREEN：同一命令通过 9 项纯函数测试。
3. RED：需求基线门禁测试在开放 `RAD-001` 时错误地批准成功。
4. GREEN：门禁拒绝批准、返回 `RAD-001`，并证明 state 在拒绝前后字节不变。
5. RED：模板组合测试因四个模板缺失、账本缺少 RAD fixture 失败。
6. GREEN：目标组合 34 项测试通过。
7. RED→GREEN：公共契约变化单项从 medium 修正为 high，锁定高风险升级语义。

## 自审

- 独立 Standards 审查：无硬性规范违规。
- 接受建议：统一严格 `RAD-[0-9]{3,}` ID 判定，避免阻塞与追踪逻辑接受 validator 会拒绝的宽松前缀。
- 接受建议：将 RAD subtype validator 集中到 `state` Ledger registry，移除 mutation 层的 subtype 特判。
- `git diff --check` 与 Python 编译通过。

## 最终验证

- `python3 -m unittest tests.unit.test_requirements_radar tests.unit.test_ledger tests.unit.test_workflow_ops tests.unit.test_templates -v`：34 项通过。
- `python3 -m unittest discover -s tests -p 'test_*.py'`：222 项通过。
- `python3 -m py_compile skills/grill-harness/scripts/*.py`：通过。
- `git diff --check`：通过。

## 审查修复追加

- 强制每个 RAD record 提供 `risk_signals` 布尔映射与合法 `escalation`（low / medium / high），且 escalation 必须与 `classify_escalation(risk_signals)` 推导结果完全一致，禁止缺失或降级绕过。
- 推导结果为 high 时，强制完整 `investigation_plan`，并要求 `agent_selection=needs_user`；缺失计划或自动派发均拒绝。
- `traceability_report()` 现在严格要求每个下游产物的 `radar_ids` 为非字符串序列，且每项均满足严格 `RAD-[0-9]{3,}`；容器或 ID 非法时返回 contract conflict。
- 新增 3 个绕过回归测试；目标组合 37 项通过，全量 225 项通过。
