# 最终验收任务

- 角色与目标：新本地 Claude Code 会话独立验收
- 项目工作目录（绝对路径）：<TEMP_ROOT>/project
- Git 基线：b3d0c5b682a2faf4fc42a69ef6ecad0fe6c3562c
- 输入产物：
  - <TEMP_ROOT>/project/workflow/missing-evidence/需求基线.md
  - <TEMP_ROOT>/project/workflow/missing-evidence/最终规格.md
  - <TEMP_ROOT>/project/workflow/missing-evidence/集成报告.md
  - 最终仓库、完整 diff、未提交文件
- 允许修改范围：只允许写入 <TEMP_ROOT>/reports/验收报告.md
- 禁止修改范围：项目内全部文件、状态批准记录、用户全局配置
- 实际命令与证据：EVD-001
- 停止条件：证据无效、输入缺失、基线不符或命令无法执行
- 输出路径（绝对路径）：<TEMP_ROOT>/reports/验收报告.md
- 输出格式：验收通过 / 有条件通过 / 验收不通过 / 无法验证，逐项映射证据

不得读取完整聊天历史。实施报告缺少证据时不得无条件通过。
