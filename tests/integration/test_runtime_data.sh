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

status=$(python3 "$INSTALLED_SCRIPTS/grh.py" status --project "$PROJECT")
grep -Fq '"status": "not_started"' <<<"$status" \
  || fail "installed status command did not report a fresh project"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "read-only status created runtime data"

WORKFLOW="$TEMP_ROOT/state.yaml"
printf '%s\n' '{"phases":[{"id":"alignment","status":"pending"}],"artifacts":[],"tasks":[],"evidence":[],"gates":{}}' >"$WORKFLOW"
reconcile=$(python3 "$INSTALLED_SCRIPTS/grh.py" reconcile --workflow "$WORKFLOW")
grep -Fq '"valid": true' <<<"$reconcile" \
  || fail "installed reconcile command rejected a valid workflow"

upstream=$(python3 "$INSTALLED_SCRIPTS/grh.py" upstream-check \
  --previous "$REPO_ROOT/tests/fixtures/upstream/current.json" \
  --facts "$REPO_ROOT/tests/fixtures/upstream/current.json" \
  --checked-at 2026-07-12T00:00:00Z --offline)
grep -Fq '"actions_performed": false' <<<"$upstream" \
  || fail "installed upstream-check was not read-only"

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

set +e
update_output=$(npx --yes skills update grill-harness -g -y 2>&1)
update_status=$?
set -e

after=$(shasum -a 256 "$GRILL_HARNESS_TEST_ROOT/项目/user-workflow.yaml")
[[ "$before" == "$after" ]] || fail "isolated update attempt changed user workflow data"
[[ $update_status == 0 ]] || fail "isolated update probe failed unexpectedly: $update_output"
grep -Fq 'No installed skills found matching: grill-harness' <<<"$update_output" \
  || fail "local install unexpectedly became updateable; review the isolation strategy"

printf 'PASS: runtime creation isolation\n'
printf 'SKIP: real update behavior unverified; current CLI does not track local installs\n'
