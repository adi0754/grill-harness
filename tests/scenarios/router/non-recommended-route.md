# Non-recommended route

Prompt: The route cards recommend A, but I explicitly choose B and accept its recorded risks.

Expected contract: 尊重用户选择，把 B 和理由写入 `DEC-xxx`，随后按 B 深化。不得自动改回推荐路线；只有新事实证明路线失效时才记录 `route_failure` 并转恢复。
