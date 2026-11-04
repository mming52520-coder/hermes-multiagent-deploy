"""Architect projection and consent contracts over the real native fixture."""
import importlib
import json
import threading
import unittest
from unittest.mock import patch

import test_workflow_conversation as conversations
import test_workflow_v2 as v2


class TimelineTest(unittest.TestCase):
    setUp = conversations.ConversationTest.setUp
    wait = conversations.ConversationTest.wait

    def prepare(self):
        module = self.api.timeline_module()
        advisor = importlib.import_module(self.controller.__package__ + ".workflow_advisor")
        scheduled = patch.object(advisor, "schedule")
        scheduled.start(); self.addCleanup(scheduled.stop)
        row = self.controller.architect(self.workflow)
        response = self.client.post(self.url + "/architect/tasks", json={"objective": "Synthetic feature with fixed checks"})
        self.assertEqual(response.status_code, 200, response.text)
        execution = response.json()["execution_id"]
        data = self.client.get(self.url + "/architect").json()
        card = next(item for item in data["items"] if item["type"] == "card")
        return module, advisor, row, execution, card

    def test_readonly_get_does_not_create_an_architect(self):
        result = self.client.get(self.url + "/architect")
        self.assertEqual(result.status_code, 200)
        self.assertIsNone(result.json()["conversation"])
        self.assertEqual(result.json()["pending"], 0)
        self.assertFalse((self.workflow.root / "workflow/conversations").exists())
        settings = json.loads(self.config.read_text()); settings["allow_actions"] = False
        self.config.write_text(json.dumps(settings))
        for path, body in [("/messages", {"message": "hello"}), ("/tasks", {"objective": "task"}),
                           ("/decisions", {"card_id": "x", "action": "approve"})]:
            self.assertEqual(self.client.post(self.url + "/architect" + path, json=body).status_code, 403)

    def test_architect_writes_preserve_origin_source_and_native_capability_gates(self):
        with patch.object(self.controller, "architect") as create:
            denied = self.client.post(self.url + "/architect/messages", json={"message": "hello"},
                                      headers={"Origin": "https://untrusted.example"})
            self.assertEqual(denied.status_code, 403)
            with patch.object(self.api.core_module(), "verify_source", side_effect=ValueError("unsupported Hermes source")):
                self.assertEqual(self.client.post(self.url + "/architect/messages", json={"message": "hello"}).status_code, 409)
            with patch.object(self.api.importlib.util, "find_spec", return_value=None):
                self.assertEqual(self.client.post(self.url + "/architect/messages", json={"message": "hello"}).status_code, 409)
            create.assert_not_called()

    def test_webhook_link_preserves_the_card_and_execution_without_external_io(self):
        from urllib.parse import urlsplit, parse_qs
        notify = importlib.import_module(self.controller.__package__ + ".workflow_notify")
        link = notify.dashboard_link({"WORKFLOW_DASHBOARD_URL": "http://localhost:9119/"}, "a" * 32, "b" * 16)
        self.assertEqual(parse_qs(urlsplit(link).query), {"card": ["b" * 16], "execution": ["a" * 32]})

    def test_existing_modern_tasks_join_the_architect_without_rewriting_old_conversations(self):
        old = self.workflow.submit("Existing synthetic v2 task")
        legacy = self.controller.create(self.workflow)
        before = self.controller.load(self.workflow, legacy["id"])
        row = self.controller.architect(self.workflow)
        self.assertIn(old["execution_id"], row["execution_ids"])
        self.assertEqual(self.controller.load(self.workflow, legacy["id"]), before)
        self.assertFalse(self.workflow.load(old["execution_id"])["approved_write"])
        later = self.workflow.submit("A later task submitted through the existing entry")
        self.assertIn(later["execution_id"], self.controller.architect(self.workflow)["execution_ids"])

    def test_two_tasks_share_one_architect_and_remain_unapproved(self):
        _, _, row, first, _ = self.prepare()
        self.assertEqual(row["id"], self.controller.architect(self.workflow)["id"])
        result = self.client.post(self.url + "/architect/tasks", json={"objective": "A separate synthetic task"})
        self.assertEqual(result.status_code, 200, result.text)
        second = result.json()["execution_id"]
        self.assertNotEqual(first, second)
        current = self.controller.load(self.workflow, row["id"])
        self.assertEqual(current["execution_ids"], [first, second])
        for execution in current["execution_ids"]:
            self.assertFalse(self.workflow.load(execution)["approved_write"])
        self.assertEqual(self.client.get(self.url + "/architect").json()["pending"], 2)
        repeated = self.client.post(self.url + "/architect/tasks", json={"objective": "A separate synthetic task"})
        self.assertEqual(repeated.json()["execution_id"], second)
        self.assertEqual(len(self.controller.load(self.workflow, row["id"])["execution_ids"]), 2)

    def test_decision_resolves_in_place_and_old_card_cannot_be_reused(self):
        module, _, _, execution, card = self.prepare()
        response = self.client.post(self.url + "/architect/decisions",
            json={"card_id": card["card_id"], "action": "reject", "reason": "Do not pursue this scope"})
        self.assertEqual(response.status_code, 200, response.text)
        manifest = self.workflow.load(execution)
        self.assertEqual(manifest["workflow_state"], "REJECTED")
        resolved = module.resolved_cards(manifest)[0]
        self.assertEqual(resolved["card_id"], card["card_id"])
        self.assertEqual(resolved["at"], card["at"])
        self.assertEqual(resolved["resolved"]["by"], "web")
        self.assertEqual(resolved["resolved"]["action"], "reject")
        again = self.client.post(self.url + "/architect/decisions",
            json={"card_id": card["card_id"], "action": "approve"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(len(self.workflow.load(execution)["decisions_log"]), 1)
        items = self.client.get(self.url + "/architect").json()["items"]
        self.assertEqual(len([item for item in items if item["type"] == "card"]), 1)

    def test_card_capabilities_reasons_and_schema_are_checked_before_perform(self):
        _, _, _, execution, card = self.prepare()
        with patch.object(self.api, "perform") as perform:
            for body in [{"card_id": card["card_id"], "action": "accept"},
                         {"card_id": card["card_id"], "action": "reject", "reason": " "},
                         {"card_id": "expired", "action": "approve"}]:
                self.assertEqual(self.client.post(self.url + "/architect/decisions", json=body).status_code, 409)
            self.assertEqual(self.client.post(self.url + "/architect/decisions",
                json={"card_id": card["card_id"], "action": "approve", "round_number": 7}).status_code, 422)
            perform.assert_not_called()
        self.assertFalse(self.workflow.load(execution)["approved_write"])

    def test_ordinary_agreement_only_reaches_the_architect(self):
        _, _, row, execution, card = self.prepare()
        before = self.workflow.load(execution)
        with patch.object(self.controller, "start", return_value={"status": "running"}) as start, patch.object(self.api, "perform") as perform:
            response = self.client.post(self.url + "/architect/messages", json={"message": "可以，接受"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(start.call_args.args[1], row["id"])
        self.assertEqual(start.call_args.args[-1]["cards"][0]["card_id"], card["card_id"])
        perform.assert_not_called()
        self.assertEqual(self.workflow.load(execution), before)

    def test_round_is_rechecked_inside_native_rejection_after_card_validation(self):
        _, _, _, execution, card = self.prepare()
        native = self.api.core_module().Workflow
        original = native.reject
        def changed(workflow, target, reason, **kwargs):
            manifest = workflow.load(target)
            manifest["rounds"].append({**manifest["rounds"][-1], "number": 1})
            workflow.save(manifest)
            return original(workflow, target, reason, **kwargs)
        with patch.object(native, "reject", changed):
            response = self.client.post(self.url + "/architect/decisions",
                json={"card_id": card["card_id"], "action": "reject", "reason": "original scope only"})
        self.assertEqual(response.status_code, 409, response.text)
        self.assertEqual(self.workflow.load(execution)["workflow_state"], "WAITING_APPROVAL")
        self.assertEqual(self.workflow.load(execution).get("decisions_log", []), [])

    def test_pending_claim_prevents_simultaneous_decisions_without_holding_the_execution_lock(self):
        _, _, _, execution, card = self.prepare()
        entered, release = threading.Event(), threading.Event()
        responses = []
        def apply(*args, **kwargs):
            with self.workflow.locked(execution):
                entered.set()
            release.wait(4)
            return {"completed": True}
        body = {"card_id": card["card_id"], "action": "approve"}
        with patch.object(self.api, "perform", side_effect=apply) as perform:
            worker = threading.Thread(target=lambda: responses.append(self.client.post(self.url + "/architect/decisions", json=body)))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                second = self.client.post(self.url + "/architect/decisions", json=body)
                self.assertEqual(second.status_code, 409)
                self.assertIn("正在处理", second.text)
            finally:
                release.set(); worker.join(5)
            self.assertEqual(responses[0].status_code, 200, responses[0].text)
            self.assertEqual(perform.call_count, 1)
        self.assertNotIn("decision_claim", self.workflow.load(execution))

    def test_exhausted_repairs_and_native_failed_runs_produce_only_valid_actions(self):
        module, _, _, execution, _ = self.prepare()
        manifest = self.workflow.load(execution)
        manifest["workflow_state"] = "REPAIR_REQUIRED"
        manifest["budget"]["max_rounds"] = 0
        self.assertEqual(module.card_for(manifest, {})["actions"], ["reject"])
        manifest["workflow_state"] = "HUMAN_REQUIRED"
        card = module.card_for(manifest, {"builder": {"status": "blocked", "outcome": "crashed", "run_id": 12}})
        self.assertIn("retry-worker", card["actions"])
        self.assertEqual(card["retry"], {"role": "builder", "run_id": 12})
        manifest["workflow_state"] = "RUNNING_RESEARCH"
        self.assertIsNone(module.card_for(manifest, {}))

    def test_advice_uses_an_independent_session_and_is_cached(self):
        _, advisor, row, execution, _ = self.prepare()
        sessions = []
        class Agent:
            def run_conversation(self, *args, **kwargs):
                return {"final_response": '{"reply":"建议先检查边界，再确认范围。","objective":null}'}
            def close(self): pass
        def factory(workflow, record, db):
            sessions.append(record["session_id"])
            self.assertIsNone(db)
            self.assertNotEqual(record["session_id"], row["session_id"])
            return Agent()
        with patch.object(self.controller, "make_agent", side_effect=factory) as make:
            self.assertEqual(advisor.advise(self.workflow, execution)["source"], "model")
            advisor.advise(self.workflow, execution)
            self.assertEqual(make.call_count, 1)
        self.assertEqual(self.controller.view(self.workflow, row["id"])["messages"], [])

    def test_model_failure_falls_back_and_a_changed_state_discards_model_advice(self):
        _, advisor, _, execution, _ = self.prepare()
        with patch.object(self.controller, "make_agent", side_effect=ValueError("synthetic provider unavailable")):
            result = advisor.advise(self.workflow, execution)
        self.assertEqual(result["source"], "rule")
        manifest = self.workflow.load(execution); manifest.pop("advice")
        self.workflow.save(manifest)
        class Agent:
            def run_conversation(_self, *args, **kwargs):
                current = self.workflow.load(execution); current["workflow_state"] = "REJECTED"
                self.workflow.save(current)
                return {"final_response": '{"reply":"outdated recommendation","objective":null}'}
            def close(self): pass
        with patch.object(self.controller, "make_agent", return_value=Agent()):
            self.assertEqual(advisor.advise(self.workflow, execution)["source"], "rule")
        self.assertNotIn("advice", self.workflow.load(execution))

    def test_current_revision_reaches_advice_and_architect_conversation(self):
        _, advisor, row, execution, _ = self.prepare()
        manifest = self.workflow.load(execution)
        request = {"kind": "implementation", "reason": "Add the parser required in this round", "requested_by": "customer"}
        manifest["rounds"].append({**manifest["rounds"][-1], "number": 1})
        manifest["failures"].append(request)
        self.workflow.save(manifest)
        contexts = []
        class Agent:
            def run_conversation(self, text, **kwargs):
                contexts.append(json.loads(text))
                return {"final_response": '{"reply":"按本轮修改意见核对解析功能。","objective":null}'}
            def close(self): pass
        with patch.object(self.controller, "make_agent", return_value=Agent()):
            self.assertEqual(advisor.advise(self.workflow, execution)["source"], "model")
        self.assertEqual(contexts[0]["current_request"], request)
        with patch.object(self.controller, "start", return_value={"status": "running"}) as start:
            result = self.client.post(self.url + "/architect/messages", json={"message": "本轮需要验收什么？"})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(start.call_args.args[-1]["tasks"][0]["current_request"], request)
        self.assertEqual(self.workflow.load(execution)["workflow_state"], "WAITING_APPROVAL")
        self.assertFalse(self.workflow.load(execution)["approved_write"])


    def test_recommendation_timeout_returns_rules_and_interrupts_its_own_agent(self):
        _, advisor, _, execution, _ = self.prepare()
        stopped, closed = threading.Event(), threading.Event()
        class Agent:
            def run_conversation(self, *args, **kwargs):
                stopped.wait(2)
                return {"final_response": '{"reply":"late reply","objective":null}'}
            def interrupt(self, *args, **kwargs): stopped.set()
            def close(self): closed.set()
        with patch.object(advisor, "TIMEOUT", .01), patch.object(self.controller, "make_agent", return_value=Agent()):
            self.assertEqual(advisor.advise(self.workflow, execution)["source"], "rule")
        self.assertTrue(closed.wait(2))

    def test_update_helper_backs_up_private_config_and_keeps_model_values_out_of_output(self):
        import os
        import subprocess
        from pathlib import Path
        source = Path(__file__).resolve().parents[1]
        before = self.config.read_bytes()
        self.env.write_text(self.env.read_text() + "\nSYNTHETIC_API_KEY=synthetic-key\n")
        result = subprocess.run(["bash", str(source / "update-workflow-plugin.sh")],
            env={**os.environ, "HERMES_HOME": str(self.workflow.root)}, capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_bytes(), before)
        backups = list((self.workflow.root / "backups").glob("workflow-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "workflow-app.env").stat().st_mode & 0o777, 0o600)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o700)
        self.assertNotIn("synthetic-key", result.stdout + result.stderr)
        for name in ("workflow_timeline.py", "workflow_advisor.py", "workflow_feishu.py"):
            self.assertTrue((self.config.parent / "operator" / name).is_file())

    def test_progress_keeps_platform_failures_and_policy_acceptance_distinct(self):
        module, _, _, execution, _ = self.prepare()
        manifest = self.workflow.load(execution)
        manifest["transitions"] = [{"to": "REPAIR_REQUIRED", "from": "VERIFYING", "round": 0, "at": 10, "verification": "FAIL"},
                                   {"to": "ACCEPTED", "from": "RUNNING_REVIEW", "round": 1, "at": 20}]
        manifest["accepted_by"] = "policy"
        entries = module.progress(manifest)
        self.assertIn("平台测试未通过", entries[0]["text"])
        self.assertEqual(entries[0]["label"], "平台测试未通过")
        self.assertEqual(entries[0]["objective"], manifest["objective"].splitlines()[0])
        self.assertIn("授权范围内自动验收", entries[1]["text"])
