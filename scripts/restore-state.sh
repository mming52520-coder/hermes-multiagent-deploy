#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
ARCHIVE="${2:-}"

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "用法：$0 deploy.env /path/to/hermes-state-YYYY....tar.gz" >&2
  exit 2
fi

# shellcheck disable=SC1090
source "$ENV_FILE"
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"

"$HERMES_BIN" -p orchestrator gateway stop || true
safety="$BACKUP_DIR/pre-restore-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
tar -C "$HOME" -czf "$safety" \
  --exclude='.hermes/hermes-agent' --exclude='.hermes/venvs' --exclude='.hermes/bin' \
  .hermes
chmod 0600 "$safety"

tar -C "$HOME" -xzf "$ARCHIVE"
"$HERMES_BIN" -p orchestrator gateway start
echo "恢复完成。恢复前快照：$safety"
