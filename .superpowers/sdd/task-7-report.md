# Task 7 实施报告：V2 完整验证与独立验收包

日期：2026-07-12

## 交付范围

- 新增中文自包含验收提示词：`docs/acceptance-prompt-v2.md`。
- 执行 V2 全量单元、编译、Shell 语法、skills.sh 安装、运行时数据、diff、凭据、个人路径和运行时边界验证。
- 完成一次独立代码/规格审查和一次独立 Skill 行为审查，对有证据的 Important 使用 RED→GREEN 修复并复审。
- 未合并、推送、发布、删除分支/worktree 或更改仓库可见性。

## Git 基线

- 分支：`feat/initial-implementation`
- Task 7 提交前本地 HEAD：`cbe0cd2ce64049c22aa2b277201bd96a368f2ccd`
- 当时跟踪的 `origin/feat/initial-implementation`：`de3ce5d492f00b5e692474219da5409d5ff0db95`
- `origin/main`：`f2282fdecf547e9bfdb0a43929338043db0324e8`
- Task 7 最终提交 SHA 由交付回复报告；同一提交无法在自身内容中稳定引用自身 SHA。

报告写入时的未提交范围是 Task 7 预期文档、测试和经证实修复；提交后工作树状态由交付回复中的 fresh `git status --short` 证据确认。

## Fresh 验证证据

### 全量单元测试

```text
python3 -m unittest discover -s tests -p 'test_*.py'
Ran 300 tests in 12.302s
OK
```

结果：300/300 PASS。

### Python 编译

```text
python3 -m py_compile skills/grill-harness/scripts/*.py
exit 0
```

### Shell 语法

```text
rg --files -g '*.sh' -0 | xargs -0 -n1 bash -n
exit 0
```

### skills.sh 隔离安装

```text
tests/integration/test_skills_install.sh
PASS: eight-entry wildcard discovery, complete/incomplete install, and uninstall
exit 0
```

证实：

- 当前 skills CLI 发现并用 `-s '*'` 安装 8 个公开 Skill；
- Codex canonical 副本和 Claude Code 入口均在隔离 HOME 中创建；
- 必需能力 `grilling`、`domain-modeling`、`codebase-design` 在隔离 HOME 中安装并通过 preflight；
- 只安装 `grh-learn` 时缺少主内核失败关闭，不创建运行时数据；
- 卸载 8 个 Skill 不删除隔离用户 workflow 数据。

### 运行时数据隔离

```text
tests/integration/test_runtime_data.sh
PASS: runtime creation isolation
SKIP: real update behavior unverified; current CLI does not track local installs
exit 0
```

证实：安装和只读 status 不创建运行时根；首次 mutating 使用只写隔离 `GRILL_HARNESS_TEST_ROOT`；产品 fixture 不变且 Git 干净；卸载不改用户 workflow 文件。

限制：脚本中的 update 是隔离 HOME 下“未发现可跟踪本地安装”的 no-match 探针，不是真实 update 验证。本报告不宣称更新行为通过。

### 边界扫描

- `git diff --check`：PASS。
- `git diff --check origin/main...HEAD`：PASS。
- 高可信 secret scan：无匹配；`rg` 按无匹配语义退出 1。
- 已跟踪文本 personal-path scan：PASS；白名单只包含显式测试假路径、场景临时占位和任务图模板占位。
- 已提交运行时证据的凭据/关联 ID/个人路径脱敏测试：包含在 300 项全量测试中并通过。
- 运行时边界：存储、入口、知识、运行时安全单测与两项 integration 均通过；产品项目不保存 Harness 状态。

## 独立审查与修复

独立代码/规格审查报告：`.superpowers/sdd/task-7-code-review.md`。

独立 Skill 行为审查报告：`.superpowers/sdd/task-7-skill-review.md`。

最终复审结论：Critical 0，Important 0。

已关闭的有证据 finding：

1. 主 `SKILL.md` 曾错误允许轻量模式合并三门禁。新测试先 RED，修复后要求三门禁分别批准、绑定形成后的真实产物版本，禁止合并/预批/零确认。
2. 普通知识 promotion preview 曾可在未验收时写出。新 unit/CLI 测试先 RED，现要求 independent assurance 完成、accepted evidence 当前有效，且在写 preview 前使用真实 `project_path` 重算 Git baseline。
3. project/general preview 现对验收后新 commit、dirty 工作树、`git status`、`git diff`、`git ls-files` 失败全部失败关闭，并有零 preview 文件回归测试。`route_failure` 仍是只限项目失败事实的独立例外，不完成归档且不能提升为通用知识。
4. 已跟踪历史实施文档中的个人绝对路径改为 `<REPO_ROOT>`、`<REPO_PARENT>`、`<SOURCE_DESIGN>` 和 `<SOURCE_PLAN>`，并新增全 tracked text 扫描。
5. 验收提示词曾声明隔离但未隔离 Python bytecode cache。新测试先 RED，现在运行任何 Python/npm/场景命令前必须创建 `ACCEPT_TMP`，导出隔离 HOME/CODEX_HOME/XDG/运行时/npm cache/输出及 `PYTHONPYCACHEPREFIX`。

## 验收提示词

`docs/acceptance-prompt-v2.md` 可在新会话中独立使用，覆盖：

- 八公开入口、显式入口优先、资格阻断和 no auto-chain；
- 五维需求雷达、低/中/高升级、用户选择调查 Agent 和相似实现逐项对照；
- 三个分别绑定真实产物版本的人类硬门禁；
- 查询/草稿/project/general 知识边界和 route-failure 例外；
- 四失败类、第三次进入 recover、Review 可选意见收敛和人类换路权；
- skills.sh 安装、缺内核失败关闭、上游只读和禁止有副作用 update；
- 证据、独立会话、并发 worktree/共享契约边界、reconcile/recover 和迁移回滚；
- 静态、确定性、真实模型三层证据和明确 PASS 阈值。

## 真实模型与 update 限制

- 本 Task 7 未在已登录的隔离 Codex 或 Claude Code 环境重跑端到端角色场景。
- 已提交的隔离结果记录 Codex `401 Unauthorized` / `UNVERIFIED` 和 Claude Code `Not logged in`。这些结果只证明凭据隔离和失败记录，不证明真实模型行为通过。
- 因此本报告只宣称静态与确定性层通过；不宣称真实模型入口、启动提示词或角色执行已通过端到端验证。
- 真实 skills update 行为和本地目录安装的更新跟踪仍未验证。

## 结论

静态与确定性层达到 V2 Task 7 阈值：300/300 单元测试、编译、Shell 语法、两项 integration、diff/凭据/个人路径/运行时边界和两项独立复审均通过，最终 Critical 0 / Important 0。

真实模型端到端和真实 update 仍为未验证限制，未被表述为通过。
