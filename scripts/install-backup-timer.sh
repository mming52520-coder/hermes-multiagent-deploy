#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${1:-$ROOT/deploy.env}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

unit_dir="$HOME/.config/systemd/user"
mkdir -p "$unit_dir"

cat > "$unit_dir/hermes-state-backup.service" <<EOF
[Unit]
Description=Backup Hermes multi-agent state
After=hermes-gateway-orchestrator.service

[Service]
Type=oneshot
ExecStart=$ROOT/scripts/backup.sh $ENV_FILE
EOF

cat > "$unit_dir/hermes-state-backup.timer" <<'EOF'
[Unit]
Description=Daily Hermes state backup

[Timer]
OnCalendar=*-*-* 03:15:00
Persistent=true
RandomizedDelaySec=900

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now hermes-state-backup.timer
