#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/deploy.env}"
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || true)"
if [[ -z "$HERMES_BIN" ]]; then
  HERMES_BIN="$HOME/.local/bin/hermes"
fi

echo "Gateway 状态："
"$HERMES_BIN" -p orchestrator gateway status

key="deploy-smoke-$(date -u +%Y%m%dT%H%M%SZ)"
body=$(cat <<EOF
Perform a read-only deployment smoke test.

Project: $PROJECT_DIR

Required:
1. Read the top-level directory.
2. If it is a Git repository, report the current HEAD and working-tree status.
3. Do not modify any project file.
4. Complete the Kanban task with metadata containing inspected_paths and verification.
EOF
)

task_json="$("$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" create \
  "deployment smoke test" \
  --body "$body" \
  --assignee researcher \
  --workspace "dir:$PROJECT_DIR" \
  --max-runtime 8m \
  --max-retries 1 \
  --idempotency-key "$key" \
  --json)"

task_id="$(jq -r '.id' <<<"$task_json")"
if [[ -z "$task_id" || "$task_id" == "null" ]]; then
  echo "错误：未获得 smoke task id：" >&2
  echo "$task_json" >&2
  exit 1
fi

echo "Smoke task: $task_id"
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" dispatch --max 1 >/dev/null || true

deadline=$((SECONDS + 600))
while (( SECONDS < deadline )); do
  payload="$("$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" show "$task_id" --json)"
  status="$(jq -r '.task.status' <<<"$payload")"
  printf '  status=%s\n' "$status"
  case "$status" in
    done)
      echo "端到端 Smoke Test 通过。"
      jq '{status: .task.status, summary: .latest_summary, runs: .runs}' <<<"$payload"
      exit 0
      ;;
    blocked|archived)
      echo "Smoke Test 失败：任务进入 $status。" >&2
      jq . <<<"$payload" >&2
      "$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" log "$task_id" --tail 20000 || true
      exit 1
      ;;
  esac
  sleep 10
done

echo "Smoke Test 超时。" >&2
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" show "$task_id" --json | jq . >&2
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" log "$task_id" --tail 20000 || true
exit 1
