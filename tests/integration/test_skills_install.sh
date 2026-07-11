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

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

discovery=$(run_skills add "$REPO_ROOT" --list)
grep -q 'grill-harness' <<<"$discovery" || fail "current skills CLI did not discover grill-harness"

help=$(run_skills --help)
grep -Eq 'update \[skills\.\.\.\]' <<<"$help" || fail "current skills CLI update syntax changed"
grep -Eq 'remove \[skills\]' <<<"$help" || fail "current skills CLI remove syntax changed"

run_skills add "$REPO_ROOT" -g -a codex claude-code -s grill-harness -y --copy
run_skills add mattpocock/skills -g -a codex claude-code \
  -s grilling domain-modeling codebase-design -y --copy

CODEX_SKILL="$HOME/.agents/skills/grill-harness"
CLAUDE_SKILL="$HOME/.claude/skills/grill-harness"
[[ -f "$CODEX_SKILL/SKILL.md" ]] || fail "Codex isolated install missing"
[[ -f "$CLAUDE_SKILL/SKILL.md" ]] || fail "Claude Code isolated install missing"
for dependency in grilling domain-modeling codebase-design; do
  [[ -f "$HOME/.agents/skills/$dependency/SKILL.md" ]] \
    || fail "isolated dependency install missing: $dependency"
done
preflight=$(python3 "$CODEX_SKILL/scripts/grh.py" preflight \
  --skill-root "$HOME/.agents/skills")
grep -Fq '"ready": true' <<<"$preflight" \
  || fail "installed preflight did not verify required dependencies"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "installation created runtime data"
[[ ! -e "$HOME/.grill-harness" ]] || fail "installation created default runtime data"

printf 'user workflow data\n' >"$TEMP_ROOT/runtime-sentinel"
mkdir -p "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example"
cp "$TEMP_ROOT/runtime-sentinel" "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml"
before=$(shasum -a 256 "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml")

run_skills remove grill-harness -g -a codex claude-code -y

after=$(shasum -a 256 "$GRILL_HARNESS_TEST_ROOT/项目/example/工作流/example/state.yaml")
[[ "$before" == "$after" ]] || fail "uninstall changed isolated user workflow data"
[[ ! -e "$CODEX_SKILL" ]] || fail "Codex uninstall left installed skill"
[[ ! -e "$CLAUDE_SKILL" ]] || fail "Claude Code uninstall left installed skill"

grep -Fq 'npx skills add "$PWD" -g -a codex claude-code -s grill-harness -y --copy' "$REPO_ROOT/README.md" \
  || fail "README is missing the verified install command"
grep -Fq 'npx skills update grill-harness -g' "$REPO_ROOT/README.md" \
  || fail "README is missing the help-verified update command"
grep -Fq '运行时行为未验证' "$REPO_ROOT/README.md" \
  || fail "README does not label runtime behavior as unverified"

printf 'PASS: isolated skills discovery, install, uninstall, and documentation\n'
