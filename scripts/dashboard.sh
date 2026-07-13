#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
# shellcheck disable=SC1090
source "$ENV_FILE"
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
HERMES_BIN="$(command -v hermes || echo "$HOME/.local/bin/hermes")"

cat <<EOF
Dashboard 将仅监听 127.0.0.1。
远程访问请从本机建立 SSH 隧道：
  ssh -L 8080:127.0.0.1:8080 ${HERMES_USER}@<server>
EOF
exec "$HERMES_BIN" -p orchestrator dashboard --host 127.0.0.1
