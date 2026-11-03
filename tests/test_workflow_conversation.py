"""Native session persistence, approval isolation and live worker evidence."""
import json
import io
from pathlib import Path
import threading
import tarfile
import time
import unittest
import sqlite3
from unittest.mock import patch
import hermes_bootstrap  # prepare the supplied interpreter before entering a temporary test home
import run_agent

from fastapi import FastAPI
from fastapi.testclient import TestClient
import check_workflow_writes_v0225 as fixtures
import test_workflow_app as app_fixtures


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowWrites()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.env = f.directory / "app.env"
        self.env.write_text("\n".join(f"{k}={v}" for k, v in f.env.items()) + "\n")
        target = app_fixtures.installer.install(f.home, self.env)
        config = target / "config.json"
        settings = json.loads(config.read_text()); settings["allow_actions"] = True
        config.write_text(json.dumps(settings))
        self.config = config
        self.api = app_fixtures.import_file("conversation_api_" + f.execution, target / "dashboard/plugin_api.py")
        app = FastAPI(); app.include_router(self.api.router, prefix="/api/plugins/workflow")
        from hermes_cli import web_server
        token = patch.object(web_server, "_SESSION_TOKEN", "synthetic-session")
        token.start(); self.addCleanup(token.stop)
        self.client = TestClient(app)
        self.client.headers.update({"X-Hermes-Session-Token": "synthetic-session", "X-Hermes-Workflow-Action": "1"})
        self.url = "/api/plugins/workflow"
        self.controller = self.api.conversations_module()
        self.workflow = self.api.bound_workflow(settings)

    def create(self, **body):
        response = self.client.post(self.url + "/conversations", json=body)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def wait(self, id):
        for _ in range(100):
            response = self.client.get(self.url + "/conversations/" + id)
            if response.json()["status"] != "running" and response.json()["pending"] is None:
                return response.json()
            time.sleep(.02)
        self.fail("Controller turn did not finish")

    def test_native_conversation_survives_read_and_cannot_dispatch(self):
        row = self.create()
        inputs = []
        class Agent:
            def __init__(self, record, db): self.session_id, self.db = record["session_id"], db
            def run_conversation(self, text, **kwargs):
                inputs.append(text)
                self.db.create_session(self.session_id, "workflow-controller")
                self.db.append_message(self.session_id, "user", content=kwargs["persist_user_message"])
                result = json.dumps({"reply": "确认需求后可生成任务卡。", "objective": "Implement the synthetic feature and test it."})
                kwargs["stream_callback"](result)
                self.db.append_message(self.session_id, "assistant", content=result)
                return {"final_response": result}
            def close(self): pass
        with patch.object(self.controller, "make_agent", side_effect=lambda w, r, db: Agent(r, db)), patch.object(fixtures.runtime, "dispatch") as dispatch:
            response = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "实现一个功能"})
            self.assertEqual(response.status_code, 200, response.text)
            data = self.wait(row["id"])
            self.assertEqual(data["status"], "idle", data)
            self.assertEqual(data["messages"][-1]["content"], "确认需求后可生成任务卡。")
            self.assertIn("synthetic feature", data["objective"])
            self.assertEqual(data["messages"][0]["content"], "实现一个功能")
            dispatch.assert_not_called()
            self.controller.start(self.workflow, row["id"], "现在的进展？", {"workflow_state": "RUNNING_BUILD_AND_TEST"})
            again = self.wait(row["id"])
            self.assertIn("RUNNING_BUILD_AND_TEST", inputs[-1])
            self.assertEqual(again["messages"][-2]["content"], "现在的进展？")
        other = self.create()
        self.assertEqual(self.client.get(f"{self.url}/conversations/{other['id']}").json()["messages"], [])
        self.assertEqual(len(self.client.get(f"{self.url}/conversations/{row['id']}").json()["messages"]), 4)

    def test_pending_turn_rejects_duplicate_without_losing_the_first_turn(self):
        row = self.create()
        entered, finish = threading.Event(), threading.Event()
        class Agent:
            session_id = row["id"]
            def run_conversation(self, *args, **kwargs):
                entered.set(); finish.wait(4)
                return {"final_response": '{"reply":"done","objective":null}'}
            def close(self): pass
        with patch.object(self.controller, "make_agent", return_value=Agent()):
            first = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "first"})
            self.assertEqual(first.status_code, 200)
            self.assertTrue(entered.wait(2))
            try:
                duplicate = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "duplicate"})
                self.assertEqual(duplicate.status_code, 409)
                pending = self.client.get(f"{self.url}/conversations/{row['id']}").json()["pending"]
                self.assertEqual(pending["input"], "first")
            finally:
                finish.set()
            self.wait(row["id"])

    def test_progress_question_includes_the_current_platform_receipt(self):
        row = self.create(execution=self.fixture.execution)
        task = {"workflow_version": 2, "rounds": [{"number": 0}, {"number": 1}], "workflow_state": "RUNNING_REVIEW"}
        receipt = {"available": True, "receipt": {"status": "PASS", "exit_code": 0}, "log_matches": True, "log_tail": "Ran 9 tests: OK"}
        with patch.object(self.api, "execution_details", return_value=task), patch.object(self.api, "evidence", return_value=receipt) as read, patch.object(self.controller, "start", return_value={"status": "running"}) as start:
            response = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "测试通过了吗？"})
        self.assertEqual(response.status_code, 200, response.text)
        read.assert_called_once_with(self.fixture.execution, 1, "platform")
        self.assertEqual(start.call_args.args[-1]["verification"]["platform"], receipt)

    def test_task_card_is_idempotent_and_stays_unapproved(self):
        row = self.create()
        result = self.client.post(f"{self.url}/conversations/{row['id']}/task", json={"objective": "A synthetic task with fixed acceptance criteria"})
        self.assertEqual(result.status_code, 200, result.text)
        execution = result.json()["execution_id"]
        repeated = self.client.post(f"{self.url}/conversations/{row['id']}/task", json={"objective": "A synthetic task with fixed acceptance criteria"})
        self.assertEqual(repeated.json()["execution_id"], execution)
        manifest = self.workflow.load(execution)
        self.assertFalse(manifest["approved_write"])
        with fixtures.runtime.connect_closing(board="default") as conn:
            self.assertEqual({fixtures.kb.get_task(conn, tid).status for tid in manifest["rounds"][0]["tasks"].values()}, {"triage"})

    def test_auth_readonly_project_and_path_boundaries(self):
        row = self.create()
        self.client.headers.pop("X-Hermes-Session-Token")
        self.assertEqual(self.client.get(f"{self.url}/conversations/{row['id']}").status_code, 401)
        self.client.headers["X-Hermes-Session-Token"] = "synthetic-session"
        self.assertEqual(self.client.get(self.url + "/conversations/not-an-id").status_code, 404)
        config = json.loads(self.config.read_text()); config["allow_actions"] = False
        self.config.write_text(json.dumps(config))
        self.assertEqual(self.client.post(self.url + "/conversations", json={}).status_code, 403)
        self.assertEqual(self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "hello"}).status_code, 403)

    def test_activity_reads_a_running_worker_not_only_completed_runs(self):
        from hermes_state import SessionDB
        f = self.fixture
        f.workflow.start(f.execution, True)
        task_id = f.manifest["rounds"][0]["tasks"]["researcher"]
        with fixtures.runtime.connect_closing(board="default") as conn:
            fixtures.kb.recompute_ready(conn)
            fixtures.kb.claim_task(conn, task_id)
            run = fixtures.kb.latest_run(conn, task_id)
            path = f.home / "profiles" / run.profile / "state.db"
            db = SessionDB(db_path=path)
            try:
                db.create_session("live-synthetic-worker", "cli")
                db.append_message("live-synthetic-worker", "assistant", content="正在检查入口。", tool_calls=[{"id": "call1", "type": "function", "function": {"name": "read_file", "arguments": '{"path":"source.py"}'}}])
                db.append_message("live-synthetic-worker", "tool", tool_name="read_file", content="source contents")
            finally: db.close()
            with sqlite3.connect(path) as messages:
                messages.execute("UPDATE messages SET reasoning_content='internal-only-thinking'")
            fixtures.kb._append_event(conn, task_id, "owner_admitted", {"session_id": "live-synthetic-worker", "db": str(path)}, run_id=run.id)
        response = self.client.get(f"{self.url}/executions/{f.execution}/activity")
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["roles"]["researcher"]["status"], "running")
        self.assertTrue(any(item["kind"] == "tool" and item["name"] == "read_file" for item in data["events"]))
        self.assertNotIn("reasoning_content", response.text)
        self.assertNotIn("internal-only-thinking", response.text)

    def test_controller_uses_native_main_connection_without_execution_tools(self):
        row = self.create()
        runtime = {"provider": "synthetic-provider", "api_mode": "anthropic_messages", "api_key": "synthetic-key", "base_url": "https://models.example"}
        config = {"model": {"provider": "synthetic-provider", "default": "synthetic-model"}, "agent": {"reasoning_effort": "none"}}
        with patch("hermes_cli.config.load_config", return_value=config), patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value=runtime) as resolve, patch.object(run_agent, "AIAgent") as native:
            self.controller.make_agent(self.workflow, row, object())
        resolve.assert_called_once_with(requested="synthetic-provider", target_model="synthetic-model")
        options = native.call_args.kwargs
        self.assertEqual(options["enabled_toolsets"], [])
        self.assertEqual(options["model"], "synthetic-model")
        self.assertEqual(options["api_mode"], "anthropic_messages")
        self.assertTrue(options["skip_context_files"])

    def test_delivery_includes_new_files_and_excludes_git_and_external_links(self):
        manifest = self.workflow.load(self.fixture.execution)
        row = manifest["rounds"][-1]
        source = Path(row["review"])
        (source / "new-file.txt").write_text("synthetic delivered feature\n")
        private = self.fixture.directory / "private.txt"; private.write_text("outside snapshot")
        (source / "external-link").symlink_to(private)
        core = self.api.core_module()
        row.update(snapshot_ready=True, candidate_files=core.tree_files(source))
        row["candidate_digest"] = core.digest(row["candidate_files"])
        self.workflow.save(manifest)
        detail = self.client.get(f"{self.url}/executions/{self.fixture.execution}/delivery")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("synthetic delivered feature", detail.json()["patch"])
        response = self.client.get(f"{self.url}/executions/{self.fixture.execution}/download")
        self.assertEqual(response.status_code, 200)
        with tarfile.open(fileobj=io.BytesIO(response.content)) as archive:
            names = archive.getnames()
            self.assertFalse(any(".git" in Path(name).parts or name.endswith("external-link") for name in names))
            self.assertEqual(archive.extractfile(self.workflow.project.name + "/new-file.txt").read(), b"synthetic delivered feature\n")


if __name__ == "__main__":
    unittest.main()
