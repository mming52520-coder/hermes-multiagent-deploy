"""Dashboard adapter; all mutations delegate to the existing P0 operator code."""
from __future__ import annotations

import hashlib
from contextlib import closing
import importlib
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import types
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
ROLES = ("researcher", "builder", "reviewer", "orchestrator")


def require_session(request: Request) -> None:
    # No standalone/auth-free fallback. Use the host's cookie/token gate.
    from hermes_cli.web_server import _require_token
    _require_token(request)


async def workflow_home_scope():
    # The host's profile picker must not retarget the server-bound workflow board.
    settings = read_settings()
    with core_module().workflow_runtime.home_scope(Path(settings["hermes_home"])):
        yield


router = APIRouter(dependencies=[Depends(require_session), Depends(workflow_home_scope)])


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1, max_length=4000)
    instance: str = Field(default="", max_length=128)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool = False
    round_number: int | None = Field(default=None, ge=0)
    kind: Literal["implementation", "test", "environment", "api_model", "permission", "requirements"] = "implementation"
    reason: str = Field(default="", max_length=2000)


class ModelParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: str
    model: str = ""
    api_key: SecretStr = SecretStr("")
    base_url: str = ""
    protocol: Literal["chat_completions", "codex_responses", "anthropic_messages"] = "chat_completions"


class ModelConnection(ModelParameters):
    role: Literal["all", "researcher", "builder", "reviewer", "orchestrator"] = "all"
    execution: str = ""


class ModelBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    connections: dict[Literal["researcher", "builder", "reviewer", "orchestrator"], ModelParameters] = Field(min_length=1)
    execution: str = ""


def read_settings() -> dict:
    file = PLUGIN_ROOT / "config.json"
    if not file.is_file():
        raise HTTPException(503, "尚未安装工作流应用，请先完成插件安装。")
    return json.loads(file.read_text(encoding="utf-8"))


def core_module():
    # A private package avoids adding generic script names to global sys.path.
    operator = PLUGIN_ROOT / "operator"
    name = "_hermes_workflow_operator_" + hashlib.sha256(str(operator).encode()).hexdigest()[:12]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(operator)]
        sys.modules[name] = package
    return importlib.import_module(name + ".workflow_control")


def bound_workflow(settings: dict):
    core = core_module()
    return core.Workflow(Path(settings["hermes_home"]), bound_environment(settings))


def models_module():
    if importlib.util.find_spec("hermes_cli.provider_catalog") is None:
        raise HTTPException(503, "模型连接设置需要 Hermes v0.22.5。")
    return importlib.import_module(core_module().__package__ + ".workflow_models")


@router.get("/model-connection")
def model_connections(execution: str = ""):
    settings = read_settings()
    models = models_module()
    profiles = dict(zip(ROLES, ROLES))
    if execution:
        from hermes_cli import kanban_db as kb
        manifest = load_manifest(settings, execution)
        database = kb.kanban_db_path(board=manifest["board"])
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            profiles = {role: kb.get_task(conn, tid).assignee for role, tid in manifest["rounds"][-1]["tasks"].items()}
    home = Path(settings["hermes_home"])
    return {"providers": models.catalog(), "roles": {
        role: models.profile_settings(home, profile) for role, profile in profiles.items()}}


@router.put("/model-connection")
def save_model_connection(request: Request, body: ModelConnection):
    settings = read_settings()
    try:
        require_action(request, settings)
        workflow = bound_workflow(settings)
        roles = list(ROLES) if body.role == "all" else [body.role]
        models_module().ensure_profiles(workflow, roles)
        profiles = list(roles)
        if body.execution:
            from hermes_cli import kanban_db as kb
            load_manifest(settings, body.execution)
            with workflow.locked(body.execution), core_module().workflow_runtime.connect_closing(board=workflow.board) as conn:
                manifest = workflow.load(body.execution)
                tasks = {role: kb.get_task(conn, tid) for role, tid in manifest["rounds"][-1]["tasks"].items()}
                if any(task.status != "triage" for task in tasks.values()):
                    raise HTTPException(409, "当前目标已启动；请为后续目标配置模型。")
                profiles.extend(tasks[role].assignee for role in roles)
                result = models_module().save(workflow.root, profiles, provider=body.provider,
                    model=body.model, api_key=body.api_key.get_secret_value(), base_url=body.base_url, protocol=body.protocol)
                manifest["approved_write"] = False
                manifest.pop("approval", None)
                workflow.save(manifest)
        else:
            result = models_module().save(workflow.root, profiles, provider=body.provider,
                model=body.model, api_key=body.api_key.get_secret_value(), base_url=body.base_url, protocol=body.protocol)
        return {"saved": True, "roles": roles, "connections": result, "requires_approval": bool(body.execution)}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/model-connections/models")
def discover_role_models(request: Request, body: ModelBatch):
    settings = read_settings()
    try:
        require_action(request, settings)
        workflow = bound_workflow(settings)
        models = models_module()
        models.ensure_profiles(workflow, list(body.connections))
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, str(exc)) from exc
    results = {}
    for role, values in body.connections.items():
        try:
            results[role] = models.discover(role, provider=values.provider,
                api_key=values.api_key.get_secret_value(), base_url=values.base_url, protocol=values.protocol)
        except (ValueError, OSError) as exc:
            results[role] = {"error": str(exc)}
    return {"roles": results}


@router.put("/model-connections")
def save_role_models(request: Request, body: ModelBatch):
    settings = read_settings()
    try:
        require_action(request, settings)
        workflow = bound_workflow(settings)
        models = models_module()
        models.ensure_profiles(workflow, list(body.connections))
        values = {role: {**entry.model_dump(exclude={"api_key"}), "api_key": entry.api_key.get_secret_value()}
                  for role, entry in body.connections.items()}
        targets = {role: [role] for role in values}
        if body.execution:
            from hermes_cli import kanban_db as kb
            load_manifest(settings, body.execution)
            with workflow.locked(body.execution), core_module().workflow_runtime.connect_closing(board=workflow.board) as conn:
                manifest = workflow.load(body.execution)
                tasks = {role: kb.get_task(conn, tid) for role, tid in manifest["rounds"][-1]["tasks"].items()}
                if any(task.status != "triage" for task in tasks.values()):
                    raise HTTPException(409, "当前目标已启动；请为后续目标配置模型。")
                for role in targets:
                    targets[role].append(tasks[role].assignee)
                result = models.save_batch(workflow.root, targets, values)
                manifest["approved_write"] = False
                manifest.pop("approval", None)
                workflow.save(manifest)
        else:
            result = models.save_batch(workflow.root, targets, values)
        return {"saved": True, "roles": list(values), "connections": result, "requires_approval": bool(body.execution)}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, str(exc)) from exc


def bound_environment(settings: dict) -> dict:
    try:
        env = core_module().load_env_file(Path(settings["env_file"]))
    except OSError as exc:
        raise HTTPException(503, "部署配置文件不可用，请由操作员检查安装配置。") from exc
    if not env.get("PROJECT_DIR") or not env.get("BOARD_SLUG"):
        raise HTTPException(503, "部署配置缺少 PROJECT_DIR 或 BOARD_SLUG。")
    return env


def matches_project(env: dict, manifest: dict) -> bool:
    return Path(manifest["project"]).resolve() == Path(env["PROJECT_DIR"]).resolve() and manifest["board"] == env["BOARD_SLUG"]


def execution_directory(settings: dict, execution: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{32}", execution):
        raise HTTPException(400, "执行 ID 格式不正确。")
    store = Path(settings["hermes_home"]) / "workflow" / "executions"
    directory = store / execution
    if not directory.resolve().is_relative_to(store.resolve()):
        raise HTTPException(403, "执行目录不在允许范围内。")
    if not (directory / "execution.json").is_file():
        raise HTTPException(404, "找不到这次执行。")
    return directory


def load_manifest(settings: dict, execution: str) -> dict:
    manifest = json.loads((execution_directory(settings, execution) / "execution.json").read_text(encoding="utf-8"))
    if not matches_project(bound_environment(settings), manifest):
        raise HTTPException(404, "这次执行不属于当前配置的项目与看板。")
    return manifest


def task_summary(conn, task_id: str) -> dict:
    from hermes_cli import kanban_db as kb
    task = kb.get_task(conn, task_id)
    if task is None:
        return {"id": task_id, "status": "missing", "outcome": None}
    run = kb.latest_run(conn, task_id)
    return {"id": task.id, "status": task.status, "assignee": task.assignee,
            "started_at": task.started_at, "completed_at": task.completed_at,
            "max_runtime_seconds": task.max_runtime_seconds,
            "outcome": run.outcome if run else None}


def summary(settings: dict, manifest: dict) -> dict:
    from hermes_cli import kanban_db as kb
    database = kb.kanban_db_path(board=manifest["board"])
    rounds = []
    # Browse the existing native DB without creating/migrating a board on GET.
    if database.is_file():
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            for row in manifest["rounds"]:
                rounds.append({"number": row["number"], "tasks": {
                    role: task_summary(conn, tid) for role, tid in row["tasks"].items()}})
    return {"execution_id": manifest["execution_id"], "objective": manifest["objective"],
            "instance": manifest.get("instance", ""), "created_at": manifest["created_at"],
            "source_revision": manifest["source_revision"], "board": manifest["board"],
            "approved_write": manifest["approved_write"], "rounds": rounds,
            "has_acceptance_record": (execution_directory(settings, manifest["execution_id"]) / "acceptance.json").is_file()}


@router.get("/meta")
def metadata():
    settings = read_settings()
    env = bound_environment(settings)
    enabled = settings.get("allow_actions") is True
    return {"name": "Hermes Workflow", "version": "0.4.0", "phase": "P0_PARTIAL_PASS",
            "project_name": Path(env["PROJECT_DIR"]).name, "board": env["BOARD_SLUG"],
            "actions_enabled": enabled,
            "model_connections_supported": importlib.util.find_spec("hermes_cli.provider_catalog") is not None,
            "readiness": bound_workflow(settings).readiness() if enabled else None,
            "limitations": ["模型调用次数与实际费用硬限额尚未完成。", "真实 Worker 隔离与服务级恢复仍待验证。"],
            "unknown_cost": True}


@router.get("/executions")
def executions():
    settings = read_settings()
    env = bound_environment(settings)
    store = Path(settings["hermes_home"]) / "workflow" / "executions"
    records = []
    for file in store.glob("*/execution.json"):
        directory = execution_directory(settings, file.parent.name)
        manifest = json.loads((directory / "execution.json").read_text(encoding="utf-8"))
        if matches_project(env, manifest):
            records.append(summary(settings, manifest))
    return {"executions": sorted(records, key=lambda row: row["created_at"], reverse=True)}


@router.get("/executions/{execution}")
def execution_details(execution: str):
    settings = read_settings()
    manifest = load_manifest(settings, execution)
    data = summary(settings, manifest)
    if not data["rounds"] or any(task["status"] == "missing" for row in data["rounds"] for task in row["tasks"].values()):
        raise HTTPException(409, "原生任务数据库或任务记录缺失，无法核验本次执行。")
    workflow = bound_workflow(settings)
    try:
        state = workflow.status(execution)
    except (ValueError, OSError, sqlite3.Error) as exc:
        raise HTTPException(409, "无法核验执行记录，请检查项目、任务数据库与证据文件。") from exc
    row = manifest["rounds"][-1]
    data.update(acceptance=state["acceptance"], budget=state["budget"], failures=state["failures"],
                approval=manifest.get("approval"),
                readiness=workflow.readiness(execution) if settings.get("allow_actions") is True else None,
                candidate_revision=row.get("candidate_revision"), candidate_digest=row.get("candidate_digest"),
                changed_files=sorted(row.get("candidate_files", {}).keys() - manifest["source_files"].keys())
                + sorted(key for key in manifest["source_files"] if row.get("candidate_files", {}).get(key) != manifest["source_files"][key])
                if "candidate_files" in row else [], actual_api_cost_usd=None)
    return data


@router.get("/executions/{execution}/evidence/{round_number}/{role}")
def evidence(execution: str, round_number: int, role: Literal["builder", "reviewer"]):
    settings = read_settings()
    manifest = load_manifest(settings, execution)
    if round_number not in [row["number"] for row in manifest["rounds"]]:
        raise HTTPException(404, "找不到这轮执行。")
    directory = execution_directory(settings, execution) / f"round-{round_number}"
    receipt_file = directory / f"{role}-verification.json"
    log = directory / f"{role}-verification.log"
    if not receipt_file.is_file():
        return {"role": role, "available": False}
    if not log.is_file():
        raise HTTPException(409, "验证日志缺失，证据不完整。")
    if not receipt_file.resolve().is_relative_to(directory.resolve()) or not log.resolve().is_relative_to(directory.resolve()):
        raise HTTPException(403, "证据文件不在允许范围内。")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 16384))
        tail = stream.read().decode("utf-8", errors="replace")
    # Do not expose dotenvs or arbitrary task metadata as browser downloads.
    return {"available": True, "receipt": receipt, "log_tail": tail,
            "log_matches": hashlib.sha256(log.read_bytes()).hexdigest() == receipt["log_sha256"]}


def require_action(request: Request, settings: dict, confirmed: bool = True) -> None:
    if settings.get("allow_actions") is not True:
        raise HTTPException(403, "当前为只读模式，操作员尚未启用应用操作。")
    if request.headers.get("X-Hermes-Workflow-Action") != "1":
        raise HTTPException(403, "缺少明确的应用操作请求。")
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.url.netloc:
        raise HTTPException(403, "操作必须来自当前应用。")
    if not confirmed:
        raise HTTPException(400, "请先确认这次操作及其影响范围。")
    # Match the CLI's provenance gate; do not relax P0 just because it has a UI.
    from hermes_cli import kanban_db as kb
    core = core_module()
    archive = settings.get("baseline_archive")
    core.verify_source(Path(kb.__file__).resolve().parents[1], Path(archive) if archive else None)


@router.post("/executions")
def submit(request: Request, body: Submission):
    settings = read_settings()
    try:
        require_action(request, settings)
        if not body.objective.strip():
            raise HTTPException(422, "请填写研发目标。")
        result = bound_workflow(settings).submit(body.objective.strip(), body.instance)
        return {"execution_id": result["execution_id"]}
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/executions/{execution}/actions/{action}")
def run_action(request: Request, execution: str,
               action: Literal["approve", "launch", "start", "prepare-review", "verify-builder", "verify-reviewer", "accept", "repair"], body: Action):
    settings = read_settings()
    load_manifest(settings, execution)
    try:
        require_action(request, settings, body.confirmed)
        workflow = bound_workflow(settings)
        if action in {"approve", "launch"} and body.round_number is None:
            raise HTTPException(400, "请刷新并确认当前执行轮次。")
        if action == "approve":
            workflow.approve(execution, expected_round=body.round_number)
        elif action in {"launch", "start"}:
            # Preserve the legacy URL as an alias, including the separate approval/readiness gate.
            return {**workflow.launch(execution, expected_round=body.round_number), "action": action, "completed": True}
        elif action == "prepare-review":
            workflow.prepare_review(execution)
        elif action.startswith("verify-"):
            receipt = workflow.verify(execution, action.removeprefix("verify-"))
            if receipt["status"] != "PASS":
                raise HTTPException(409, "验证没有通过，请查看执行证据。")
        elif action == "repair":
            workflow.repair(execution, body.kind, body.reason)
        else:
            workflow.accept(execution)
        return {"execution_id": execution, "action": action, "completed": True}
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        raise HTTPException(409, str(exc)) from exc
