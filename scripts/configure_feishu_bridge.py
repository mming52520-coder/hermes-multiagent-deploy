"""Interactive, local configuration for an already installed workflow."""

import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
import warnings
import uuid

ASSIGN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z_0-9]*)\s*=(.*)$")


def values(text):
    result = {}
    for line in text.splitlines():
        match = ASSIGN.match(line)
        if match:
            raw = match[2].strip()
            if len(raw) >= 2 and raw[0] == raw[-1] == '"':
                raw = re.sub(r'\\(["\\])', r"\1", raw[1:-1])
            elif len(raw) >= 2 and raw[0] == raw[-1] == "'":
                raw = raw[1:-1]
            result[match[1]] = raw
    return result


def updated(text, changes):
    lines = []
    for line in text.splitlines(keepends=True):
        match = ASSIGN.match(line)
        if not match or match[1] not in changes:
            lines.append(line)
    kept = "".join(lines)
    if kept and not kept.endswith("\n"):
        kept += "\n"
    for key, value in changes.items():
        if "\n" in value or "\r" in value or "\0" in value:
            raise ValueError("配置值必须是单行。")
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        kept += f'{key}="{escaped}"\n'
    return kept


def private_write(path, content):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".workflow-feishu-")
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def open_ids(text, required):
    result = list(dict.fromkeys(part.strip() for part in text.split(",") if part.strip()))
    if (required and not result) or any(not re.fullmatch(r"ou_[a-zA-Z0-9_-]+", item) for item in result):
        raise ValueError("请使用逗号分隔的审批人或成员 open_id（ou_ 开头）。")
    return result


def configure(root, ask=input, secret_input=getpass.getpass):
    config = root / "plugins/workflow/config.json"
    if not config.is_file():
        raise ValueError("请先安装工作流插件。")
    settings = json.loads(config.read_text())
    if Path(settings["hermes_home"]).resolve() != root.resolve():
        raise ValueError("当前数据根与插件绑定不一致。")
    binding = Path(settings["env_file"])
    native = root / ".env"
    if (
        not binding.is_file()
        or binding.is_symlink()
        or native.is_symlink()
        or binding.resolve() == native.resolve()
    ):
        raise ValueError("需要独立的绑定 env 和原生 .env 文件，不能通过符号链接更新配置。")
    native_before = native.read_bytes() if native.exists() else None
    binding_before = binding.read_bytes()
    native_text = (native_before or b"").decode()
    binding_text = binding_before.decode()
    original, bound = values(native_text), values(binding_text)
    app = ask("飞书 App ID（回车沿用已有值）：").strip() or original.get("FEISHU_APP_ID", "")
    if not re.fullmatch(r"cli_[a-zA-Z0-9_-]+", app):
        raise ValueError("请填写有效的 App ID。")
    secret = secret_input("飞书 App Secret（隐藏输入，同一应用可回车沿用）：")
    if not secret and (app != original.get("FEISHU_APP_ID") or not original.get("FEISHU_APP_SECRET")):
        raise ValueError("新应用需要填写 App Secret。")
    chat = ask("绑定群 ID（oc_ 开头，回车沿用）：").strip() or bound.get("WORKFLOW_FEISHU_CHAT_ID", "")
    if not re.fullmatch(r"oc_[a-zA-Z0-9_-]+", chat):
        raise ValueError("请填写有效的群 ID。")
    approvers = open_ids(
        ask("审批人 open_id（逗号分隔，回车沿用）：").strip() or bound.get("WORKFLOW_FEISHU_APPROVERS", ""), True
    )
    members = open_ids(ask("可对话成员 open_id（逗号分隔，留空仅审批人）："), False)
    url = (
        ask("工作台地址（回车沿用，首次默认 http://127.0.0.1:9119）：").strip()
        or bound.get("WORKFLOW_DASHBOARD_URL")
        or "http://127.0.0.1:9119"
    ).rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme not in {"http", "https"}
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise ValueError("请填写可访问的工作台 HTTP(S) 基址。")
    allowed = [part.strip() for part in original.get("FEISHU_ALLOWED_USERS", "").split(",") if part.strip()]
    native_changes = {
        "FEISHU_APP_ID": app,
        "FEISHU_CONNECTION_MODE": "websocket",
        "FEISHU_ALLOWED_USERS": ",".join(dict.fromkeys(allowed + approvers + members)),
    }
    if secret:
        native_changes["FEISHU_APP_SECRET"] = secret
    binding_changes = {
        "WORKFLOW_FEISHU_CHAT_ID": chat,
        "WORKFLOW_FEISHU_APPROVERS": ",".join(approvers),
        "WORKFLOW_FEISHU_MEMBERS": ",".join(members),
        "WORKFLOW_DASHBOARD_URL": url,
    }
    new_native = updated(native_text, native_changes).encode()
    new_binding = updated(binding_text, binding_changes).encode()

    backups = root / "backups"
    backups.mkdir(mode=0o700, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix="feishu-bridge-", dir=backups))
    if native_before is not None:
        private_write(backup / "hermes.env", native_before)
    private_write(backup / "workflow-app.env", binding_before)
    private_write(native, new_native)
    try:
        private_write(binding, new_binding)
    except OSError:
        if native_before is None:
            native.unlink()
        else:
            private_write(native, native_before)
        raise
    return backup


def send_probe(root, *, opener=None):
    from workflow_feishu import probe_card
    from workflow_feishu_client import FeishuClient

    config = json.loads((root / "plugins/workflow/config.json").read_text())
    chat = values(Path(config["env_file"]).read_text())["WORKFLOW_FEISHU_CHAT_ID"]
    native = values((root / ".env").read_text())
    secret = native.get("FEISHU_APP_SECRET", "")
    if not secret or secret.startswith("op://"):
        return False
    client = FeishuClient(
        native["FEISHU_APP_ID"], secret, native.get("FEISHU_DOMAIN", "feishu").lower(), opener=opener
    )
    probe = uuid.uuid4().hex
    message = client.send_card(chat, probe_card(probe), delivery_id=probe)
    if not message:
        return False
    directory = root / "workflow"
    directory.mkdir(mode=0o700, exist_ok=True)
    receipt = {
        "probe_id": probe,
        "message_id": message,
        "chat_id": chat,
        "app_id": client.app_id,
        "host": client.host,
    }
    private_write(directory / "feishu-probe.json", json.dumps(receipt).encode())
    return True


if __name__ == "__main__":
    if not sys.stdin.isatty():
        sys.exit("请在本机交互终端运行，以便隐藏输入 App Secret。")
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            root = Path(os.getenv("HERMES_HOME") or Path.home() / ".hermes").expanduser().resolve()
            backup = configure(root)
        except (ValueError, OSError, EOFError, getpass.GetPassWarning) as exc:
            sys.exit(
                str(exc)
                if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError)
                else "配置未完成，请检查本机终端、数据根和文件权限。"
            )
    print("飞书配置已保存。私有备份目录：" + str(backup))
    print("执行 hermes gateway restart，再重启此数据根的 Dashboard。")
    try:
        if input("现在向绑定群发送一张无任务操作的测试卡？[y/N] ").strip().lower() in {"y", "yes"}:
            print(
                "测试卡已发出，请在重启后点击测试按钮。"
                if send_probe(root)
                else "配置已保存，测试卡发送失败。请检查应用权限、入群与本机凭据。"
            )
    except (EOFError, KeyboardInterrupt):
        pass
    except (OSError, ValueError, KeyError):
        print("配置已保存，测试卡未能完成投递，请检查绑定和数据目录。")
