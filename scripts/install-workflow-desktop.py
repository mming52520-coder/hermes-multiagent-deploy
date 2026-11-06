#!/usr/bin/env python3
"""Install a per-user Linux desktop window for an existing workflow installation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from workflow_desktop import APP_ID, Settings, xdg_path


def exec_argument(value: str) -> str:
    # Desktop Entry string escaping precedes Exec argument parsing; this is
    # deliberately not shell quoting (Exec never invokes a shell).
    value = value.replace("\\", "\\\\\\\\").replace('"', '\\\\"')
    value = value.replace("`", "\\\\`").replace("$", "\\\\$").replace("%", "%%")
    return '"' + value + '"'


def install(settings: Settings, desktop: Path | None) -> Path:
    settings.validate()
    destination = xdg_path("XDG_DATA_HOME", ".local/share")
    configuration = xdg_path("XDG_CONFIG_HOME", ".config")
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    configuration.mkdir(parents=True, exist_ok=True, mode=0o700)
    for name in ("workflow_desktop.py", "workflow-desktop.svg"):
        shutil.copyfile(Path(__file__).with_name(name), destination / name)
    config = configuration / "config.json"
    config.write_text(json.dumps({name: str(value) for name, value in vars(settings).items()},
                                 ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    config.chmod(0o600)
    applications = destination.parent / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    entry = applications / f"{APP_ID}.desktop"
    entry.write_text(
        "[Desktop Entry]\nType=Application\nName=多 Agent 工作流\n"
        "Comment=自动启动服务并打开多 Agent 工作流\n"
        f"Exec=/usr/bin/python3 {exec_argument(str(destination / 'workflow_desktop.py'))}\n"
        f"Icon={destination / 'workflow-desktop.svg'}\n"
        "Terminal=false\nStartupNotify=true\nCategories=Development;\n"
        f"StartupWMClass={APP_ID}\n", encoding="utf-8")
    entry.chmod(0o755)
    if desktop is not None:
        desktop.mkdir(parents=True, exist_ok=True)
        shortcut = desktop / "多 Agent 工作流.desktop"
        shutil.copyfile(entry, shortcut)
        shortcut.chmod(0o755)
        if shutil.which("gio"):
            trusted = subprocess.run(["gio", "set", str(shortcut), "metadata::trusted", "true"],
                                     capture_output=True, text=True)
            if trusted.returncode:
                print("桌面环境未设置启动信任；可在图标上右键选择“允许启动”，或从应用菜单打开。")
    if shutil.which("update-desktop-database"):
        subprocess.run(["update-desktop-database", str(applications)], check=False)
    return entry


def main() -> int:
    if sys.platform != "linux":
        raise ValueError("此桌面入口适用于 Linux。")
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    binary = shutil.which("hermes")
    if binary is None:
        raise ValueError("PATH 中找不到已有 Hermes 启动程序。")
    web_dist = os.environ.get("HERMES_WEB_DIST")
    if not web_dist:
        raise ValueError("请用 HERMES_WEB_DIST 指向当前已构建的工作流前端目录。")
    settings = Settings(Path(os.environ.get("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve(),
                        Path(binary).absolute(), Path(web_dist).expanduser().resolve())
    desktop = None
    if shutil.which("xdg-user-dir"):
        found = subprocess.run(["xdg-user-dir", "DESKTOP"], check=True, capture_output=True, text=True).stdout.strip()
        # XDG uses HOME to indicate that the desktop directory is disabled.
        if found and Path(found) != Path.home():
            desktop = Path(found)
    entry = install(settings, desktop)
    print(f"应用已安装：{entry}")
    if desktop:
        print(f"桌面图标：{desktop / '多 Agent 工作流.desktop'}")
    print("点击即可检查、启动服务并打开工作流。关闭窗口不会停止后台任务。")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, ImportError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"安装未完成：{exc}")
