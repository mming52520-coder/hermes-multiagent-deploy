#!/usr/bin/env bash
set -Eeuo pipefail
# An explicitly approved reinstall can restore this supported pin. A new
# upstream version needs a separate compatibility audit before changing it.
if [[ "${HERMES_APPROVED_UPGRADE_COMMIT:-}" != aaf5691261f12601db845386d650dce1cdfa30f9 ]]; then
  echo "拒绝未审计升级；请先阅读 docs/MULTIAGENT_WORKFLOW_P0.md 的升级/回滚要求。" >&2
  exit 1
fi
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
bash "$ROOT/scripts/install-pinned-hermes.sh"
python3 "$ROOT/scripts/hermes_baseline.py" --hermes-bin "$HERMES_BIN"
python3 "$ROOT/scripts/configure_profiles.py" "$ENV_FILE"
"$HERMES_BIN" -p orchestrator gateway start

for profile in orchestrator researcher builder reviewer; do
  "$HERMES_BIN" -p "$profile" doctor || true
done

printf '%s\n' aaf5691261f12601db845386d650dce1cdfa30f9 > "$ROOT/installed-commit.txt"

echo "升级完成。建议立即运行：$ROOT/scripts/smoke-test.sh $ENV_FILE"
