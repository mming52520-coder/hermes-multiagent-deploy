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

    def model_reply(self, payload, inputs=None, system_messages=None):
        def factory(workflow, row, db):
            class Agent:
                session_id = row["session_id"]

                def run_conversation(self, text, **kwargs):
                    if inputs is not None:
                        inputs.append(text)
                    if system_messages is not None:
                        system_messages.append(kwargs["system_message"])
                    db.append_message(self.session_id, "user", content=kwargs["persist_user_message"])
                    response = json.dumps(payload, ensure_ascii=False)
                    db.append_message(self.session_id, "assistant", content=response)
                    return {"final_response": response}

                def close(self): pass
            return Agent()
        return patch.object(self.controller, "make_agent", side_effect=factory)

    def test_document_publication_binds_type_and_reuses_task(self):
        objective = "只交付一份方案报告，包含方案比较及可追溯证据；不实现代码。"
        reply = {"reply": "准备发布方案任务。", "objective": objective, "publish": True, "deliverable_type": "document"}
        core = self.api.core_module()
        with self.model_reply(reply), patch.object(core.Workflow, "readiness", return_value={"ready": True}), \
                patch.object(core.workflow_runtime, "dispatch", return_value={"spawned": []}):
            for delivery in ("document", "code"):
                reply["deliverable_type"] = delivery
                response = self.client.post(self.url + "/architect/messages", json={"message": "创建方案任务"})
                result = self.wait(response.json()["id"])
                self.assertEqual(result["status"], "idle", result["error"])
                self.assertEqual(len(result["execution_ids"]), 1)
        manifest = self.workflow.load(result["execution_ids"][0])
        self.assertEqual(manifest["deliverable_type"], "document")
        self.assertEqual(manifest["test_command"], core.DOCUMENT_TEST_COMMAND)
        self.assertTrue(manifest["approved_write"])

    def test_invalid_delivery_type_does_not_publish_or_break_chat_view(self):
        reply = {"reply": "Invalid typed proposal.", "objective": "A task", "publish": True, "deliverable_type": "skip-tests"}
        with self.model_reply(reply):
            response = self.client.post(self.url + "/architect/messages", json={"message": "创建任务"})
            result = self.wait(response.json()["id"])
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["execution_ids"], [])
        self.assertIn("unsupported deliverable", result["error"])

    def test_architect_turn_loads_packaged_guidance_with_existing_protocol(self):
        systems = []
        with self.model_reply({"reply": "讨论范围。", "objective": None, "publish": False}, system_messages=systems):
            response = self.client.post(self.url + "/architect/messages", json={"message": "先讨论方案"})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(self.wait(response.json()["id"])["execution_ids"], [])
        guidance = self.controller.workflow_skills.architect_guidance()
        self.assertEqual(systems, [self.controller.PROMPT + "\n\n" + guidance])

    def test_resumed_controller_rebuilds_changed_guidance_once_and_keeps_history(self):
        from agent.conversation_loop import _restore_or_build_system_prompt
        from hermes_state_registry import acquire, release

        row = self.controller.architect(self.workflow)
        db = acquire(self.workflow.root / "state.db")
        self.addCleanup(release, db)
        old = "LEGACY_BUTTON_ONLY: cannot publish; use the task button."
        db.update_system_prompt(row["session_id"], old)
        db.append_message(row["session_id"], "user", content="Keep this confirmed requirement.")
        db.append_message(row["session_id"], "assistant", content="Use the task button.")
        original = db.get_messages_as_conversation(row["session_id"])
        db.create_session("unrelated-controller", "workflow-controller", system_prompt=old)
        observed, builds = [], []

        def factory(workflow, current_row, session_db):
            # Actual native prompt restoration and persistence; no provider call.
            agent = run_agent.AIAgent(
                model="fixture-model", provider="openai-api", api_key="synthetic-test-key",
                base_url="https://example.invalid/v1", api_mode="chat_completions",
                enabled_toolsets=[], quiet_mode=True, skip_context_files=True, skip_memory=True,
                skip_background_review=True, platform="workflow-controller", cwd=str(workflow.project),
                session_id=current_row["session_id"], session_db=session_db,
            )
            build = agent._build_system_prompt
            def tracked_build(prompt):
                builds.append(prompt)
                return build(prompt)
            agent._build_system_prompt = tracked_build
            def turn(text, **kwargs):
                _restore_or_build_system_prompt(agent, kwargs["system_message"], kwargs["conversation_history"])
                observed.append(agent._cached_system_prompt)
                session_db.append_message(agent.session_id, "user", content=kwargs["persist_user_message"])
                reply = json.dumps({"reply": "Capability question only.", "objective": None, "publish": False})
                session_db.append_message(agent.session_id, "assistant", content=reply)
                return {"final_response": reply}
            agent.run_conversation = turn
            return agent

        guidance = self.controller.workflow_skills.architect_guidance()
        before = set(self.workflow.store.glob("*/execution.json"))
        with patch.object(self.controller, "make_agent", side_effect=factory):
            for instruction in (guidance, guidance, guidance + "\nUpdated controller guidance."):
                with patch.object(self.controller.workflow_skills, "architect_guidance", return_value=instruction):
                    response = self.client.post(self.url + "/architect/messages", json={"message": "现在能直接发布任务吗？"})
                    self.assertEqual(response.status_code, 200)
                    result = self.wait(response.json()["id"])
                    self.assertEqual(result["status"], "idle", result["error"])
                    self.assertIn(self.controller.PROMPT + "\n\n" + instruction, observed[-1])
                    self.assertNotIn(old, observed[-1])
        self.assertEqual(len(builds), 2)
        self.assertEqual(observed[0], observed[1])
        self.assertNotEqual(observed[1], observed[2])
        self.assertEqual(db.get_messages_as_conversation(row["session_id"])[:2], original)
        self.assertEqual(db.get_session("unrelated-controller")["system_prompt"], old)
        self.assertEqual(set(self.workflow.store.glob("*/execution.json")), before)

    def test_architect_publishes_and_starts_from_chat_and_reuses_repeated_task(self):
        core = self.api.core_module()
        objective = "目标：实现示例功能。范围：独立候选。验收：固定测试通过。"
        payload = {"reply": "总控台对话：需求已整理，准备发布。", "objective": objective, "publish": True}
        inputs = []
        with self.model_reply(payload, inputs), patch.object(core.Workflow, "readiness", return_value={"ready": True, "checks": []}), \
                patch.object(core.workflow_runtime, "dispatch", return_value={"spawned": []}) as dispatch:
            response = self.client.post(self.url + "/architect/messages", json={"message": "需求已明确，请发布任务并执行"})
            self.assertEqual(response.status_code, 200, response.text)
            row = self.wait(response.json()["id"])
            self.assertEqual(row["status"], "idle", row["error"])
            execution = row["execution_id"]
            manifest = self.workflow.load(execution)
            self.assertEqual(manifest["objective"], objective)
            self.assertTrue(manifest["approved_write"])
            self.assertEqual(manifest["workflow_state"], "RUNNING_RESEARCH")
            self.assertEqual(manifest["decisions_log"][-1]["by"], "web")
            self.assertEqual(row["submitted_objective"], objective)
            self.assertIn('"can_publish": true', inputs[-1])
            self.assertEqual(row["messages"][-2]["content"], "需求已整理，准备发布。")
            self.assertIn(execution, row["messages"][-1]["content"])
            self.assertIn("任务已发布", row["messages"][-1]["content"])
            with fixtures.runtime.connect_closing(board="default") as conn:
                tasks = manifest["rounds"][0]["tasks"]
                self.assertEqual(set(tasks), {"researcher", "builder", "tester", "reviewer"})
                self.assertIn(fixtures.kb.get_task(conn, tasks["researcher"]).status, {"todo", "ready"})
                self.assertEqual({fixtures.kb.get_task(conn, tasks[r]).status for r in ("builder", "tester", "reviewer")}, {"triage"})
            # The older URL for this same architect session has the same capability.
            response = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "再次发布相同任务"})
            self.assertEqual(response.status_code, 200, response.text)
            repeated = self.wait(row["id"])
            self.assertEqual(repeated["execution_ids"], [execution])
            self.assertEqual(len(self.workflow.load(execution)["decisions_log"]), 1)
            dispatch.assert_called_once()

    def test_discussion_and_invalid_publish_flags_do_not_create_or_approve_tasks(self):
        before = set(self.workflow.store.glob("*/execution.json"))
        core = self.api.core_module()
        with patch.object(core.workflow_runtime, "dispatch") as dispatch:
            for intent in (False, "true", 1, None):
                with self.subTest(intent=intent), self.model_reply({"reply": "先讨论范围。", "objective": "尚在讨论的草案", "publish": intent}):
                    response = self.client.post(self.url + "/architect/messages", json={"message": "先讨论，不执行"})
                    row = self.wait(response.json()["id"])
                    self.assertEqual(row["execution_ids"], [])
            dispatch.assert_not_called()
        self.assertEqual(set(self.workflow.store.glob("*/execution.json")), before)

    def test_publication_requires_a_complete_nonempty_objective(self):
        before = set(self.workflow.store.glob("*/execution.json"))
        for objective in (None, "  ", "x" * 4001):
            with self.subTest(objective_length=len(objective or "")), self.model_reply({"reply": "准备发布。", "objective": objective, "publish": True}):
                response = self.client.post(self.url + "/architect/messages", json={"message": "发布任务"})
                row = self.wait(response.json()["id"])
                self.assertEqual(row["status"], "failed")
                self.assertIn("任务发布未完成", row["messages"][-1]["content"])
        self.assertEqual(set(self.workflow.store.glob("*/execution.json")), before)

    def test_missing_runtime_conditions_publish_but_never_claim_work_is_running(self):
        core = self.api.core_module()
        checks = {"ready": False, "checks": [{"ready": False, "label": "Docker", "detail": "服务未运行"}]}
        with self.model_reply({"reply": "准备发布。", "objective": "Synthetic runtime readiness task", "publish": True}), \
                patch.object(core.Workflow, "readiness", return_value=checks), patch.object(core.workflow_runtime, "dispatch") as dispatch:
            response = self.client.post(self.url + "/architect/messages", json={"message": "发布并执行"})
            row = self.wait(response.json()["id"])
            manifest = self.workflow.load(row["execution_id"])
            self.assertTrue(manifest["approved_write"])
            self.assertEqual(manifest["workflow_state"], "HUMAN_REQUIRED")
            self.assertIn("尚未开始执行：Docker：服务未运行", row["messages"][-1]["content"])
            dispatch.assert_not_called()

    def test_failed_publication_is_persisted_as_failure_without_a_success_receipt(self):
        core = self.api.core_module()
        with self.model_reply({"reply": "准备发布。", "objective": "Synthetic failing task", "publish": True}), \
                patch.object(core.Workflow, "submit", side_effect=ValueError("Synthetic creation failure")):
            response = self.client.post(self.url + "/architect/messages", json={"message": "发布任务"})
            row = self.wait(response.json()["id"])
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["execution_ids"], [])
        self.assertEqual(row["messages"][-1]["content"], "任务发布未完成：Synthetic creation failure")

    def test_publication_recovers_an_initial_grant_interrupted_before_start(self):
        objective = "Synthetic interrupted initial publication"
        created = self.client.post(self.url + "/architect/tasks", json={"objective": objective})
        execution = created.json()["execution_id"]
        self.workflow.approve(execution, expected_round=0)
        core = self.api.core_module()
        with self.model_reply({"reply": "准备继续发布。", "objective": objective, "publish": True}), \
                patch.object(core.Workflow, "readiness", return_value={"ready": True, "checks": []}), \
                patch.object(core.workflow_runtime, "dispatch", return_value={"spawned": []}) as dispatch:
            response = self.client.post(self.url + "/architect/messages", json={"message": "继续发布此任务"})
            row = self.wait(response.json()["id"])
        self.assertEqual(row["execution_ids"], [execution])
        self.assertEqual(self.workflow.load(execution)["workflow_state"], "RUNNING_RESEARCH")
        dispatch.assert_called_once()

    def test_republishing_a_rejected_task_does_not_reverse_the_decision(self):
        objective = "Synthetic rejected task"
        created = self.client.post(self.url + "/architect/tasks", json={"objective": objective})
        execution = created.json()["execution_id"]
        self.workflow.reject(execution, "No longer needed")
        with self.model_reply({"reply": "准备发布。", "objective": objective, "publish": True}):
            response = self.client.post(self.url + "/architect/messages", json={"message": "发布相同任务"})
            row = self.wait(response.json()["id"])
        self.assertEqual(row["execution_ids"], [execution])
        self.assertEqual(self.workflow.load(execution)["workflow_state"], "REJECTED")
        self.assertFalse(self.workflow.load(execution)["approved_write"])
        self.assertIn("已决定不做", row["messages"][-1]["content"])

    def test_publication_remains_a_running_turn_until_the_backend_finishes(self):
        core = self.api.core_module()
        entered, finish = threading.Event(), threading.Event()
        original = core.Workflow.advance
        def advance(workflow, execution):
            entered.set()
            finish.wait(5)
            return original(workflow, execution)
        with self.model_reply({"reply": "准备发布。", "objective": "Synthetic slow publication", "publish": True}), \
                patch.object(core.Workflow, "advance", advance), \
                patch.object(core.Workflow, "readiness", return_value={"ready": True, "checks": []}), \
                patch.object(core.workflow_runtime, "dispatch", return_value={"spawned": []}):
            response = self.client.post(self.url + "/architect/messages", json={"message": "发布任务"})
            try:
                self.assertTrue(entered.wait(3))
                row = self.controller.view(self.workflow, response.json()["id"])
                self.assertEqual(row["status"], "running")
                self.assertIsNotNone(row["pending"])
                duplicate = self.client.post(self.url + "/architect/messages", json={"message": "重复发布"})
                self.assertEqual(duplicate.status_code, 409)
            finally:
                finish.set()
                self.wait(response.json()["id"])

    def test_reply_prefix_is_removed_from_json_and_plain_text_without_changing_body(self):
        expected = "需求已整理，可在总控台对话查看任务。"
        for prefix in ("总控台对话：", " 总控台对话: ", "总控台对话 ", "总控台对话：总控台对话："):
            for source in (prefix + expected, json.dumps({"reply": prefix + expected, "objective": None})):
                self.assertEqual(self.controller.decode(source)["reply"], expected)
        self.assertFalse(self.controller.decode('broken {"publish":true')["publish"])

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


    def test_old_conversations_are_readonly_and_architect_creation_is_stable(self):
        row = self.create()
        stored = self.controller.load(self.workflow, row["id"])
        stored.pop("kind")
        self.controller.save(self.workflow, stored)
        response = self.client.post(f"{self.url}/conversations/{row['id']}/messages", json={"message": "继续"})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(self.client.get(f"{self.url}/conversations/{row['id']}").status_code, 200)
        first = self.controller.architect(self.workflow)
        self.assertEqual(first["id"], self.controller.architect(self.workflow)["id"])
        self.assertEqual(first["execution_ids"], [])

    def test_previous_architect_title_changes_on_read_without_renaming_legacy_history(self):
        row = self.controller.architect(self.workflow)
        self.assertEqual(row["title"], "总控台对话")
        old_title = "项目架构师"
        row["title"] = old_title
        self.controller.save(self.workflow, row)
        legacy = self.create()
        legacy.pop("kind", None)
        legacy["title"] = old_title
        self.controller.save(self.workflow, legacy)
        settings = json.loads(self.config.read_text())
        settings["allow_actions"] = False
        self.config.write_text(json.dumps(settings))
        path = self.controller.directory(self.workflow, row["id"]) / "conversation.json"
        before = path.read_bytes()

        timeline = self.client.get(self.url + "/architect").json()
        self.assertEqual(timeline["conversation"]["id"], row["id"])
        self.assertEqual(timeline["conversation"]["title"], "总控台对话")
        self.assertEqual(timeline["conversation"]["execution_ids"], row["execution_ids"])
        titles = {item["id"]: item["title"] for item in self.client.get(self.url + "/conversations").json()["conversations"]}
        self.assertEqual(titles[row["id"]], "总控台对话")
        self.assertEqual(titles[legacy["id"]], old_title)
        self.assertEqual(path.read_bytes(), before)

    def test_highlight_only_refers_to_a_current_card_and_never_approves_work(self):
        row = self.controller.architect(self.workflow)
        selected = {"id": "not-current"}
        class Agent:
            session_id = row["id"]
            def run_conversation(self, *args, **kwargs):
                return {"final_response": json.dumps({"reply": "请在卡片里确认。", "objective": None, "card_id": selected["id"]})}
            def close(self): pass
        with patch.object(self.controller, "make_agent", return_value=Agent()), patch.object(fixtures.runtime, "dispatch") as dispatch:
            self.controller.start(self.workflow, row["id"], "可以", {"cards": [{"card_id": "current-card"}]})
            self.assertNotIn("highlight", self.wait(row["id"]))
            selected["id"] = "current-card"
            self.controller.start(self.workflow, row["id"], "你推荐哪个？", {"cards": [{"card_id": "current-card"}]})
            self.assertEqual(self.wait(row["id"])["highlight"]["card_id"], "current-card")
            dispatch.assert_not_called()

    def test_another_process_owns_a_durable_pending_reply_and_restart_is_detected(self):
        import subprocess
        import sys
        row = self.controller.architect(self.workflow)
        directory = self.controller.directory(self.workflow, row["id"])
        child = subprocess.Popen([sys.executable, "-c",
            "import fcntl,sys; f=open(sys.argv[1],'a'); fcntl.flock(f,fcntl.LOCK_EX); print('ready',flush=True); sys.stdin.read(1)",
            str(directory / "conversation.lock")], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), "ready")
            row["status"] = "running"; self.controller.save(self.workflow, row)
            (directory / "pending.json").write_text(json.dumps({"input": "synthetic question", "text": "partial reply",
                "started_at": time.time(), "pid": child.pid}))
            visible = self.controller.view(self.workflow, row["id"])
            self.assertEqual(visible["status"], "running")
            self.assertEqual(visible["pending"]["text"], "partial reply")
        finally:
            child.communicate("x", timeout=5)
        self.assertEqual(self.controller.view(self.workflow, row["id"])["status"], "interrupted")
        class Agent:
            session_id = row["id"]
            def run_conversation(self, *args, **kwargs):
                return {"final_response": '{"reply":"recovered","objective":null}'}
            def close(self): pass
        with patch.object(self.controller, "make_agent", return_value=Agent()):
            self.controller.start(self.workflow, row["id"], "retry", {})
            self.assertEqual(self.wait(row["id"])["status"], "idle")
        self.assertFalse((directory / "pending.json").exists())


if __name__ == "__main__":
    unittest.main()
