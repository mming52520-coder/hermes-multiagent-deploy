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

"$ROOT/scripts/backup.sh" "$ENV_FILE"
"$HERMES_BIN" -p orchestrator gateway stop || true
"$HERMES_BIN" update
python3 "$ROOT/scripts/configure_profiles.py" "$ENV_FILE"
"$HERMES_BIN" -p orchestrator gateway start

for profile in orchestrator researcher builder reviewer; do
  "$HERMES_BIN" -p "$profile" doctor || true
done

if [[ -d "$HOME/.hermes/hermes-agent/.git" ]]; then
  git -C "$HOME/.hermes/hermes-agent" rev-parse HEAD > "$ROOT/installed-commit.txt"
fi

echo "升级完成。建议立即运行：$ROOT/scripts/smoke-test.sh $ENV_FILE"
