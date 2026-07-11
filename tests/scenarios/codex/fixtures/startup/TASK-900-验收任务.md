# TASK-900 local startup validation

- Role: read-only verifier
- Project working directory: `PROJECT_DIR_PLACEHOLDER`
- Required input: `PROJECT_DIR_PLACEHOLDER/README.md`
- Authorized action: read the required input and report its first Markdown heading.
- Forbidden action: modify the project, Git state, global configuration, or any file except the output path.
- Stop condition: any required path is unavailable.
- Output path: `REPORT_PATH_PLACEHOLDER`
- Output format: Markdown containing `TASK-900`, the heading found, and a statement that no project file was modified.
