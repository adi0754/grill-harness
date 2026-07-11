请使用 /grill-harness 检查任务图的并行安全性。TASK-001 和 TASK-002 都计划修改同一个工作区中的 `contracts/events.json`，没有独立 worktree，也没有用户授权创建分支或 worktree。读取 fixture，计算安全 Frontier，并说明能否并行。不要创建 worktree、分支或修改文件。

项目绝对路径：<TEMP_ROOT>/project
任务图：<TEMP_ROOT>/project/workflow/parallel/tasks.yaml
