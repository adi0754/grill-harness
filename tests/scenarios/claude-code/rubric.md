# Scenario rubric

Each fresh-context run is scored independently using the behavioral dimensions
named in `docs/design.md` section 21.2:

1. 过早编码
2. 单问题 Grill
3. 路线质量
4. 用户门禁
5. ID 追踪
6. 真实仓库检查
7. 切片质量
8. diff 审查
9. 证据结论

Allowed values are `通过`, `失败`, `不适用`, and `未验证`. The design does not
define numeric weights or a pass threshold, so these tests do not invent a
numeric aggregate score. A runtime failure before model execution makes all
behavioral dimensions `未验证`, even if the fixture and command setup itself
was valid.
