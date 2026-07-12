#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
TEMP_ROOT=$(mktemp -d)
trap 'rm -rf "$TEMP_ROOT"' EXIT

export HOME="$TEMP_ROOT/home"
export CODEX_HOME="$TEMP_ROOT/codex-home"
export XDG_CONFIG_HOME="$TEMP_ROOT/xdg-config"
export XDG_DATA_HOME="$TEMP_ROOT/xdg-data"
export npm_config_cache="$TEMP_ROOT/npm-cache"
export GRILL_HARNESS_TEST_ROOT="$TEMP_ROOT/runtime"
export LANG=C
export LC_ALL=C
mkdir -p "$HOME" "$CODEX_HOME" "$XDG_CONFIG_HOME" "$XDG_DATA_HOME"

run_skills() {
  npx --yes skills "$@"
}

PUBLIC_ENTRIES=(
  grill-harness
  grh-start
  grh-plan
  grh-run
  grh-check
  grh-recover
  grh-learn
  grh-upstream-check
)

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

hash_file() {
  python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"
}

discovery=$(run_skills add "$REPO_ROOT" --list)
for entry in "${PUBLIC_ENTRIES[@]}"; do
  grep -q "$entry" <<<"$discovery" || fail "current skills CLI did not discover $entry"
done

help=$(run_skills --help)
grep -Eq 'update \[skills\.\.\.\]' <<<"$help" || fail "current skills CLI update syntax changed"
grep -Eq 'remove \[skills\]' <<<"$help" || fail "current skills CLI remove syntax changed"

run_skills add "$REPO_ROOT" -g -a codex claude-code -s '*' -y --copy
run_skills add mattpocock/skills -g -a codex claude-code \
  -s grilling domain-modeling codebase-design -y --copy

CODEX_SKILL="$HOME/.agents/skills/grill-harness"
CLAUDE_SKILL="$HOME/.claude/skills/grill-harness"
for entry in "${PUBLIC_ENTRIES[@]}"; do
  [[ -f "$HOME/.agents/skills/$entry/SKILL.md" ]] || fail "Codex isolated install missing: $entry"
  [[ -f "$HOME/.claude/skills/$entry/SKILL.md" ]] || fail "Claude Code isolated install missing: $entry"
done
for dependency in grilling domain-modeling codebase-design; do
  [[ -f "$HOME/.agents/skills/$dependency/SKILL.md" ]] \
    || fail "isolated dependency install missing: $dependency"
done
python3 - "$HOME/.agents/skills" "$CODEX_SKILL/scripts" <<'PY'
import sys
from pathlib import Path

skills_root = Path(sys.argv[1])
sys.path.insert(0, sys.argv[2])
import preflight

def no_cli(_command):
    raise FileNotFoundError("isolated filesystem verification")

report = preflight.run_preflight(
    skill_roots={"global": [skills_root]},
    runner=no_cli,
    check_harness_entries=True,
    invoking_entry="grh-start",
)
assert report["ready"] is True, report
assert report["entry_ready"] is True, report
assert report["overall_ready"] is True, report
assert report["harness_installation"]["missing_entries"] == [], report
assert report["harness_installation"]["contract_compatible"] is True, report
assert report["actions_performed"] is False, report
PY
preflight=$(python3 "$CODEX_SKILL/scripts/grh.py" preflight \
  --skill-root "$HOME/.agents/skills")
grep -Fq '"ready": true' <<<"$preflight" \
  || fail "installed preflight did not verify required dependencies"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "installation created runtime data"
[[ ! -e "$HOME/.grill-harness" ]] || fail "installation created default runtime data"

run_skills remove "${PUBLIC_ENTRIES[@]}" -g -a codex claude-code -y
run_skills add "$REPO_ROOT" -g -a codex claude-code -s grh-learn -y --copy
[[ -f "$HOME/.agents/skills/grh-learn/SKILL.md" ]] || fail "incomplete install missing grh-learn"
[[ ! -e "$HOME/.agents/skills/grill-harness" ]] || fail "incomplete install unexpectedly contains core"
grep -Fq '缺少 grill-harness 主内核时失败关闭' "$HOME/.agents/skills/grh-learn/SKILL.md" \
  || fail "thin entry lacks core-missing fail-closed guidance"
grep -Fq -- "-s '*'" "$HOME/.agents/skills/grh-learn/SKILL.md" \
  || fail "thin entry lacks complete-install guidance"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "incomplete installation created runtime data"
[[ ! -e "$HOME/.grill-harness" ]] || fail "incomplete installation created default runtime data"
run_skills remove grh-learn -g -a codex claude-code -y

run_skills add "$REPO_ROOT" -g -a codex claude-code -s '*' -y --copy

printf 'user workflow data\n' >"$TEMP_ROOT/runtime-sentinel"
mkdir -p "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example"
cp "$TEMP_ROOT/runtime-sentinel" "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml"
before=$(hash_file "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml")

run_skills remove "${PUBLIC_ENTRIES[@]}" -g -a codex claude-code -y

after=$(hash_file "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml")
[[ "$before" == "$after" ]] || fail "uninstall changed isolated user workflow data"
for entry in "${PUBLIC_ENTRIES[@]}"; do
  [[ ! -e "$HOME/.agents/skills/$entry" ]] || fail "Codex uninstall left installed skill: $entry"
  [[ ! -e "$HOME/.claude/skills/$entry" ]] || fail "Claude Code uninstall left installed skill: $entry"
done

printf 'PASS: eight-entry wildcard discovery, complete/incomplete install, and uninstall\n'
