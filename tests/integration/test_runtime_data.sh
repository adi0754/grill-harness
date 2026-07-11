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

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

npx --yes skills add "$REPO_ROOT" -g -a codex -s grill-harness -y --copy
INSTALLED_SCRIPTS="$HOME/.agents/skills/grill-harness/scripts"
[[ -f "$INSTALLED_SCRIPTS/common.py" ]] || fail "isolated installed runtime scripts missing"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "installation created runtime data"

PROJECT="$TEMP_ROOT/project"
mkdir -p "$PROJECT"
printf 'project sentinel\n' >"$PROJECT/README.md"
project_before=$(shasum -a 256 "$PROJECT/README.md")

PYTHONPATH="$INSTALLED_SCRIPTS" python3 - <<'PY'
import common

paths = common.ensure_storage_layout()
assert all(path.is_dir() for path in paths.values())
PY

[[ -d "$GRILL_HARNESS_TEST_ROOT/配置" ]] || fail "first use did not create configured runtime root"
[[ -d "$GRILL_HARNESS_TEST_ROOT/上游管理" ]] || fail "first use did not create upstream directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/项目" ]] || fail "first use did not create projects directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/模板" ]] || fail "first use did not create templates directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/日志" ]] || fail "first use did not create logs directory"
[[ ! -e "$HOME/.grill-harness" ]] || fail "first use escaped to the default runtime root"
project_after=$(shasum -a 256 "$PROJECT/README.md")
[[ "$project_before" == "$project_after" ]] || fail "first use changed the fixture project"
[[ $(find "$PROJECT" -mindepth 1 -maxdepth 1 | wc -l | tr -d ' ') == 1 ]] \
  || fail "first use wrote runtime data into the fixture project"

printf 'workflow-v1\n' >"$GRILL_HARNESS_TEST_ROOT/项目/user-workflow.yaml"
before=$(shasum -a 256 "$GRILL_HARNESS_TEST_ROOT/项目/user-workflow.yaml")

# Update is deliberately represented by an isolated local fixture: it changes
# only installed package files and never invokes the real update subcommand.
printf 'updated installed package\n' >"$HOME/.agents/skills/grill-harness/update-fixture.txt"

after=$(shasum -a 256 "$GRILL_HARNESS_TEST_ROOT/项目/user-workflow.yaml")
[[ "$before" == "$after" ]] || fail "isolated update fixture changed user workflow data"

printf 'PASS: runtime creation and update isolation\n'
