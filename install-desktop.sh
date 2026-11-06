#!/usr/bin/env bash
# Install and open the desktop app from the extracted release package.
set -euo pipefail
umask 077
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
package="$PWD"
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
pin=bf0203a794a07aac3ff764972ab9087baa4e4f4e
fail() { printf '%s\n' "$*" >&2; exit 1; }

[[ -f MANIFEST.sha256 && -f web_dist/index.html ]] || fail "请从已解压的桌面发布包运行安装器。"
sha256sum --quiet -c MANIFEST.sha256
command -v hermes >/dev/null || fail "请先安装指定提交的 Hermes v0.22.5（见 docs/DESKTOP_APP.md）。"
command -v gtk-launch >/dev/null || fail "请先安装 libgtk-3-bin。"
/usr/bin/python3 - <<'PY'
import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("WebKit2", "4.1")
from gi.repository import Gtk, WebKit2
if not Gtk.init_check()[0]:
    raise SystemExit("请在 Linux 图形桌面会话中运行安装器。")
PY
version="$(hermes --version)"
source_dir="$(sed -n 's/^Install directory: //p' <<< "$version")"
[[ -n "$source_dir" && "$(git -C "$source_dir" rev-parse HEAD)" == "$pin" ]] ||
  fail "Hermes 必须来自固定提交 $pin。"
git -C "$source_dir" diff --quiet HEAD -- || fail "Hermes 源码含跟踪文件改动，请使用干净安装。"

config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/hermes-workflow-desktop"
data_dir="${XDG_DATA_HOME:-$HOME/.local/share}/hermes-workflow-desktop"
binding="$config_dir/workflow-app.env"
plugin_config="$HERMES_HOME/plugins/workflow/config.json"
if [[ -f "$plugin_config" ]]; then
  /usr/bin/python3 - "$plugin_config" "$binding" <<'PY'
import json, sys
from pathlib import Path
settings = json.loads(Path(sys.argv[1]).read_text())
if settings.get("env_file") != str(Path(sys.argv[2]).resolve()):
    raise SystemExit("检测到已有工作流绑定。请按 docs/DESKTOP_APP.md 单独安装桌面入口。")
PY
fi
mkdir -p -- "$config_dir" "$data_dir"
if [[ ! -f "$binding" ]]; then
  mkdir -p -- "$data_dir/示例项目"
  printf 'PROJECT_DIR=%s\nBOARD_SLUG=default\n' "$data_dir/示例项目" > "$binding"
fi
export HERMES_WEB_DIST="$data_dir/web_dist"
if [[ -e "$HERMES_WEB_DIST" ]]; then
  diff -qr -- "$package/web_dist" "$HERMES_WEB_DIST" ||
    fail "已安装的前端与此包不同，请先备份旧前端再安装。"
else
  cp -R -- "$package/web_dist" "$HERMES_WEB_DIST"
fi
/usr/bin/python3 scripts/install-workflow-app.py --home "$HERMES_HOME" --env "$binding"
hermes --profile default plugins enable workflow --no-allow-tool-override
/usr/bin/python3 scripts/install-workflow-desktop.py
gtk-launch local.hermes.Workflow
