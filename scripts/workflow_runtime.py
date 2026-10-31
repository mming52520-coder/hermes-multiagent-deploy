"""Native runtime seams and read-only execution prerequisites for the audited releases."""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import subprocess

if __package__:
    from .configure_profiles import BUILTIN_PROVIDERS, CUSTOM_PROVIDERS, is_placeholder, load_env_file, read_yaml
else:
    from configure_profiles import BUILTIN_PROVIDERS, CUSTOM_PROVIDERS, is_placeholder, load_env_file, read_yaml


def connect_closing(*, board: str):
    from hermes_cli import kanban_db
    if hasattr(kanban_db, "connect_closing"):
        return kanban_db.connect_closing(board=board)
    from hermes_cli.kanban_db_connect import connect_closing as native_connect
    return native_connect(board=board)


@contextmanager
def home_scope(home: Path):
    import hermes_constants
    if hasattr(hermes_constants, "set_hermes_home_override"):
        token = hermes_constants.set_hermes_home_override(home)
        try:
            yield
        finally:
            hermes_constants.reset_hermes_home_override(token)
    else:
        yield


def readiness(workflow, manifest: dict | None = None) -> dict:
    from hermes_cli.profiles import get_profile_dir
    checks = []
    checks.append({"code": "configuration", "label": "任务输出和容器镜像",
                   "ready": bool(workflow.env.get("OUTPUT_DIR") and workflow.env.get("DOCKER_IMAGE")),
                   "detail": "在项目绑定配置中设置 OUTPUT_DIR 和 DOCKER_IMAGE。"})
    docker = shutil.which("docker")
    docker_ready = False
    docker_detail = "请安装并启动 Docker。"
    if docker:
        try:
            result = subprocess.run([docker, "info", "--format", "{{.ServerVersion}}"],
                                    capture_output=True, text=True, timeout=10)
            docker_ready = result.returncode == 0
            docker_detail = "Docker 已就绪。" if docker_ready else "Docker 服务不可用，请检查服务和当前用户权限。"
        except (OSError, subprocess.TimeoutExpired):
            docker_detail = "Docker 检查失败或超时。"
    checks.append({"code": "docker", "label": "Docker 执行环境", "ready": docker_ready, "detail": docker_detail})
    checks.append({"code": "verification", "label": "验收命令", "ready": bool(workflow.env.get("WORKFLOW_TEST_COMMAND", "").strip()),
                   "detail": "由操作员在项目绑定配置中设置，不接收网页任意命令。"})
    cost_cap = manifest["budget"]["max_cost_usd"] if manifest else workflow.env.get("WORKFLOW_MAX_COST_USD")
    checks.append({"code": "budget", "label": "执行预算策略", "ready": not cost_cap,
                   "detail": "实际费用硬限额尚未实现；配置有限费用上限时将拒绝执行。"})
    profiles = {}
    if manifest:
        database = workflow.kb.kanban_db_path(board=workflow.board)
        if database.is_file():
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                profiles = {role: task.assignee for role, tid in manifest["rounds"][-1]["tasks"].items()
                            if (task := workflow.kb.get_task(conn, tid)) is not None}
    for role in ("researcher", "builder", "reviewer", "orchestrator"):
        profile = profiles.get(role, role)
        directory = get_profile_dir(profile)
        config = read_yaml(directory / "config.yaml")
        model = config.get("model") or {}
        provider = model.get("provider", "auto") if isinstance(model, dict) else "auto"
        name = model.get("default", "") if isinstance(model, dict) else str(model)
        values = load_env_file(directory / ".env") if (directory / ".env").is_file() else dict(os.environ)
        key = model.get("key_env") if isinstance(model, dict) else None
        key = key or CUSTOM_PROVIDERS.get(provider, {}).get("key_env") or BUILTIN_PROVIDERS.get(provider)
        configured = bool(name and not is_placeholder(name))
        authenticated = not key or not is_placeholder(values.get(key, ""))
        checks.append({"code": role, "label": role, "profile": profile, "model": name, "provider": provider,
                       "ready": configured and authenticated,
                       "detail": "模型配置已就绪。" if configured and authenticated else "请在此角色配置中设置模型及其凭据。"})
    try:
        from hermes_cli.gateway_runtime import ensure_gateway_runtime  # noqa: F401
        supported = read_yaml(workflow.root / "config.yaml").get("kanban", {}).get("dispatch_in_gateway") is not False
    except ModuleNotFoundError as exc:
        if exc.name != "hermes_cli.gateway_runtime":
            raise
        supported = False
    checks.append({"code": "runtime", "label": "原生执行引擎", "ready": supported,
                   "detail": "启动时按需连接原生 Gateway。" if supported else "需要 Hermes v0.22.5，并启用 kanban.dispatch_in_gateway。"})
    ready = all(item["ready"] for item in checks)
    return {"ready": ready, "checks": checks, "approved": bool(manifest and manifest["approved_write"])}


def dispatch(workflow) -> dict:
    """Start/attach the native owner, then use its existing atomic dispatcher."""
    from hermes_cli.gateway_runtime import attachable, ensure_gateway_runtime
    from hermes_cli import kanban_db_dispatch as native
    from hermes_cli.config import load_config
    with home_scope(workflow.root):
        owner = ensure_gateway_runtime(workflow.root, idle_exit=True)
        if not attachable(owner):
            raise ValueError(f"原生执行引擎未就绪：{owner.reason_code or owner.state}")
        config = load_config().get("kanban", {})
        with connect_closing(board=workflow.board) as conn:
            result = native.dispatch_once(
                conn, board=workflow.board,
                max_in_progress=native.resolve_max_in_progress(native.configured_max_in_progress()),
                max_in_progress_per_profile=native._positive_int(config.get("max_in_progress_per_profile"), None),
                max_spawn=native._positive_int(config.get("max_spawn"), None),
                failure_limit=native._positive_int(config.get("failure_limit"), native.DEFAULT_FAILURE_LIMIT),
            )
        return {"spawned": [{"task_id": tid, "profile": who} for tid, who, _ in result.spawned],
                "skipped_locked": result.skipped_locked}
