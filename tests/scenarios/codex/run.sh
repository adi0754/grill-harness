#!/usr/bin/env bash
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
SAFETY="$HERE/../runtime_safety.py"
OUT="${1:-$HERE/../results/codex-latest}"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/grh-codex.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

mkdir -p "$OUT/raw" "$OUT/final" "$TMP/home/.codex/skills" "$TMP/runtime" "$TMP/startup-output" "$TMP/tmp"
cp -R "$REPO/skills/grill-harness" "$TMP/home/.codex/skills/grill-harness"

run_isolated() {
  python3 "$SAFETY" exec-env \
    --home "$TMP/home" \
    --temp-dir "$TMP/tmp" \
    --set "CODEX_HOME=$TMP/home/.codex" \
    --set "XDG_CONFIG_HOME=$TMP/home/.config" \
    --set "XDG_CACHE_HOME=$TMP/home/.cache" \
    --set "GRILL_HARNESS_TEST_ROOT=$TMP/runtime" \
    -- "$@"
}

sanitize_files() {
  python3 "$SAFETY" sanitize-file \
    --temp-root "$TMP" \
    --repo-root "$REPO" \
    --fixture-root "$HERE/fixtures" \
    "$@"
}

run_isolated codex --version > "$OUT/version.txt" 2>&1
printf '%s\n' "HOME=$TMP/home" "CODEX_HOME=$TMP/home/.codex" "GRILL_HARNESS_TEST_ROOT=$TMP/runtime" "fixture=$HERE/fixtures" > "$OUT/isolation.txt"
sanitize_files "$OUT/isolation.txt"

set +e
run_isolated codex exec --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check \
    --sandbox read-only -C "$HERE/fixtures" --json "Reply with OK." </dev/null \
    > "$OUT/raw/auth-probe.jsonl" 2>&1
AUTH_EXIT=$?
printf '%s\n' "$AUTH_EXIT" > "$OUT/raw/auth-probe.exit"
if [[ "$AUTH_EXIT" -ne 0 ]]; then
  sanitize_files "$OUT/raw/auth-probe.jsonl"
  python3 - "$HERE/scenarios.json" "$OUT" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[2])
reason = "UNVERIFIED: isolated Codex HOME has no authentication; see raw/auth-probe.jsonl."
for item in json.load(open(sys.argv[1], encoding="utf-8")):
    (out / "final" / f'{item["id"]}.md').write_text(reason + "\n", encoding="utf-8")
    (out / "raw" / f'{item["id"]}.exit').write_text("UNVERIFIED\n", encoding="utf-8")
(out / "final" / "startup-prompt.md").write_text(reason + "\n", encoding="utf-8")
(out / "raw" / "startup-prompt.exit").write_text("UNVERIFIED\n", encoding="utf-8")
PY
  printf '%s\n' 'UNVERIFIED: isolated Codex HOME has no authentication; user credentials were not read or copied.' > "$OUT/status.txt"
  exit 0
fi

python3 - "$HERE/scenarios.json" <<'PY' | while IFS=$'\t' read -r id prompt; do
import json, sys
for item in json.load(open(sys.argv[1], encoding="utf-8")):
    print(item["id"] + "\t" + item["prompt"].replace("\n", " "))
PY
  run_isolated codex exec --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check \
      --sandbox read-only -C "$HERE/fixtures" --json -o "$OUT/final/$id.md" "$prompt" \
      </dev/null > "$OUT/raw/$id.jsonl" 2>&1
  printf '%s\n' "$?" > "$OUT/raw/$id.exit"
  sanitize_files "$OUT/raw/$id.jsonl" "$OUT/final/$id.md"
done

TASK="$TMP/TASK-900-验收任务.md"
REPORT="$TMP/startup-output/TASK-900-report.md"
sed -e "s#PROJECT_DIR_PLACEHOLDER#$HERE/fixtures/project#g" \
    -e "s#REPORT_PATH_PLACEHOLDER#$REPORT#g" \
    "$HERE/fixtures/startup/TASK-900-验收任务.md" > "$TASK"
START_PROMPT="读取任务包 $TASK，检查真实仓库，只执行授权范围，运行要求的验证，并把报告写回任务包指定路径；遇到停止条件立即停止并报告。"
run_isolated codex exec --ephemeral --ignore-user-config --ignore-rules --skip-git-repo-check \
    --sandbox workspace-write --add-dir "$TMP/startup-output" -C "$HERE/fixtures/project" \
    --json -o "$OUT/final/startup-prompt.md" "$START_PROMPT" </dev/null > "$OUT/raw/startup-prompt.jsonl" 2>&1
printf '%s\n' "$?" > "$OUT/raw/startup-prompt.exit"
if [[ -f "$REPORT" ]]; then
  cp "$REPORT" "$OUT/startup-report.md"
  sanitize_files "$OUT/startup-report.md"
fi
sanitize_files "$OUT/raw/startup-prompt.jsonl" "$OUT/final/startup-prompt.md"
set -e

printf '%s\n' 'COMPLETE: inspect exit files and score responses against ../results/RUBRIC.md.' > "$OUT/status.txt"
