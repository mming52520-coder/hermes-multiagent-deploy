#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"

mkdir -p "$BACKUP_DIR"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
dest="$BACKUP_DIR/hermes-state-$stamp.tar.gz"
was_running=false

if "$HERMES_BIN" -p orchestrator gateway status >/dev/null 2>&1; then
  was_running=true
  "$HERMES_BIN" -p orchestrator gateway stop
fi

restart_gateway() {
  if [[ "$was_running" == true ]]; then
    "$HERMES_BIN" -p orchestrator gateway start || true
  fi
}
trap restart_gateway EXIT

tar -C "$HOME" -czf "$dest" \
  --exclude='.hermes/hermes-agent' \
  --exclude='.hermes/venvs' \
  --exclude='.hermes/bin' \
  --exclude='*/logs/*' \
  --exclude='*/cache/*' \
  .hermes

chmod 0600 "$dest"
find "$BACKUP_DIR" -maxdepth 1 -type f -name 'hermes-state-*.tar.gz' \
  -printf '%T@ %p\n' | sort -nr | awk 'NR>7 {print $2}' | xargs -r rm -f

echo "Backup: $dest"
