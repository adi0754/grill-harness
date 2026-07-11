# Codex fresh-context scenarios

Run `./run.sh`. The runner creates an isolated temporary `HOME`, `CODEX_HOME`, Skill directory, and Grill Harness data root. It does not read or copy user credentials. Product fixtures are run with Codex's read-only sandbox. The startup-prompt check alone receives write access to an isolated report directory.

The runner copies only Grill Harness itself. It does not install or simulate required upstream capabilities; a fully authenticated first-class rerun must separately provision real `grilling`, `domain-modeling`, and `codebase-design` Skills inside the isolated Skill root.

Raw JSONL, final answers, exit codes, version information, and the startup report are written beneath the output directory passed as the first argument (default: `../results/codex-latest`).
