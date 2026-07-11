# Task 7 实施报告：模板与聚焦工作流参考

## 范围

新增六份中文工作流/运行时参考和十二份产物模板，覆盖需求基线、账本、路线、仓库挑战、规格、任务图、实施、双轴审查、修复、集成、验收与经验沉淀。未修改 `SKILL.md`，未创建网页/便携提示词模板。

## TDD 证据

先创建 `tests/unit/test_templates.py`，首次运行得到 1 个 failure 和 6 个 error，均由目标 references/templates 缺失导致。实现后专项测试 7/7 通过。

## 契约结果

- 稳定 ASCII ID 与现有 `state.py` 类型一致。
- 本地角色任务明确绝对项目路径、输入、输出、停止条件和禁止读取完整聊天历史。
- 轻量、标准、Wayfinding 模式以及三个用户门禁均显式记录。
- 路线卡在用户选择前停止，不提前生成多份完整规格。
- 仓库挑战提供六类结论并要求真实路径与符号。
- 审查使用独立 Standards / Spec 两轴。
- 本地启动提示词保持简短，仅引用任务包；模板目录不包含 web/portable prompt。

## 验证

```text
python -m unittest discover -s tests -p 'test_*.py'
...................................................................................................................
Ran 115 tests in 0.672s
OK

git diff --check
通过
```

## 审查修复

审查后先把模板测试升级为真实协议测试。RED 显示账本和任务图都不是 JSON-compatible YAML，且五类角色任务缺少统一的逐项输入定位字段。修复后：

- `决策账本.yaml` 可由 `json.loads` 解析，每条记录包含合法 `type`，并通过 `state.validate_ledger`；内容与 `state.create_ledger_record` 生成协议一致。
- `任务图.yaml` 显式提供 `depends_on`/`blockers`、`currentness`、冲突分析字段、隔离字段、追踪/验收 ID 和绝对任务/输出路径；通过 `validate_dag`、`calculate_frontier` 与 `analyze_task_conflict`。
- 实施、审查、修复、集成、验收模板均要求逐项填写输入产物绝对路径及版本或基线。
- 更新后专项测试 8/8、全量测试 116/116 通过。
