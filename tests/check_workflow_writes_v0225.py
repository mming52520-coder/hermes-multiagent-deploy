"""Real v0.22.5 DB/profile/API contracts; only Gateway startup and worker processes are doubles."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
import workflow_control as wc
import workflow_runtime as runtime
from configure_profiles import write_yaml
from hermes_cli import kanban_db as kb
from hermes_cli import kanban_db_dispatch as dispatcher
from hermes_cli.gateway_runtime import GatewayDiscovery, GatewayEndpoint
from hermes_baseline import verify_source, verify_workflow_source, WORKFLOW_COMMIT

ARCHIVE = Path(os.environ["HERMES_BASELINE_ARCHIVE"])


class WorkflowWrites(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="hermes-workflow-v0225-")
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.home = self.directory / "state"
        self.home.mkdir(mode=0o700)
        environment = {k: v for k, v in os.environ.items() if k in {"HOME", "PATH", "LANG", "PYTHONPATH"}}
        environment.update(HERMES_HOME=str(self.home), HERMES_KANBAN_BOARD="default", HERMES_DESKTOP="0")
        patcher = patch.dict(os.environ, environment, clear=True)
        patcher.start(); self.addCleanup(patcher.stop)
        self.project = self.directory / "project"
        wc.independent_clone(REPO, self.project, wc.git(REPO, "rev-parse", "HEAD"))
        for role in wc.ROLES:
            tools = ["kanban", "memory", "skills"] if role == "orchestrator" else ["terminal", "file"]
            write_yaml(self.home / "profiles" / role / "config.yaml", {
                "model": {"provider": "test-provider", "default": "offline-fixture"},
                "terminal": {"backend": "docker"}, "toolsets": tools, "platform_toolsets": {"cli": tools},
            })
        write_yaml(self.home / "config.yaml", {"kanban": {"dispatch_in_gateway": True}})
        self.env = {"PROJECT_DIR": str(self.project), "BOARD_SLUG": "default", "OUTPUT_DIR": str(self.directory / "outputs"),
                    "DOCKER_IMAGE": "offline-test-image", "WORKFLOW_TEST_COMMAND": "python -m unittest"}
        self.workflow = wc.Workflow(self.home, self.env)
        self.manifest = self.workflow.submit("Implement a verified synthetic change")
        self.execution = self.manifest["execution_id"]

    def statuses(self):
        with runtime.connect_closing(board="default") as conn:
            return {role: kb.get_task(conn, tid).status for role, tid in self.manifest["rounds"][0]["tasks"].items()}

    def ready(self):
        return {"ready": True, "approved": True, "checks": []}

    def test_submission_creates_four_native_triage_cards(self):
        self.assertEqual(set(self.statuses()), set(wc.ROLES))
        self.assertEqual(set(self.statuses().values()), {"triage"})
        self.assertFalse(self.manifest["approved_write"])
        repeated = self.workflow.submit(self.manifest["objective"])
        self.assertEqual(repeated["rounds"][0]["tasks"], self.manifest["rounds"][0]["tasks"])

    def test_approval_is_persisted_but_does_not_release_or_dispatch(self):
        with patch.object(runtime, "dispatch") as dispatch:
            approved = self.workflow.approve(self.execution)
        dispatch.assert_not_called()
        self.assertTrue(approved["approved_write"])
        self.assertEqual(approved["approval"]["round"], 0)
        self.assertEqual(approved["approval"]["source_revision"], self.manifest["source_revision"])
        self.assertEqual(set(self.statuses().values()), {"triage"})

    def test_launch_without_approval_is_rejected(self):
        with patch.object(runtime, "dispatch") as dispatch, self.assertRaisesRegex(wc.Rejected, "WRITE_NOT_APPROVED"):
            self.workflow.launch(self.execution)
        dispatch.assert_not_called()
        self.assertEqual(set(self.statuses().values()), {"triage"})

    def test_failed_prerequisites_do_not_release_tasks(self):
        self.workflow.approve(self.execution)
        missing = {"ready": False, "checks": [{"ready": False, "label": "Docker", "detail": "Unavailable"}]}
        with patch.object(self.workflow, "readiness", return_value=missing), patch.object(runtime, "dispatch") as dispatch:
            with self.assertRaisesRegex(wc.Rejected, "EXECUTION_NOT_READY"):
                self.workflow.launch(self.execution)
        dispatch.assert_not_called()
        self.assertEqual(set(self.statuses().values()), {"triage"})

    def test_launch_uses_native_claims_and_retries_do_not_spawn_duplicates(self):
        self.workflow.approve(self.execution)
        endpoint = GatewayEndpoint("default", "test-owner", 1, 1, "http://127.0.0.1", "none", frozenset())
        owner = GatewayDiscovery("ready", endpoint=endpoint)
        native_dispatch = dispatcher.dispatch_once
        children = []

        def spawn(task, workspace):
            child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            children.append(child)
            return child.pid

        def dispatch(conn, **kwargs):
            return native_dispatch(conn, spawn_fn=spawn, reconcile_orphans=False, **kwargs)

        try:
            with patch.object(self.workflow, "readiness", side_effect=lambda _: self.ready()), \
                    patch("hermes_cli.gateway_runtime.ensure_gateway_runtime", return_value=owner), \
                    patch.object(dispatcher, "dispatch_once", side_effect=dispatch):
                first = self.workflow.launch(self.execution)
                second = self.workflow.launch(self.execution)
            self.assertEqual(len(first["dispatch"]["spawned"]), 1)
            self.assertEqual(second["dispatch"]["spawned"], [])
            self.assertEqual(self.statuses()["researcher"], "running")
            self.assertEqual(self.statuses()["reviewer"], "triage")
            self.assertEqual(len(children), 1)
        finally:
            for child in children:
                child.wait(timeout=5)

    def test_changed_round_cannot_reuse_an_old_approval(self):
        self.workflow.approve(self.execution)
        manifest = self.workflow.load(self.execution)
        manifest["rounds"][-1]["number"] = 1
        manifest["approved_write"] = False
        self.workflow.save(manifest)
        with self.assertRaisesRegex(wc.Rejected, "WRITE_NOT_APPROVED"):
            self.workflow.start(self.execution, True, approved_round=0)
        self.assertEqual(set(self.statuses().values()), {"triage"})

    def test_stale_confirmation_cannot_approve_or_launch_another_round(self):
        manifest = self.workflow.load(self.execution)
        manifest["rounds"][-1]["number"] = 1
        self.workflow.save(manifest)
        with self.assertRaisesRegex(wc.Rejected, "ROUND_CHANGED"):
            self.workflow.approve(self.execution, expected_round=0)
        self.assertFalse(self.workflow.load(self.execution)["approved_write"])
        with patch.object(runtime, "dispatch") as dispatch, self.assertRaisesRegex(wc.Rejected, "ROUND_CHANGED"):
            self.workflow.launch(self.execution, expected_round=0)
        dispatch.assert_not_called()

    def test_readiness_reports_missing_docker_without_exposing_secrets(self):
        with patch.object(runtime.shutil, "which", return_value=None):
            result = self.workflow.readiness(self.execution)
        self.assertFalse(result["ready"])
        self.assertFalse(next(item for item in result["checks"] if item["code"] == "docker")["ready"])
        self.assertNotIn("api_key", json.dumps(result))

    def test_workflow_pin_is_explicit_and_does_not_change_deployment_pin(self):
        source = Path(kb.__file__).resolve().parents[1]
        verified = verify_workflow_source(source, ARCHIVE)
        self.assertEqual(verified["commit"], WORKFLOW_COMMIT)
        self.assertEqual(verified["version"], "0.22.5")
        with self.assertRaises(ValueError):
            verify_source(source, ARCHIVE)
        with self.assertRaises(ValueError):
            verify_workflow_source(self.project)

    def test_authenticated_http_create_approve_and_launch_gate_on_modern_source(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from hermes_cli import web_server

        def load(name, file):
            spec = importlib.util.spec_from_file_location(name, file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        installer = load("modern_workflow_installer", REPO / "scripts" / "install-workflow-app.py")
        env_file = self.directory / "workflow.env"
        env_file.write_text("\n".join(f"{key}={value}" for key, value in self.env.items()) + "\n")
        target = installer.install(self.home, env_file, archive=ARCHIVE)
        settings_file = target / "config.json"
        settings = json.loads(settings_file.read_text())
        settings["allow_actions"] = True
        settings_file.write_text(json.dumps(settings))
        api = load("modern_workflow_api_" + self.execution, target / "dashboard" / "plugin_api.py")
        app = FastAPI()
        app.include_router(api.router, prefix="/api/plugins/workflow")
        url = "/api/plugins/workflow/executions"
        client = TestClient(app)
        with patch.object(web_server, "_SESSION_TOKEN", "synthetic-session"):
            self.assertEqual(client.post(url, json={"objective": "unauthorized"}).status_code, 401)
            client.headers.update({"X-Hermes-Session-Token": "synthetic-session", "X-Hermes-Workflow-Action": "1"})
            created = client.post(url, json={"objective": "HTTP synthetic development goal"})
            self.assertEqual(created.status_code, 200, created.text)
            execution = created.json()["execution_id"]
            action = f"{url}/{execution}/actions/"
            self.assertEqual(client.post(action + "launch", json={"confirmed": True, "round_number": 0}).status_code, 409)
            self.assertEqual(client.post(action + "approve", json={"confirmed": False, "round_number": 0}).status_code, 400)
            self.assertEqual(client.post(action + "approve", json={"confirmed": True, "round_number": 0},
                                         headers={"Origin": "https://untrusted.example"}).status_code, 403)
            with runtime.home_scope(self.directory / "unrelated-profile"):
                # A native Dashboard profile selection cannot change the bound board/home.
                approved = client.post(action + "approve", json={"confirmed": True, "round_number": 0})
                scoped = client.get(f"{url}/{execution}")
            self.assertEqual(scoped.status_code, 200, scoped.text)
            self.assertTrue(scoped.json()["approved_write"])
            self.assertEqual(approved.status_code, 200, approved.text)
            detail = client.get(f"{url}/{execution}").json()
            self.assertTrue(detail["approved_write"])
            self.assertIsNotNone(detail["approval"])
            self.assertEqual({task["status"] for task in detail["rounds"][0]["tasks"].values()}, {"triage"})
            core = api.core_module()
            with patch.object(core.workflow_runtime.shutil, "which", return_value=None), \
                    patch.object(core.workflow_runtime, "dispatch") as dispatch:
                blocked = client.post(action + "launch", json={"confirmed": True, "round_number": 0})
            dispatch.assert_not_called()
            self.assertEqual(blocked.status_code, 409, blocked.text)
            self.assertIn("EXECUTION_NOT_READY", blocked.json()["detail"])
            detail = client.get(f"{url}/{execution}").json()
            self.assertEqual({task["status"] for task in detail["rounds"][0]["tasks"].values()}, {"triage"})
            self.assertEqual(client.post(url, json={"objective": "unsafe payload", "command": "arbitrary"}).status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
