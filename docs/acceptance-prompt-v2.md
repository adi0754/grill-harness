# Grill Harness V2 独立验收提示词

你是 Grill Harness V2 的新会话独立验收者。不要依赖原聊天、实施者总结、旧报告的通过结论或其他 Agent 的口头承诺。从当前仓库、设计、V2 计划、实际文件、Git 基线和可重现命令重建事实。

本次只做验收，不实施修复。最终输出一份中文验收报告，结论只能是“验收通过”、“有条件通过”、“验收不通过”或“无法验证”。

## 1. 输入与报告位置

1. 进入待验收的 Grill Harness 仓库根目录，设为 `<REPO_ROOT>`。
2. 完整读取：
   - `.superpowers/sdd/task-7-brief.md`；
   - `docs/design.md`；
   - `docs/implementation-plan-v2.md`；
   - `README.md`；
   - 八个公开 `SKILL.md`；
   - `skills/grill-harness/references/`、`scripts/`、`assets/templates/`；
   - `tests/unit/`、`tests/integration/`、`tests/scenarios/` 及已提交场景证据。
3. 验收报告只写到仓库外的 `<ACCEPTANCE_REPORT>`，默认可用 `/tmp/grill-harness-acceptance-v2.md`。不要修改、格式化或提交仓库文件。

在运行任何 Python、npm/skills.sh 或场景命令前，先创建本次验收专用的临时环境：

```bash
ACCEPT_TMP=$(mktemp -d "${TMPDIR:-/tmp}/grh-acceptance.XXXXXX")
trap 'rm -rf "$ACCEPT_TMP"' EXIT
export HOME="$ACCEPT_TMP/home"
export CODEX_HOME="$ACCEPT_TMP/codex-home"
export XDG_CONFIG_HOME="$ACCEPT_TMP/xdg-config"
export XDG_DATA_HOME="$ACCEPT_TMP/xdg-data"
export XDG_CACHE_HOME="$ACCEPT_TMP/xdg-cache"
export GRILL_HARNESS_TEST_ROOT="$ACCEPT_TMP/runtime"
export PYTHONPYCACHEPREFIX="$ACCEPT_TMP/pycache"
export npm_config_cache="$ACCEPT_TMP/npm-cache"
mkdir -p "$HOME" "$CODEX_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" \
  "$XDG_CACHE_HOME" "$PYTHONPYCACHEPREFIX" "$npm_config_cache"
```

验收命令必须在这些导出仍有效的同一 shell 会话中执行。`PYTHONPYCACHEPREFIX` 确保 `py_compile` 和 `unittest` 的 bytecode cache 不落入待验收仓库或用户真实缓存目录。

## 2. 强制安全边界

- 先只读、后隔离验证。所有会创建文件、安装 Skill 或调用模型的测试必须使用 `mktemp` 下的独立 `HOME`、`CODEX_HOME`、配置目录、运行时根目录和输出目录。
- 不得读取、复制或继承用户真实 Codex / Claude / 云凭据、OAuth 会话、API key 或私人配置。
- 不得在真实 HOME 中执行 `skills add/remove/update`、包管理器安装、全局配置修改或第三方 Skill 更新。
- 禁止任何可以更新已安装 Skill 的有副作用 update。不得运行真实 `npx skills update ...`，不得接受上游变更。
- `tests/integration/test_runtime_data.sh` 包含一个隔离 HOME 中的“本地安装不可跟踪” no-match 探针。只有在你已亲自确认脚本仍将 HOME/配置/运行时全部指向 `mktemp`，且探针预期为 `No installed skills found matching` 时，才可将整个脚本作为隔离测试运行。该探针不是真实 update 验证；若无法证明它仍为无副作用，跳过并报告“无法验证”。
- 不得执行 `git reset --hard`、`git clean`、强制推送、删除分支/worktree、合并、发布、部署或将仓库改为公开。
- 不得调用任何会修改 workflow 的 `record`、`approve`、`transition`、`task-transition`、`task-review`、`failure-record`、`knowledge-draft`、`knowledge-promote`、`migrate` 或 `rollback` 命令来验收真实用户数据。需要这些场景时只能在临时测试根中使用仓库已有 fixture/测试。

## 3. 证据分层

必须分开报告三层证据，不得用低层证据替代高层证据。

### A. 静态证据

检查文件、契约、diff 和静态边界：

```bash
git status --short
git rev-parse HEAD
git remote -v
git merge-base origin/main HEAD
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
python3 -m py_compile skills/grill-harness/scripts/*.py
rg --files -g '*.sh' -0 | xargs -0 -n1 bash -n
```

执行高可信凭据扫描，无匹配时 `rg` 退出码 `1` 为正常“未发现”：

```bash
rg -n --hidden --pcre2 -g '!.git/**' -g '!*.pyc' \
  -e 'AKIA[0-9A-Z]{16}' \
  -e 'sk-(?:proj|svcacct)-[A-Za-z0-9_-]{20,}' \
  -e 'gh[pousr]_[A-Za-z0-9]{36,}' \
  -e '-----BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY-----' .
```

运行已跟踪文本的个人路径扫描测试，它只允许显式的测试假路径、场景临时占位符和模板占位符：

```bash
python3 -m unittest \
  tests.unit.test_runtime_safety.RuntimeEvidenceSanitizationTests.test_tracked_text_has_no_personal_paths_outside_explicit_test_fixtures -v
```

亲自审查 `origin/main...HEAD` 的完整文件列表和重要 diff，至少覆盖八入口、入口契约、状态/门禁、雷达、知识、失败控制、上游检查、安装脚本、场景运行器和测试。

### B. 确定性证据

先运行全量测试：

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

再运行 V2 聚焦契约：

```bash
python3 -m unittest \
  tests.unit.test_entry_contract \
  tests.unit.test_preflight \
  tests.unit.test_requirements_radar \
  tests.unit.test_knowledge \
  tests.unit.test_failure_control \
  tests.unit.test_templates \
  tests.unit.test_router_scenarios \
  tests.unit.test_codex_scenarios \
  tests.unit.test_claude_code_scenarios \
  tests.unit.test_runtime_safety -v
```

检查两个集成脚本的隔离设置后，在不触碰真实 HOME 的前提下运行：

```bash
tests/integration/test_skills_install.sh
tests/integration/test_runtime_data.sh
```

必须分别记录：全量测试数、失败数、编译结果、八入口发现/安装结果、不完整安装失败关闭、卸载保留用户数据、运行时根隔离和 update 限制。

### C. 真实模型证据

该层是独立证据，不是确定性测试的必然延伸。

- 仓库已提交的 Codex / Claude Code 隔离结果若显示 `401 Unauthorized`、`Not logged in` 或 `UNVERIFIED`，只能证明隔离和失败记录，不能证明模型行为通过。
- 不要为了验收复制用户真实登录态。如果没有用户明确授权的已登录隔离环境，将本层标记为“未验证”。
- 如果确有授权的隔离登录环境，在仓库的临时副本中运行真实模型场景，不要让 Claude runner 把输出写回待验收工作树。Codex runner 必须显式传入仓库外的输出目录。
- 按 `tests/scenarios/results/RUBRIC.md` 逐场景打分。每个可适用维度都必须为 `1`，任一维度为 `0` 则该场景失败。

## 4. 八个公开入口验收

静态契约、机器决策和场景证据都必须覆盖下列八个入口：

1. `grill-harness`：只读识别状态、下一步和候选入口；用户未点名入口时才根据真实状态推荐；不初始化、不执行完整阶段。
2. `grh-start`：支持“只梳理需求”等更窄 scope；完成仓库侦察、需求雷达、需求基线和路线选择后停止；不进入详细规格或实施。
3. `grh-plan`：只在路线已选且资格满足时进行调研/原型、仓库挑战、最终规格和垂直切片；最终规格未批准时等待，批准后生成 Frontier 并停止。
4. `grh-run`：必须已有绑定真实规格版本的 `final_spec_approval`；只做任务包、实施和已授权修复；不执行最终验收，不切换路线。
5. `grh-check`：只读执行 Standards / Spec 双轴审查、集成检查和最终验收；`review-only` 窄 scope 必须排除 final acceptance；不修复、不自动调用 `grh-run`。
6. `grh-recover`：处理中断、漂移、证据冲突、完整性错误、重复失败和路线失效；可生成带新事实的路线卡，但切换路线必须等待用户。
7. `grh-learn`：`search_knowledge` 在任何阶段保持只读且不创建存储；复盘只写 tentative 草稿；普通 project/general promotion preview 在创建文件前即要求独立保障完成和当前验收通过，未验收时零 preview 文件；项目提升需用户批准，通用提升再需第二次独立批准。
8. `grh-upstream-check`：只读检查依赖、上游内容和行为契约；报告必须固定 `actions_performed: false` 且 `accepted_upstream_changes: false`；不安装、不更新、不接受变更。

通用入口断言：用户显式点名入口时优先尊重该意图，但仍必须经过 `entry-check`；状态、前置产物和硬门禁可以阻止它。所有决策必须 `will_auto_route: false`；入口结束只能建议下一入口，不能自动串联或自动换路。

## 5. 需求雷达与相似实现

- 需求基线前必须覆盖五类：需求澄清、需求遗漏、需求牵连、需求悖论、相似实现。
- 每个发现使用稳定 `RAD-xxx`，保留类别、证据、可信度、影响、责任、阻塞级别、状态和跨产物追踪。
- 低风险由主会话处理；中风险只深入一至两个维度；高风险才生成独立调查任务包。升级不能被低级字段静默降级。
- 独立调查前必须展示理由、问题、角色、预期产物和是否阻塞基线；用户决定是否启动以及使用哪个模型/Agent。
- 未解决的 baseline blocker 必须阻止需求基线批准并返回稳定 RAD ID。
- 每个相似实现候选必须逐项包含：路径/符号、相同点、差异点、可复用点、不可复用原因、必须一致的公共契约、可复用测试和本需求新增行为。
- “未发现”必须记录搜索范围和查询证据，不得写成“仓库不存在”。

## 6. 三个人类硬门禁

必须分别验证：

1. 用户确认需求基线；
2. 用户选择路线；
3. 用户批准最终规格。

每个门禁都必须在对应产物形成后绑定真实版本。轻量模式只能缩短产物，不得合并、预批、省略门禁或零确认编码。最终规格未批准前，产品仓库只读，不得派发实施、创建实施分支或 worktree。

## 7. 知识生命周期

- 查经验：任何阶段可用，只读，不推进 phase，不创建目录。
- 做复盘：只写当前工作流 `过程产物/学习草稿/`，强制 `tentative`。
- 正式项目知识：普通 promotion preview 在审查通过且当前 final acceptance 有效前就必须失败关闭，不创建 preview；之后仍需 preview-bound 用户批准才写入项目知识。
- 通用知识：只能从已验证的项目知识晋升，需要不同于项目归档的第二次独立批准。
- 冲突不得覆盖，要使用 `replaced_by`；`invalidated` / `replaced` 知识只解释历史，不能指导当前规划。
- 唯一提前例外是经证据和用户确认的 `route_failure`：只能写项目级失败事实，不得完成 `knowledge_archive`、不得把工作流标为完成、不得提升到通用知识。

## 8. 失败分类与 Review 收敛

四类失败必须分开：

- `implementation_failure`：第 1 次 `minimal_fix`，第 2 次 `root_cause_recheck`，同一稳定指纹第 3 次 `recover_required`；不得再生成普通修复任务。
- `route_failure`：停止实施，进入 `grh-recover`，带新事实重新出路线卡，由用户重新选择。
- `evidence_failure`：只补当前、可重现证据，不能修改失败类或宣称完成。
- `workflow_integrity_failure`：先 reconcile 状态、manifest、门禁和追加历史，不得继续业务修复。

指纹必须由问题 ID、失败验收/命令和 Git 基线构成，不能依赖自由文本措辞。阈值覆盖、新失败链或路线重选必须绑定用户批准的 `DEC/CHG`。

Review 意见分为阻塞、must-fix、可选优化和不成立。阻塞与 must-fix 必须在当前 Git 基线由后续独立复审关闭；只剩明确可选建议，且规格、测试和证据已满足时可收敛，不要追求 Reviewer “零意见”。

## 9. 安装与上游验收

- skills.sh 必须发现 Router + 七个薄入口，总数恰为 8，且 `-s '*'` 能在隔离 HOME 完整安装到 Codex 与 Claude Code。
- 只安装薄入口时，缺少主内核必须失败关闭、不创建运行时目录，并给出完整八入口安装建议。
- 安装只复制 Skill，不创建 `~/.grill-harness/`；首次 mutating 使用才创建运行时根；卸载 Skill 不删除用户 workflow 数据。
- 必需上游能力为 `grilling`、`domain-modeling`、`codebase-design`；缺失时失败关闭，不静默模拟、不自动安装。
- 上游检查可使用已提交 fixture 进行 offline compare；检查结果只能建议无需处理、在入口外人工更新、修改适配器、暂缓或人工决策。验收会话不得执行更新。
- README 对真实 update 必须保持“未验证”，不得把 CLI help 或 no-match 探针当作 update 成功证据。

## 10. 证据、并发与恢复

- 每项有效证据必须包含：`EVD` ID、对应 `REQ/DEC/TASK/ISSUE`、实际命令、绝对工作目录、执行时间、退出码、原始输出位置、Git 基线、产生者、可重现性和当前有效性。
- 命令没运行、输出被截断、基线变化、只有摘要或证据过期时，不得无条件通过。
- 并发任务必须同时满足：不同 worktree/独立工作区、独立分支、无写路径重叠、无共享契约/迁移/生成物冲突。否则必须串行。
- 每个任务开始前和结束后都要比较预计与实际 diff；并行组完成后必须做集成检查。
- 中断、手工编辑、manifest/state 冲突、基线漂移或证据冲突必须进入 reconcile/recover，不能选“看起来最完整”的文件当权威，不能静默倒退 phase。
- 迁移必须备份、临时转换、验证、原子替换、写报告；失败时保留原状态并可回滚。

## 11. PASS 阈值

### 静态层 PASS

必须同时满足：

- 八个公开入口齐全，七个薄入口没有复制状态机、脚本或模板；
- 对照 `docs/design.md` 和 V2 计划的 Critical = 0、Important = 0；
- `git diff --check`、Python 编译、全部 shell 语法、高可信 secret scan、已跟踪文本 personal-path scan 全部无未解释失败；
- 不存在产品仓库 Harness 运行时写入、真实 HOME 泄漏或凭据泄漏。

### 确定性层 PASS

必须同时满足：

- 全量 `unittest` 失败数为 0，且实际发现数不得低于当前 V2 基线的 300 项；
- 两个 integration 脚本退出码为 0，八入口安装数精确为 8，不完整安装、卸载保留数据和运行时隔离断言全部成立；
- 八入口、五维雷达、相似实现、三门禁、知识三模式/两步提升、四失败类、第三次恢复、Review 可选意见收敛、上游只读、证据、并发和恢复均有通过的确定性测试或可重现 fixture 证据；
- 真实 update 仍明确为未验证，没有被 no-match 探针伪装成通过。

### 真实模型层 PASS

只有在已授权、已登录且隔离的 Codex 与 Claude Code 环境中，全部选定场景的每个可适用 rubric 维度均为 `1`，且产品 fixture 无越权写入，该运行时才 PASS。

`401 Unauthorized`、`Not logged in`、缺少真实必需上游 Skill、runner 未执行模型或只有场景定义，都必须标记为“未验证”，不得计入 PASS。

### 总结论规则

- 静态层和确定性层全部 PASS，但真实模型层未验证：可以宣称“静态与确定性验收通过，真实模型端到端未验证”；不得宣称真实模型场景通过。
- 任一静态/确定性必须项失败，或存在未关闭 Critical/Important：“验收不通过”。
- 因环境、权限或证据缺失无法判定静态/确定性必须项：“无法验证”。
- “有条件通过”只适用于核心规格已满足、条件明确、非阻塞且已由用户接受的情形；不能用来掩盖缺证据或未关闭 Important。

## 12. 报告必填项

在 `<ACCEPTANCE_REPORT>` 中至少记录：

- 本地 HEAD SHA、跟踪的 remote SHA（不执行 fetch）、merge-base、分支名和验收前后工作树状态；
- 每个实际命令、工作目录、退出码、测试数/失败数和原始输出位置；
- 静态、确定性和真实模型三层的独立结论；
- 八入口逐项结论；
- 雷达/相似实现、三门禁、知识、失败/Review、安装/上游、证据/并发/恢复结论；
- secret/personal-path/runtime-boundary 扫描结果；
- skills.sh 实际结果和真实 update 未验证限制；
- 所有 Critical/Important，或明确“无”；
- 最终结论及其与上述 PASS 阈值的逐项对应。

不要合并、推送、发布、删除分支/worktree，也不要更改仓库可见性。
