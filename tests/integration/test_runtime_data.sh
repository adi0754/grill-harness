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

hash_file() {
  python3 -c 'import hashlib, pathlib, sys; print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())' "$1"
}

npx --yes skills add "$REPO_ROOT" -g -a codex -s grill-harness -y --copy
INSTALLED_SCRIPTS="$HOME/.agents/skills/grill-harness/scripts"
[[ -f "$INSTALLED_SCRIPTS/common.py" ]] || fail "isolated installed runtime scripts missing"
[[ ! -e "$GRILL_HARNESS_TEST_ROOT" ]] || fail "installation created runtime data"

PROJECT="$TEMP_ROOT/project"
mkdir -p "$PROJECT"
printf 'project sentinel\n' >"$PROJECT/README.md"
git -C "$PROJECT" init --quiet
git -C "$PROJECT" config user.email tests@example.com
git -C "$PROJECT" config user.name 'Grill Harness Tests'
git -C "$PROJECT" add README.md
git -C "$PROJECT" commit --quiet -m fixture
project_before=$(hash_file "$PROJECT/README.md")

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
  --previous "$REPO_ROOT/skills/grill-harness/references/上游清单.yaml" \
  --facts "$REPO_ROOT/tests/fixtures/upstream/current.json" \
  --checked-at 2026-07-12T00:00:00Z --offline)
grep -Fq '"actions_performed": false' <<<"$upstream" \
  || fail "installed upstream-check was not read-only"

init=$(python3 "$INSTALLED_SCRIPTS/grh.py" init \
  --project "$PROJECT" --workflow-name '发布检查' \
  --workflow-key release-check --created-date 2026-07-12)
grep -Fq '"created": true' <<<"$init" || fail "installed init did not create workflow"
WORKFLOW_PATH=$(python3 -c 'import json, sys; print(json.load(sys.stdin)["workflow_path"])' <<<"$init")
second_init=$(python3 "$INSTALLED_SCRIPTS/grh.py" init \
  --project "$PROJECT" --workflow-name '发布检查' \
  --workflow-key release-check --created-date 2026-07-12)
grep -Fq '"created": false' <<<"$second_init" || fail "installed init was not idempotent"

[[ -d "$GRILL_HARNESS_TEST_ROOT/配置" ]] || fail "first use did not create configured runtime root"
[[ -d "$GRILL_HARNESS_TEST_ROOT/上游管理" ]] || fail "first use did not create upstream directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/项目" ]] || fail "first use did not create projects directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/模板" ]] || fail "first use did not create templates directory"
[[ -d "$GRILL_HARNESS_TEST_ROOT/日志" ]] || fail "first use did not create logs directory"
[[ -f "$GRILL_HARNESS_TEST_ROOT/项目索引.yaml" ]] || fail "first use did not create project index"
[[ -f "$WORKFLOW_PATH/系统/state.yaml" ]] || fail "first use did not create workflow state"
[[ ! -e "$HOME/.grill-harness" ]] || fail "first use escaped to the default runtime root"
project_after=$(hash_file "$PROJECT/README.md")
[[ "$project_before" == "$project_after" ]] || fail "first use changed the fixture project"
[[ -z $(git -C "$PROJECT" status --porcelain) ]] || fail "first use dirtied the fixture project"

printf 'workflow-v1\n' >"$WORKFLOW_PATH/核心文档/user-workflow.md"
before=$(hash_file "$WORKFLOW_PATH/核心文档/user-workflow.md")

set +e
update_output=$(npx --yes skills update grill-harness -g -y 2>&1)
update_status=$?
set -e

after=$(hash_file "$WORKFLOW_PATH/核心文档/user-workflow.md")
[[ "$before" == "$after" ]] || fail "isolated update attempt changed user workflow data"
[[ $update_status == 0 ]] || fail "isolated update probe failed unexpectedly: $update_output"
grep -Fq 'No installed skills found matching: grill-harness' <<<"$update_output" \
  || fail "local install unexpectedly became updateable; review the isolation strategy"

npx --yes skills remove grill-harness -g -a codex -y
after_uninstall=$(hash_file "$WORKFLOW_PATH/核心文档/user-workflow.md")
[[ "$before" == "$after_uninstall" ]] || fail "isolated uninstall changed user workflow data"
[[ ! -e "$HOME/.agents/skills/grill-harness" ]] || fail "isolated uninstall left installed skill"

printf 'PASS: runtime creation isolation\n'
printf 'SKIP: real update behavior unverified; current CLI does not track local installs\n'
