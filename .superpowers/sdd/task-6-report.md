# Task 6 实施报告：依赖预检与上游兼容跟踪

## 范围

本任务实现只读依赖预检、固定上游清单与兼容性分类。未修改 `SKILL.md`，未执行安装、更新、覆盖或接受上游变更。

## 危险路径 RED 证据

审查后先补充回归测试，并运行：

```text
python -m unittest discover -s tests -p 'test_preflight.py'
python -m unittest discover -s tests -p 'test_upstream_check.py'
```

RED 精确暴露以下问题：

- 旧实现调用 `npx skills add --help` 与 `npx skills update --help`；新的 FakeRunner 不提供这些危险探测，测试因此报错。
- CLI 不可用时，旧实现不能按带 scope 的标准根目录完成 filesystem fallback。
- CLI 成功时，旧实现错误地把未报告的文件系统 Skill 加入 inventory。
- 正文中的 `name:` 会被旧实现误判为 YAML 元数据。
- 远端 loader 没有返回 facts 时，旧报告仍声称 `online`。
- 缺失 repository、source hash、behavior contract 或 test result 时，旧 manifest 不会失败关闭。
- 重命名使用 `continue`，吞掉同一能力的行为契约与内容哈希变化；新增、删除和 commit 变化也未独立分类。

## 修复结果

- CLI discovery 只执行安全只读命令：project `npx skills list --json`、global `npx skills list -g --json`，以及顶层 `npx skills --help`。
- 永不调用 add/update 子命令进行探测。安装建议使用已验证 source `mattpocock/skills`，只为缺失的 required capabilities 生成一条批量命令。
- CLI discovery 成功时，文件系统只验证 CLI 报告路径；仅 CLI unavailable 时从带 project/global scope 的根目录 fallback。
- metadata name 只从文件开头的 YAML frontmatter 解析。
- 所有报告显式返回 `actions_performed: false` 与 `accepted_upstream_changes: false`。
- online 检查只有取得 remote facts 才成立；否则返回 `unavailable`。
- manifest 对审计字段、每项 source path/hash、每项行为契约和最近测试结果 fail-closed。
- 上游比较可同时报告 `added`、`removed`、`renamed`、`content-fix`、`content-change`、`metadata-change` 和 `behavior-contract-change`，并比较 commit 与对应路径 hash。

## 不变式

预检和上游检查均为只读模块。生成的命令只是用户审核建议，不会被模块执行；观察到的上游事实不会被自动写入、接受或应用。
