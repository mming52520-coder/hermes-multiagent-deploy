#!/usr/bin/env bash
set -Eeuo pipefail
# The plugin installer is separate: startup does not rewrite user settings.
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
export HERMES_DESKTOP=0
if [[ -z "${HERMES_WEB_DIST:-}" && -f /workspace/.cache/hermes-workflow-dashboard-build/hermes_cli/web_dist/index.html ]]; then
  export HERMES_WEB_DIST=/workspace/.cache/hermes-workflow-dashboard-build/hermes_cli/web_dist
fi
exec hermes dashboard --host 127.0.0.1 --skip-build "$@"
