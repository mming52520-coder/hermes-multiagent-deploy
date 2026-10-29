"""Run with a Hermes interpreter to check the native read-only plugin contract.

Uses a private home and real native Kanban schema, discovery, routing and auth.
Does not invoke Gateway, workers, models, Docker, or configuration generation.
"""
from __future__ import annotations

import importlib.util
import argparse
import json
import os
from pathlib import Path
import sys
import socket
import tempfile
import time

REPOSITORY = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--info", type=Path)
    args = parser.parse_args()
    if bool(args.assets) != bool(args.info):
        parser.error("--assets and --info must be supplied together")
    if args.assets:
        if not (args.assets / "index.html").is_file():
            parser.error("a built native Dashboard is required")
        os.environ["HERMES_WEB_DIST"] = str(args.assets.resolve())
    with tempfile.TemporaryDirectory(prefix="hermes-readonly-compat-") as temporary:
        directory = Path(temporary)
        home = directory / "hermes"
        home.mkdir()
        for name in ("HERMES_KANBAN_DB", "HERMES_KANBAN_HOME", "HERMES_PROFILE"):
            os.environ.pop(name, None)
        os.environ.update(HERMES_HOME=str(home), HERMES_KANBAN_BOARD="default", HERMES_DESKTOP="0")
        # Dashboard's native enable helper writes only this private configuration.
        (home / "config.yaml").write_text("{}\n", encoding="utf-8")
        project = directory / "project"
        project.mkdir()
        env_file = directory / "app.env"
        env_file.write_text(f"PROJECT_DIR={project}\nBOARD_SLUG=default\n", encoding="utf-8")
        spec = importlib.util.spec_from_file_location("workflow_readonly_installer", REPOSITORY / "scripts/install-workflow-app.py")
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        installer.install(home, env_file)

        from hermes_cli.plugins_cmd import dashboard_set_agent_plugin_enabled
        dashboard_set_agent_plugin_enabled("workflow", enabled=True)
        from hermes_cli.plugins import get_plugin_manager
        manager = get_plugin_manager()
        manager.discover_and_load()
        loaded = next(plugin for plugin in manager.list_plugins() if plugin["name"] == "workflow")
        assert loaded["enabled"] is True and not loaded.get("error"), loaded

        from hermes_cli import kanban_db as kb, web_server
        from fastapi.testclient import TestClient

        if hasattr(kb, "connect_closing"):
            connect_closing = kb.connect_closing
        else:
            from hermes_cli.kanban_db_connect import connect_closing
        roles = ("researcher", "builder", "reviewer", "orchestrator")
        with connect_closing(board="default") as conn:
            tasks = {role: kb.create_task(conn, title=f"Readonly compatibility fixture: {role}", triage=True, board="default") for role in roles}
        execution = "a" * 32
        store = home / "workflow" / "executions" / execution
        store.mkdir(parents=True)
        manifest = {
            "execution_id": execution, "objective": "离线演示 · 中文网页与按键说明",
            "project": str(project), "board": "default", "source_revision": "0" * 40,
            "source_files": {}, "created_at": time.time(), "approved_write": False,
            "rounds": [{"number": 0, "tasks": tasks}], "failures": [],
            "budget": {"max_seconds": 7200, "max_runs": 12, "max_rounds": 2, "max_cost_usd": None},
        }
        (store / "execution.json").write_text(json.dumps(manifest), encoding="utf-8")
        plugins = web_server._discover_dashboard_plugins()
        plugin = next(item for item in plugins if item["name"] == "workflow")
        assert plugin["tab"]["path"] == "/workflow", plugin
        web_server._mount_plugin_api_routes()
        client = TestClient(web_server.app, base_url="http://127.0.0.1")
        url = "/api/plugins/workflow"
        assert client.get(url + "/meta").status_code == 401
        headers = {"X-Hermes-Session-Token": web_server._SESSION_TOKEN}
        meta = client.get(url + "/meta", headers=headers)
        assert meta.status_code == 200, meta.text
        assert meta.json()["actions_enabled"] is False
        records = client.get(url + "/executions", headers=headers)
        assert records.status_code == 200, records.text
        assert set(records.json()["executions"][0]["rounds"][0]["tasks"]) == set(roles)
        assert all(task["status"] == "triage" for task in records.json()["executions"][0]["rounds"][0]["tasks"].values())
        details = client.get(url + "/executions/" + execution, headers=headers)
        assert details.status_code == 200, details.text
        assert details.json()["acceptance"]["status"] == "NOT_ACCEPTED"
        evidence = client.get(url + "/executions/" + execution + "/evidence/0/builder", headers=headers)
        assert evidence.status_code == 200 and evidence.json()["available"] is False
        denied = client.post(url + "/executions", headers=headers, json={"objective": "Must remain read-only"})
        assert denied.status_code == 403, denied.text
        with connect_closing(board="default") as conn:
            assert conn.execute("SELECT count(*) FROM tasks").fetchone()[0] == 4
        print("PASS: native discovery and API mount; auth; metadata; four triage stages; details; missing evidence; mutation denied; no extra task")
        print("Scope: default in-process plugin host, read-only API only. No frontend, worker or write compatibility claim.")
        if args.info:
            import uvicorn
            with socket.socket() as server_socket:
                server_socket.bind(("127.0.0.1", 0))
                port = server_socket.getsockname()[1]
                args.info.write_text(json.dumps({"port": port, "pid": os.getpid(), "goal": manifest["objective"]}), encoding="utf-8")
                server = uvicorn.Server(uvicorn.Config(web_server.app, host="127.0.0.1", port=port,
                                                       lifespan="off", access_log=False, log_level="warning"))
                server.run(sockets=[server_socket])


if __name__ == "__main__":
    main()
