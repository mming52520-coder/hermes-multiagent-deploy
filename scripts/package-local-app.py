#!/usr/bin/env python3
"""制作中文本地接入包；只读取指定前端与仓库白名单文件。"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

REPOSITORY = Path(__file__).resolve().parents[1]
SOURCES = (
    "plugins/workflow/plugin.yaml", "plugins/workflow/__init__.py",
    "plugins/workflow/dashboard/manifest.json", "plugins/workflow/dashboard/plugin_api.py",
    "plugins/workflow/dashboard/app.js", "plugins/workflow/dashboard/app.css",
    "scripts/install-workflow-app.py", "scripts/workflow_control.py",
    "scripts/configure_profiles.py", "scripts/hermes_baseline.py",
    "scripts/dashboard-zh.js", "scripts/package-local-app.py",
    "localization/dashboard-zh.patch", "localization/README.md",
    "tests/check_workflow_readonly.py", "tests/browser_workflow_readonly.cjs",
    "docs/WORKFLOW_APP_BUTTONS_ZH.md",
)


def package(source: Path, output: Path) -> None:
    frontend = source / "hermes_cli/web_dist"
    if not (frontend / "index.html").is_file():
        raise ValueError("缺少已构建的官方网页前端")
    files = {name: (REPOSITORY / name).read_bytes() for name in SOURCES}
    guide = (REPOSITORY / "docs/LOCAL_HERMES_V0225.md").read_bytes().replace(b"(WORKFLOW_APP_BUTTONS_ZH.md)", b"(docs/WORKFLOW_APP_BUTTONS_ZH.md)")
    files.update({"README.md": guide,
                  "LICENSE": (REPOSITORY / "LICENSE").read_bytes(),
                  "UPSTREAM_LICENSE": (source / "LICENSE").read_bytes()})
    for file in sorted(frontend.rglob("*")):
        if file.is_symlink():
            raise ValueError("前端目录不能包含符号链接")
        if file.is_file():
            files["web_dist/" + file.relative_to(frontend).as_posix()] = file.read_bytes()
    index = files["web_dist/index.html"].decode("utf-8")
    if '<script type="module"' not in index:
        raise ValueError("无法定位前端入口；未生成包")
    index = index.replace('<html lang="en">', '<html lang="zh-CN">', 1)
    index = index.replace("<title>Hermes Agent - Dashboard</title>", "<title>Hermes 智能体 · 中文工作台</title>", 1)
    index = index.replace('<script type="module"', '<script src="/assets/workflow-zh.js"></script>\n    <script type="module"', 1)
    files["web_dist/index.html"] = index.encode("utf-8")
    files["web_dist/assets/workflow-zh.js"] = files["scripts/dashboard-zh.js"]
    files["BUILD_INFO.json"] = (json.dumps({
        "mode": "默认只读", "language": "简体中文，复用 Hermes 原生翻译",
        "hermes_source_commit": "bf0203a794a07aac3ff764972ab9087baa4e4f4e",
        "upstream_frontend_changes": "补全简体中文导航、页头提示和移动端提示布局；中文标题与首次访问语言初始化；翻译补丁随包提供",
        "workflow_writes_v0225": "未适配，保持关闭", "includes_credentials_or_user_state": False,
    }, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    files["MANIFEST.sha256"] = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                                           for name, data in sorted(files.items())).encode("utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
        with tarfile.open(fileobj=compressed, mode="w") as archive:
            for name, data in sorted(files.items()):
                entry = tarfile.TarInfo("hermes-workflow-local-readonly/" + name)
                entry.size, entry.mode, entry.mtime = len(data), 0o644, 0
                archive.addfile(entry, io.BytesIO(data))
    checksum = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_name(output.name + ".sha256").write_text(checksum + "  " + output.name + "\n")
    print(f"中文接入包已生成：{output}（{len(files)} 个文件）")
    print(f"SHA-256：{checksum}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-source", type=Path, required=True, help="已验证的 v0.22.5 官方源码及构建目录")
    parser.add_argument("--output", type=Path, required=True, help="新的 .tar.gz 文件路径，不覆盖已有文件")
    args = parser.parse_args()
    package(args.hermes_source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
