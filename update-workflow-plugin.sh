#!/usr/bin/env bash
set -Eeuo pipefail
workflow_source="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
python3 - "$workflow_source" <<'PY'
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time

source = Path(sys.argv[1])
home = Path(os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes")).expanduser().resolve()
target = home / "plugins/workflow"
config = target / "config.json"
if not config.is_file():
    raise SystemExit("尚未安装工作流插件，请先按 docs/LOCAL_HERMES_V0225.md 指定项目绑定配置安装。")
settings = json.loads(config.read_text())
binding = Path(settings["env_file"])
if not binding.is_file():
    raise SystemExit("找不到现有项目绑定配置；未修改安装。")
backup = home / "backups" / ("workflow-" + str(time.time_ns()))
backup.mkdir(parents=True, mode=0o700)
shutil.copytree(target, backup / "plugin", symlinks=True)
shutil.copyfile(binding, backup / "workflow-app.env")
(backup / "workflow-app.env").chmod(0o600)
spec = importlib.util.spec_from_file_location("workflow_installer", source / "scripts/install-workflow-app.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
archive = Path(settings["baseline_archive"]) if settings.get("baseline_archive") else None
installer.install(home, binding, archive=archive)
print("工作流插件已更新，项目绑定与操作开关已保留。")
print("私有备份：" + str(backup))
print("请重启此数据根的 Dashboard 和 Gateway，使其加载新模块。")
PY
