#!/usr/bin/env python3
"""安装中文工作流网页插件；不启动服务或更改模型配置。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
ASSETS = ("plugin.yaml", "__init__.py", "dashboard/manifest.json", "dashboard/plugin_api.py", "dashboard/app.js", "dashboard/app.css")
OPERATOR = ("workflow_control.py", "configure_profiles.py", "hermes_baseline.py")


def install(home: Path, env_file: Path, enable: bool = False, archive: Path | None = None) -> Path:
    home, env_file = home.expanduser().resolve(), env_file.expanduser().resolve()
    if not env_file.is_file():
        raise ValueError("找不到项目绑定配置文件，请检查 --env 指定的路径")
    target = home / "plugins" / "workflow"
    if target.is_symlink():
        raise ValueError("插件目录是符号链接，为保护已有文件而拒绝覆盖")
    files = {relative: REPOSITORY / "plugins" / "workflow" / relative for relative in ASSETS}
    files.update({f"operator/{name}": REPOSITORY / "scripts" / name for name in OPERATOR})
    marker = target / ".managed-files.json"
    previous = {}
    if target.exists():
        if not marker.is_file():
            raise ValueError("已有同名插件不属于本安装器，请先保留该插件")
        previous = json.loads(marker.read_text(encoding="utf-8"))
        for relative, expected in previous.items():
            installed = target / relative
            if installed.is_symlink() or not installed.resolve().is_relative_to(target.resolve()) or not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != expected:
                raise ValueError(f"检测到插件本地修改：{relative}；请先保留这些改动，再重新安装")
    for relative, source in files.items():
        if not source.is_file():
            raise ValueError(f"接入包缺少文件：{relative}")
        destination = target / relative
        if destination.exists() and relative not in previous:
            raise ValueError(f"已有不受本安装器管理的文件，拒绝覆盖：{relative}")
    target.mkdir(parents=True, exist_ok=True, mode=0o700)
    managed = {}
    for relative, source in files.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        managed[relative] = hashlib.sha256(destination.read_bytes()).hexdigest()
    marker.write_text(json.dumps(managed, indent=2) + "\n", encoding="utf-8")
    config = target / "config.json"
    if not config.exists():
        config.write_text(json.dumps({"hermes_home": str(home), "env_file": str(env_file),
                                     "baseline_archive": str(archive.resolve()) if archive else None,
                                     "allow_actions": False}, indent=2) + "\n", encoding="utf-8")
        config.chmod(0o600)
    if enable:
        # Use the existing native enable flow; preserve all unrelated settings.
        subprocess.run([sys.executable, "-m", "hermes_cli.main", "plugins", "enable", "workflow", "--no-allow-tool-override"],
                       env={**os.environ, "HERMES_HOME": str(home)}, stdin=subprocess.DEVNULL, check=True)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=Path(os.environ.get("HERMES_HOME") or str(Path.home()/".hermes")), help="已有 Hermes 数据根目录")
    parser.add_argument("--env", type=Path, required=True, help="项目与看板的绑定配置文件")
    parser.add_argument("--archive", type=Path, help="已验证的旧基线源归档，仅供受支持的写入流程校验")
    parser.add_argument("--enable", action="store_true", help="用当前 Hermes 的 Python 调用原生插件启用流程")
    args = parser.parse_args()
    try:
        target = install(args.home, args.env, args.enable, args.archive)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"安装未完成：{exc}\n")
    print(f"工作流网页插件已安装：{target}")
    print("模式：默认只读；已有操作配置会保留。未启动网关、执行进程、模型调用或其他服务。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
