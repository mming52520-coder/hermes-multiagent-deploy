#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
GOAL="${2:-}"
if [[ -z "$GOAL" ]]; then
  echo "用法：$0 deploy.env \"清晰、可验收的功能目标\"" >&2
  exit 2
fi
# shellcheck source=/dev/null
set -a
source "$ENV_FILE"
set +a
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"

# Use Hermes' interpreter rather than importing its API from system Python.
workflow_python="${HERMES_PYTHON:-}"
if [[ -z "$workflow_python" ]]; then
  hermes_command="$(command -v hermes)"
  hermes_directory="$(dirname -- "$(realpath "$hermes_command")")"
  for candidate in "$hermes_directory/python" "$HOME/.hermes/hermes-agent/venv/bin/python"; do
    if [[ -x "$candidate" ]]; then
      workflow_python="$candidate"
      break
    fi
  done
fi
if [[ -z "$workflow_python" ]]; then
  echo "找不到 Hermes Python；请设置 HERMES_PYTHON 为已验证 Hermes 安装的解释器。" >&2
  exit 1
fi
# Submission creates triage cards. Only an operator start authorizes writes.
exec "$workflow_python" "$ROOT/scripts/workflow_control.py" --env "$ENV_FILE" submit "$GOAL"
