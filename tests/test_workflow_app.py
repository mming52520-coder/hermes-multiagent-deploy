"""Authenticated HTTP adapter and additive plugin installation tests."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import test_workflow as fixtures

REPOSITORY = fixtures.REPOSITORY


def import_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


installer = import_file("workflow_app_installer_test", REPOSITORY / "scripts" / "install-workflow-app.py")


class ApplicationTest(unittest.TestCase):
    def setUp(self):
        # Reuse the real native-DB fixture, without rerunning inherited tests.
        self.fixture = fixtures.WorkflowTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.env_file = f.directory / "app.env"
        self.env_file.write_text("\n".join(f"{key}={value}" for key, value in f.env.items()) +
                                 "\nPACKY_CLAUDE_API_KEY=unit-test-private-value\n", encoding="utf-8")
        self.target = installer.install(f.root, self.env_file)
        self.api = import_file("workflow_app_http_test_" + f.execution,
                               self.target / "dashboard" / "plugin_api.py")
        self.app = FastAPI()
        self.app.include_router(self.api.router, prefix="/api/plugins/workflow")
        from hermes_cli import web_server
        token = patch.object(web_server, "_SESSION_TOKEN", "unit-test-session")
        token.start()
        self.addCleanup(token.stop)
        self.client = TestClient(self.app)
        self.client.headers["X-Hermes-Session-Token"] = "unit-test-session"
        self.url = "/api/plugins/workflow"

    def enable_actions(self):
        file = self.target / "config.json"
        data = json.loads(file.read_text(encoding="utf-8"))
        data["allow_actions"] = True
        file.write_text(json.dumps(data), encoding="utf-8")

    def test_requires_actual_dashboard_session(self):
        unauthenticated = TestClient(self.app)
        self.assertEqual(unauthenticated.get(self.url + "/meta").status_code, 401)
        self.assertEqual(unauthenticated.post(self.url + "/executions", json={"objective":"unauthorized"}).status_code, 401)
        self.assertEqual(self.client.get(self.url + "/meta").status_code, 200)

    def test_cookie_auth_also_uses_canonical_gate(self):
        self.app.state.auth_required = True
        self.assertEqual(self.client.get(self.url + "/meta").status_code, 401)
        self.app.middleware_stack = None
        @self.app.middleware("http")
        async def authenticated_cookie(request, call_next):
            request.state.session = {"principal":"fixture"}
            return await call_next(request)
        # Build a fresh middleware stack after configuring the fixture.
        self.app.middleware_stack = None
        self.assertEqual(TestClient(self.app).get(self.url + "/meta").status_code, 200)

    def test_browse_lists_native_states_without_exposing_environment(self):
        result = self.client.get(self.url + "/executions")
        self.assertEqual(result.status_code, 200)
        data = result.json()["executions"]
        self.assertEqual(data[0]["execution_id"], self.fixture.execution)
        self.assertEqual(data[0]["rounds"][0]["tasks"]["builder"]["status"], "triage")
        self.assertNotIn("unit-test-private-value", result.text)
        self.assertNotIn("PACKY_CLAUDE_API_KEY", result.text)

    def test_default_mode_rejects_all_mutations_server_side(self):
        self.assertFalse(self.client.get(self.url + "/meta").json()["actions_enabled"])
        self.assertEqual(self.client.post(self.url + "/executions", json={"objective":"blocked"}).status_code,403)
        for action in ("start","prepare-review","verify-builder","verify-reviewer","accept","repair"):
            response=self.client.post(f"{self.url}/executions/{self.fixture.execution}/actions/{action}",json={"confirmed":True},headers={"X-Hermes-Workflow-Action":"1"})
            self.assertEqual(response.status_code,403,action)

    def test_missing_confirmation_and_cross_origin_requests_rejected(self):
        self.enable_actions()
        url=f"{self.url}/executions/{self.fixture.execution}/actions/start"
        self.assertEqual(self.client.post(url,json={"confirmed":True}).status_code,403)
        self.assertEqual(self.client.post(url,json={"confirmed":False},headers={"X-Hermes-Workflow-Action":"1"}).status_code,400)
        self.assertEqual(self.client.post(url,json={"confirmed":True},headers={"X-Hermes-Workflow-Action":"1","Origin":"https://untrusted.example"}).status_code,403)

    def test_requests_cannot_supply_shell_commands_or_environment_paths(self):
        for additional in ({"command":"echo unexpected"},{"env_file":"/etc/shadow"}):
            response=self.client.post(self.url + "/executions",json={"objective":"fixture",**additional})
            self.assertEqual(response.status_code,422)
        self.assertEqual(self.client.post(f"{self.url}/executions/{self.fixture.execution}/actions/shell",json={"confirmed":True}).status_code,422)

    def test_confirmed_submit_uses_existing_native_four_stage_plan(self):
        self.enable_actions()
        core=self.api.core_module()
        with patch.object(core,"verify_source",return_value={}) as provenance:
            result=self.client.post(self.url + "/executions",json={"objective":"HTTP fixture goal","instance":"browser-test"},headers={"X-Hermes-Workflow-Action":"1"})
        self.assertEqual(result.status_code,200,result.text)
        provenance.assert_called_once()
        detail=self.client.get(self.url + "/executions/" + result.json()["execution_id"])
        self.assertEqual(detail.status_code,200,detail.text)
        self.assertEqual(set(detail.json()["rounds"][0]["tasks"]),set(self.fixture.row()["tasks"]))
        self.assertEqual(detail.json()["acceptance"]["status"],"NOT_ACCEPTED")

    def test_gate_failure_is_preserved_as_http_conflict(self):
        self.enable_actions()
        core=self.api.core_module()
        with patch.object(core,"verify_source",return_value={}):
            response=self.client.post(f"{self.url}/executions/{self.fixture.execution}/actions/accept",json={"confirmed":True},headers={"X-Hermes-Workflow-Action":"1"})
        self.assertEqual(response.status_code,409)
        self.assertIn("WRITE_NOT_APPROVED",response.json()["detail"])
        self.assertFalse((self.fixture.workflow.path(self.fixture.execution)/"acceptance.json").exists())

    def test_evidence_matches_real_operator_record_and_bounds_log_tail(self):
        self.fixture.finish()
        directory=self.fixture.workflow.path(self.fixture.execution)/"round-0"
        log=directory/"reviewer-verification.log"
        log.write_text("x"*20000 + "\nEND-OF-TEST-LOG",encoding="utf-8")
        file=directory/"reviewer-verification.json"
        receipt=json.loads(file.read_text(encoding="utf-8"))
        receipt["log_sha256"]=hashlib.sha256(log.read_bytes()).hexdigest()
        file.write_text(json.dumps(receipt),encoding="utf-8")
        response=self.client.get(f"{self.url}/executions/{self.fixture.execution}/evidence/0/reviewer")
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()["log_matches"])
        self.assertLessEqual(len(response.json()["log_tail"].encode()),16384)
        self.assertTrue(response.json()["log_tail"].endswith("END-OF-TEST-LOG"))

    def test_unknown_execution_and_unsupported_evidence_cannot_read_files(self):
        self.assertEqual(self.client.get(self.url + "/executions/" + "f"*32).status_code,404)
        self.assertEqual(self.client.get(self.url + "/executions/not-an-id").status_code,400)
        self.assertEqual(self.client.get(f"{self.url}/executions/{self.fixture.execution}/evidence/-1/builder").status_code,404)
        self.assertEqual(self.client.get(f"{self.url}/executions/{self.fixture.execution}/evidence/0/secrets").status_code,422)

    def test_missing_native_database_does_not_create_an_empty_replacement(self):
        from hermes_cli import kanban_db as kb
        database=kb.kanban_db_path(board="default")
        saved=database.with_suffix(".fixture-backup")
        database.rename(saved)
        try:
            response=self.client.get(f"{self.url}/executions/{self.fixture.execution}")
            self.assertEqual(response.status_code,409)
            self.assertFalse(database.exists())
        finally:
            saved.rename(database)

    def test_application_is_bound_to_operator_selected_project(self):
        foreign=json.loads(json.dumps(self.fixture.manifest))
        foreign["execution_id"]="d"*32
        foreign["project"]=str(self.fixture.directory/"another-project")
        directory=self.fixture.workflow.store/foreign["execution_id"]
        directory.mkdir()
        (directory/"execution.json").write_text(json.dumps(foreign),encoding="utf-8")
        result=self.client.get(self.url+"/executions")
        self.assertEqual(len(result.json()["executions"]),1)
        self.assertEqual(self.client.get(self.url+"/executions/"+foreign["execution_id"]).status_code,404)
        self.assertEqual(self.client.post(f"{self.url}/executions/{foreign['execution_id']}/actions/start",json={"confirmed":True}).status_code,404)

    def test_reinstall_preserves_local_settings_and_rejects_edited_assets(self):
        self.enable_actions()
        before=(self.target/"config.json").read_bytes()
        installer.install(self.fixture.root,self.env_file)
        self.assertEqual((self.target/"config.json").read_bytes(),before)
        with patch.object(installer.subprocess,"run") as enable:
            installer.install(self.fixture.root,self.env_file,enable=True)
        self.assertIn("--no-allow-tool-override",enable.call_args.args[0])
        (self.target/"dashboard"/"app.js").write_text("user local edit",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"插件本地修改"):
            installer.install(self.fixture.root,self.env_file)

    def test_native_dashboard_discovers_and_mounts_application(self):
        from hermes_cli import web_server, plugins_cmd
        plugins=web_server._discover_dashboard_plugins()
        workflow=next(item for item in plugins if item["name"] == "workflow")
        self.assertEqual(workflow["tab"]["path"],"/workflow")
        mounted=FastAPI()
        with patch.object(web_server,"app",mounted),patch.object(web_server,"_get_dashboard_plugins",return_value=[workflow]), \
             patch.object(plugins_cmd,"_get_enabled_set",return_value={"workflow"}),patch.object(plugins_cmd,"_get_disabled_set",return_value=set()):
            web_server._mount_plugin_api_routes()
        client=TestClient(mounted)
        self.assertEqual(client.get(self.url+"/meta").status_code,401)
        self.assertEqual(client.get(self.url+"/meta",headers={"X-Hermes-Session-Token":"unit-test-session"}).status_code,200)


if __name__ == "__main__":
    unittest.main()
