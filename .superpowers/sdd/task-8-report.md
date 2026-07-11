# Task 8 实施报告：精简主路由与只读 CLI

## 范围

将占位 `SKILL.md` 收敛为单入口 Router，覆盖 start、continue、status、recovery、upstream check；阶段细节继续由 references 承担。新增统一只读 `scripts/grh.py`，提供 `identify`、`preflight`、`status`、`reconcile`、`upstream-check` 的机器 JSON 输出，不提供 mutation 命令。

## Skill RED / GREEN

先在未加载新 Skill 的新上下文运行五个压力场景并保存 `tests/scenarios/router/RED.md`。观察到的缺口包括：信任前序摘要直接实施、无法从持久状态报告 status、自动安装上游更新，以及缺少 Harness 预检/对账/门禁协议。

写入最小 Router 后，以新上下文重跑并保存 `GREEN.md`。首轮 start 把“无 workflow”误判为 recovery，补充 `status: not_started` 的可观察条件后关闭该漏洞。continue、status、recovery、upstream check 均按持久状态和只读边界路由。

## CLI TDD

先新增 `tests/unit/test_grh_cli.py`。首次运行 5/5 失败，原因均为 `scripts/grh.py` 不存在；upstream-check 独立场景也先以 argparse unknown command 失败。最小实现后专项测试 6/6 通过。CLI 内部复用 `state`、`preflight`、`validate`、`upstream_check`，stdout 为稳定 JSON；退出码 `1` 表示策略/对账阻塞，`2` 表示输入或 I/O 错误。

## 隔离 start 前向验证

在 `/tmp/grh-router-green.HtkpgK/project` 与隔离 `GRILL_HARNESS_TEST_ROOT` 中实际运行只读 CLI：

- `identify`：exit 0，project ID `7cd4d4d303e2`；
- `preflight`：exit 0，`ready: true`，`actions_performed: false`；
- `status`：exit 0，`status: not_started`，对账有效且无冲突，`next_eligible_phase: preflight`；
- 检查后隔离 storage root 仍不存在。

第一次名为 `router_green_start_verified` 的前向子会话在 CLI 修订期间被中断，未作为证据。替代的新上下文 `router_green_start_cli` 实际执行上述命令，只依据 JSON 返回 `start → preflight`；其结果已记录在 `GREEN.md`。

## 验证

```text
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 122 tests in 0.748s
OK

git diff --check
通过
```

Bundled `quick_validate.py` 使用当前 `/usr/bin/python3` 运行时因缺少既有 `yaml` 模块而无法执行：`ModuleNotFoundError: No module named 'yaml'`。按要求未安装依赖，因此本轮 quick_validate 标记为未验证，不宣称通过。
