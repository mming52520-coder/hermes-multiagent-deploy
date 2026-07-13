#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${1:-$SCRIPT_DIR/deploy.env}"

if [[ "${EUID}" -eq 0 ]]; then
  echo "错误：本脚本必须以专用 Hermes 用户运行，不能以 root 运行。" >&2
  exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
  echo "错误：找不到 $ENV_FILE" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

required=(
  HERMES_USER PROJECT_SLUG BOARD_SLUG BOARD_NAME PROJECT_DIR OUTPUT_DIR BACKUP_DIR
  ORCHESTRATOR_PROVIDER ORCHESTRATOR_MODEL
  RESEARCHER_PROVIDER RESEARCHER_MODEL
  BUILDER_PROVIDER BUILDER_MODEL
  REVIEWER_PROVIDER REVIEWER_MODEL
  DOCKER_IMAGE
)
for k in "${required[@]}"; do
  if [[ -z "${!k:-}" ]]; then
    echo "错误：$k 未设置。" >&2
    exit 1
  fi
done
if [[ "$(id -un)" != "$HERMES_USER" ]]; then
  echo "错误：当前用户是 $(id -un)，应使用 $HERMES_USER。" >&2
  exit 1
fi

python3 "$SCRIPT_DIR/scripts/configure_profiles.py" "$ENV_FILE" --validate-only

if [[ "${RUN_PROVIDER_PREFLIGHT:-true}" == "true" ]]; then
  echo "执行模型 API 预检（每个唯一 provider/model 一个极小请求）..."
  python3 "$SCRIPT_DIR/scripts/check-model-apis.py" "$ENV_FILE"
fi

export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"

resolve_hermes() {
  local c
  for c in "$(command -v hermes 2>/dev/null || true)" \
           "$HOME/.local/bin/hermes" \
           "$HOME/.hermes/bin/hermes"; do
    if [[ -n "$c" && -x "$c" ]]; then
      printf '%s\n' "$c"
      return 0
    fi
  done
  return 1
}

if ! HERMES_BIN="$(resolve_hermes)"; then
  echo "安装 Hermes Agent..."
  curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
  hash -r
  HERMES_BIN="$(resolve_hermes)" || {
    echo "错误：安装完成后仍找不到 hermes 命令。" >&2
    exit 1
  }
fi
echo "Hermes: $HERMES_BIN"
"$HERMES_BIN" --version || true

mkdir -p "$PROJECT_DIR" "$OUTPUT_DIR" "$BACKUP_DIR"

if [[ -n "${PROJECT_GIT_URL:-}" && ! -d "$PROJECT_DIR/.git" ]]; then
  if [[ -n "$(find "$PROJECT_DIR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    echo "错误：PROJECT_DIR 非空且不是 Git 仓库，拒绝自动 clone：$PROJECT_DIR" >&2
    exit 1
  fi
  echo "克隆项目仓库..."
  git clone --branch "${PROJECT_GIT_REF:-main}" "$PROJECT_GIT_URL" "$PROJECT_DIR"
fi

create_profile() {
  local name="$1"
  local description="$2"
  if [[ ! -d "$HOME/.hermes/profiles/$name" ]]; then
    "$HERMES_BIN" profile create "$name" --description "$description"
  else
    echo "Profile 已存在，保留并更新配置：$name"
  fi
}

create_profile orchestrator "只负责拆解、路由、依赖编排和最终验收；不直接实施。"
create_profile researcher "只读调查代码、资料与外部文档，提交带证据的研究结论。"
create_profile builder "在隔离工作区实现代码、运行测试并留下可审查的提交证据。"
create_profile reviewer "独立审查代码、测试、安全和验收条件，不替实现者背书。"

python3 "$SCRIPT_DIR/scripts/configure_profiles.py" "$ENV_FILE"

if docker image inspect "$DOCKER_IMAGE" >/dev/null 2>&1; then
  echo "Docker Worker 镜像已存在，跳过远程拉取：$DOCKER_IMAGE"
else
  echo "拉取 Docker Worker 镜像：$DOCKER_IMAGE"
  docker pull "$DOCKER_IMAGE"
fi

echo "创建/更新 Kanban Board：$BOARD_SLUG"
"$HERMES_BIN" -p orchestrator kanban boards create "$BOARD_SLUG" \
  --name "$BOARD_NAME" \
  --description "Hermes multi-agent board for $PROJECT_SLUG" \
  --default-workdir "$PROJECT_DIR" \
  --switch

"$HERMES_BIN" -p orchestrator kanban --board "$BOARD_SLUG" init

echo "安装并启动 Orchestrator Gateway..."
"$HERMES_BIN" -p orchestrator gateway install
if ! "$HERMES_BIN" -p orchestrator gateway restart; then
  "$HERMES_BIN" -p orchestrator gateway start
fi

"$SCRIPT_DIR/scripts/install-backup-timer.sh" "$ENV_FILE" || {
  echo "警告：自动备份 timer 安装失败，可稍后手工执行 scripts/install-backup-timer.sh。" >&2
}

echo "检查 Profiles..."
for profile in orchestrator researcher builder reviewer; do
  echo "== $profile =="
  "$HERMES_BIN" -p "$profile" doctor || true
done

# 记录实际安装的 Git commit，便于审计与回滚。
managed_repo="$HOME/.hermes/hermes-agent"
if [[ -d "$managed_repo/.git" ]]; then
  git -C "$managed_repo" rev-parse HEAD > "$SCRIPT_DIR/installed-commit.txt"
fi

if [[ "${RUN_SMOKE_TEST:-true}" == "true" ]]; then
  "$SCRIPT_DIR/scripts/smoke-test.sh" "$ENV_FILE"
fi

cat <<EOF

部署完成。

常用命令：
  $SCRIPT_DIR/scripts/status.sh $ENV_FILE
  $SCRIPT_DIR/scripts/submit-feature.sh $ENV_FILE "实现一个明确的功能目标"
  $HERMES_BIN -p orchestrator kanban --board $BOARD_SLUG watch
  journalctl --user -u hermes-gateway-orchestrator.service -f

可选 Telegram：
  deploy.env 中填写 TELEGRAM_BOT_TOKEN 与 TELEGRAM_ALLOWED_USERS 后，
  重新执行本脚本，随后给 Bot 发送一条消息并执行 /sethome。

Dashboard 仅绑定本机：
  $SCRIPT_DIR/scripts/dashboard.sh $ENV_FILE
EOF
