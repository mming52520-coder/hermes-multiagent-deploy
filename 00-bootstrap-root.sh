#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/deploy.env}"

if [[ "${EUID}" -ne 0 ]]; then
  echo "错误：请以 root 执行：sudo $0 [deploy.env]" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误：找不到 $ENV_FILE。先复制 deploy.env.example 为 deploy.env。" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${HERMES_USER:?HERMES_USER 未设置}"
: "${PROJECT_DIR:?PROJECT_DIR 未设置}"
: "${OUTPUT_DIR:?OUTPUT_DIR 未设置}"
: "${BACKUP_DIR:?BACKUP_DIR 未设置}"

if [[ ! "$HERMES_USER" =~ ^[a-z_][a-z0-9_-]*$ ]]; then
  echo "错误：HERMES_USER 非法：$HERMES_USER" >&2
  exit 1
fi
for p in "$PROJECT_DIR" "$OUTPUT_DIR" "$BACKUP_DIR"; do
  if [[ "$p" != /* ]]; then
    echo "错误：路径必须是绝对路径：$p" >&2
    exit 1
  fi
done

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  ca-certificates curl git jq python3 python3-yaml sqlite3 rsync unzip \
  docker.io dbus-user-session

systemctl enable --now docker

if ! id "$HERMES_USER" >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash "$HERMES_USER"
fi
usermod -aG docker "$HERMES_USER"

install -d -m 0750 -o "$HERMES_USER" -g "$HERMES_USER" \
  "$(dirname "$PROJECT_DIR")" "$PROJECT_DIR" "$OUTPUT_DIR" "$BACKUP_DIR"

# 允许 systemd --user 服务在退出 SSH 后继续运行。
loginctl enable-linger "$HERMES_USER" || true

INSTALL_DIR="/opt/hermes-multiagent-deploy"
if [[ "$(realpath "$SCRIPT_DIR")" != "$INSTALL_DIR" ]]; then
  rm -rf "$INSTALL_DIR"
  install -d -m 0750 -o "$HERMES_USER" -g "$HERMES_USER" "$INSTALL_DIR"
  cp -a "$SCRIPT_DIR"/. "$INSTALL_DIR"/
fi
cp "$ENV_FILE" "$INSTALL_DIR/deploy.env"
chown -R "$HERMES_USER:$HERMES_USER" "$INSTALL_DIR"
chmod 0600 "$INSTALL_DIR/deploy.env"

uid="$(id -u "$HERMES_USER")"
mkdir -p "/run/user/$uid"
chown "$HERMES_USER:$HERMES_USER" "/run/user/$uid"
chmod 0700 "/run/user/$uid"
systemctl start "user@$uid.service" || true

cat <<EOF

主机初始化完成。

下一步执行：
  sudo -iu $HERMES_USER bash -lc \
    'cd $INSTALL_DIR && ./10-deploy.sh ./deploy.env'

说明：docker 组等价于较高主机权限，因此本方案使用专用的 $HERMES_USER 账户，
且 Worker 只挂载项目目录、Kanban 工作区和输出目录。
EOF
