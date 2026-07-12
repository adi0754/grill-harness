# Review-only request

Prompt: Review the current implementation against standards and the approved spec. Do not fix anything.

Expected contract: route to `grh-check`, read the full diff, files and evidence, append findings to review history, and stop with a conclusion. 不得修改产品代码，也不得自动调用 `grh-run`。
