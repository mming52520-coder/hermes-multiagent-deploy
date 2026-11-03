"""Advance approved workflows from the native owner's dispatch lifecycle."""
from __future__ import annotations

import hashlib
import importlib
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
import types

_active = threading.Lock()
_log = logging.getLogger(__name__)


def _advance_pending(board=None):
    root = Path(__file__).resolve().parent
    settings_file = root / "config.json"
    if not settings_file.is_file():
        return
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    if not settings.get("allow_actions"):
        return
    operator = root / "operator"
    name = "_hermes_workflow_operator_" + hashlib.sha256(str(operator).encode()).hexdigest()[:12]
    if name not in sys.modules:
        package = types.ModuleType(name)
        package.__path__ = [str(operator)]
        sys.modules[name] = package
    core = importlib.import_module(name + ".workflow_control")
    env = core.load_env_file(Path(settings["env_file"]))
    workflow = core.Workflow(Path(settings["hermes_home"]), env)
    if board is not None and board != workflow.board:
        return
    with core.workflow_runtime.home_scope(workflow.root):
        for file in sorted((workflow.root / "workflow" / "executions").glob("*/execution.json")):
            manifest = json.loads(file.read_text(encoding="utf-8"))
            if manifest.get("workflow_version", 1) < 2 or not manifest.get("approved_write"):
                continue
            if manifest.get("workflow_state") in {"READY_FOR_ACCEPTANCE", "ACCEPTED", "REPAIR_REQUIRED", "HUMAN_REQUIRED", "REJECTED"}:
                continue
            if (file.parent / "acceptance.json").exists():
                continue
            try:
                workflow.advance(manifest["execution_id"])
            except (ValueError, OSError, subprocess.SubprocessError) as exc:
                _log.error("Workflow %s could not advance: %s", manifest["execution_id"], exc)


def _on_dispatch_tick(*, board=None, dry_run=False, **_kwargs):
    from hermes_constants import get_hermes_home
    settings_file = Path(__file__).resolve().parent / "config.json"
    if not settings_file.is_file():
        return
    home = Path(json.loads(settings_file.read_text())["hermes_home"]).resolve()
    event_home = Path(get_hermes_home()).resolve()
    if event_home != home and not event_home.is_relative_to(home / "profiles"):
        return
    if dry_run or not _active.acquire(blocking=False):
        return

    def advance():
        try:
            _advance_pending(board)
        finally:
            _active.release()

    threading.Thread(target=advance, name="workflow-advance", daemon=True).start()


def register(ctx):
    ctx.register_hook("on_kanban_dispatch_tick", _on_dispatch_tick)
