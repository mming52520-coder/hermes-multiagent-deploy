#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"

echo "=== Gateway ==="
"$HERMES_BIN" -p orchestrator gateway status || true
echo
echo "=== Kanban diagnostics ==="
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" diagnostics || true
echo
echo "=== Kanban stats ==="
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" stats || true
echo
echo "=== Active tasks ==="
"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" list || true
echo
echo "=== Docker ==="
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' || true
echo
echo "=== Disk ==="
df -h "$HOME" "$PROJECT_DIR" "$BACKUP_DIR" | awk '!seen[$0]++'
