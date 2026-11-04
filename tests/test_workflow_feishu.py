"""Offline Feishu contracts. Real workflow gates and card receipts, simulated HTTP/Gateway."""

import asyncio
from dataclasses import dataclass
from io import BytesIO, StringIO
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import AsyncMock, Mock, patch
from urllib.error import HTTPError

import test_workflow_conversation as conversations
import test_workflow_v2 as v2
import configure_feishu_bridge as setup_bridge
import workflow_feishu_client as rest


class Transport:
    def __init__(self):
        self.calls = []
        self.counter = 0
        self.lock = threading.Lock()
        self.down = False

    def __call__(self, req, timeout):
        if self.down:
            raise OSError("synthetic disconnect")
        with self.lock:
            payload = json.loads(req.data)
            self.calls.append((req.method, req.full_url, payload))
            if "/auth/v3/" in req.full_url:
                result = {"code": 0, "tenant_access_token": "synthetic-token", "expire": 1000}
            else:
                assert req.get_header("Authorization") == "Bearer synthetic-token"
                self.counter += 1
                result = {"code": 0, "data": {"message_id": f"om_synthetic_{self.counter}"}}
        return BytesIO(json.dumps(result).encode())

    def texts(self):
        return [
            (url, json.loads(data["content"])["text"])
            for _, url, data in list(self.calls)
            if data.get("msg_type") == "text"
        ]

    def patches(self, message_id):
        return [
            json.loads(data["content"])
            for method, url, data in list(self.calls)
            if method == "PATCH" and url.endswith("/" + message_id)
        ]


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.http = Transport()
        self.client = rest.FeishuClient("cli_unit", "synthetic-secret", opener=self.http)
        self.addCleanup(rest._tokens.clear)
        rest._tokens.clear()

    def test_allowlisted_hosts_escaped_ids_and_no_bearer_redirects(self):
        from urllib.request import Request

        for domain in ("https://untrusted.example", "open.feishu.cn.untrusted.example", "http://open.feishu.cn"):
            with self.assertRaises(ValueError):
                rest.FeishuClient("cli_unit", "synthetic-secret", domain)
        self.client.patch_card("om_/bad?host=untrusted.example", {"schema": "2.0"})
        self.assertEqual(
            self.http.calls[-1][1],
            "https://open.feishu.cn/open-apis/im/v1/messages/om_%2Fbad%3Fhost%3Duntrusted.example",
        )
        req = Request("https://open.feishu.cn/open-apis/im/v1/messages", headers={"Authorization": "Bearer test"})
        self.assertIsNone(
            rest._NoRedirect().redirect_request(req, None, 302, "", {}, "https://untrusted.example/")
        )
        lark = rest.FeishuClient("cli_unit", "synthetic-secret", "lark", opener=self.http)
        lark.send_text("oc_group", "hello", reply_to="om_parent")
        self.assertEqual(
            self.http.calls[-1][1], "https://open.larksuite.com/open-apis/im/v1/messages/om_parent/reply"
        )

    def test_token_cache_renews_five_minutes_before_expiry_and_is_app_scoped(self):
        with patch.object(rest.time, "monotonic", return_value=100):
            self.client.send_card("oc_group", {"schema": "2.0"}, delivery_id="dedup-id")
            copy = rest.FeishuClient("cli_unit", "synthetic-secret", opener=self.http)
            copy.tenant_token()
        self.assertEqual(len([c for c in self.http.calls if "/auth/" in c[1]]), 1)
        self.assertEqual(
            self.http.calls[1][2],
            {
                "receive_id": "oc_group",
                "msg_type": "interactive",
                "content": '{"schema": "2.0"}',
                "uuid": "dedup-id",
            },
        )
        with patch.object(rest.time, "monotonic", return_value=800):
            self.client.tenant_token()
            rest.FeishuClient("cli_other", "synthetic-secret", opener=self.http).tenant_token()
        self.assertEqual(len([c for c in self.http.calls if "/auth/" in c[1]]), 3)

    def test_credentials_are_loaded_from_the_bound_native_home(self):
        from agent.secret_scope import load_env_file as read_native_env

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = """synthetic' "\\ secret"""
            native = setup_bridge.updated(
                "", {"FEISHU_APP_ID": "cli_local", "FEISHU_APP_SECRET": secret, "FEISHU_DOMAIN": "lark"}
            )
            (root / ".env").write_text(native)
            self.assertEqual(read_native_env(root / ".env")["FEISHU_APP_SECRET"], secret)
            workflow = NS(
                root=root, env={"WORKFLOW_FEISHU_CHAT_ID": "oc_group", "FEISHU_APP_SECRET": "wrong-binding-secret"}
            )
            with patch.dict(
                "os.environ", {"FEISHU_APP_ID": "cli_foreign", "FEISHU_APP_SECRET": "wrong-process-secret"}
            ):
                client = rest.client_for(workflow)
                client.opener = self.http
                client.tenant_token()
            self.assertEqual(self.http.calls[-1][2], {"app_id": "cli_local", "app_secret": secret})
            self.assertTrue(self.http.calls[-1][1].startswith("https://open.larksuite.com/"))

    def test_multiplex_publisher_defaults_domain_without_borrowing_another_profile(self):
        from agent.secret_scope import (
            current_secret_scope,
            reset_multiplex_context,
            reset_secret_scope,
            set_multiplex_context,
            set_secret_scope,
        )

        foreign = {"FEISHU_APP_ID": "cli_foreign", "FEISHU_APP_SECRET": "foreign-secret", "FEISHU_DOMAIN": "lark"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text("FEISHU_APP_ID=cli_bound\nFEISHU_APP_SECRET=bound-secret\n")
            workflow = NS(root=root, env={"WORKFLOW_FEISHU_CHAT_ID": "oc_group"})
            multiplex = set_multiplex_context(True)
            try:
                with patch.dict("os.environ", foreign):
                    for scope in (None, foreign):
                        with self.subTest(scope="unscoped" if scope is None else "foreign"):
                            token = set_secret_scope(scope)
                            try:
                                rest._tokens.clear()
                                client = rest.client_for(workflow)
                                client.opener = self.http
                                self.assertTrue(client.send_text("oc_group", "test"))
                                self.assertEqual(client.host, "open.feishu.cn")
                                auth = [call for call in self.http.calls if "/auth/v3/" in call[1]][-1]
                                self.assertEqual(auth[2], {"app_id": "cli_bound", "app_secret": "bound-secret"})
                                self.assertIsNone(rest.client_for(NS(root=root / "empty", env=workflow.env)))
                                self.assertIs(current_secret_scope(), scope)
                            finally:
                                reset_secret_scope(token)
            finally:
                reset_multiplex_context(multiplex)

    def test_api_error_does_not_log_credentials_or_remote_response(self):
        def bad(req, **kwargs):
            return BytesIO(b'{"code":1234,"msg":"synthetic-secret"}')

        self.client.opener = bad
        with self.assertLogs(level="WARNING") as logs:
            self.assertFalse(self.client.send_text("oc_group", "example"))
        self.assertIn("1234", str(logs.output))
        self.assertNotIn("synthetic-secret", str(logs.output))

        def bad_gateway(req, **kwargs):
            raise HTTPError(req.full_url, 502, "Bad Gateway", {}, BytesIO(b"synthetic HTML"))

        self.client.opener = bad_gateway
        with self.assertLogs(level="WARNING") as logs:
            self.assertFalse(self.client.send_text("oc_group", "example"))
        self.assertIn("502", str(logs.output))
        self.assertIsNone(self.client.last_error_code)


class ConfigTest(unittest.TestCase):
    def test_backup_modes_native_allowlist_and_blank_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugins/workflow"
            plugin.mkdir(parents=True)
            binding = root / "workflow.env"
            native = root / ".env"
            native.write_text("# preserve\nOTHER=kept\nFEISHU_ALLOWED_USERS=ou_existing\n")
            binding.write_text("PROJECT_DIR=/synthetic\nBOARD_SLUG=default\n")
            original = binding.read_bytes(), native.read_bytes()
            (plugin / "config.json").write_text(json.dumps({"hermes_home": str(root), "env_file": str(binding)}))
            answers = iter(["cli_test", "oc_group", "ou_admin", "", ""])
            with patch("sys.stdout", new_callable=StringIO) as stdout:
                backup = setup_bridge.configure(root, lambda _: next(answers), lambda _: "synthetic-secret")
            self.assertNotIn("synthetic-secret", stdout.getvalue())
            self.assertNotIn("synthetic-secret", binding.read_text())
            self.assertIn("# preserve\nOTHER=kept\n", native.read_text())
            self.assertEqual(
                setup_bridge.values(native.read_text())["FEISHU_ALLOWED_USERS"], "ou_existing,ou_admin"
            )
            self.assertEqual(setup_bridge.values(native.read_text())["FEISHU_CONNECTION_MODE"], "websocket")
            self.assertEqual(setup_bridge.values(binding.read_text())["WORKFLOW_FEISHU_MEMBERS"], "")
            self.assertEqual((backup / "workflow-app.env").read_bytes(), original[0])
            self.assertEqual((backup / "hermes.env").read_bytes(), original[1])
            self.assertEqual(backup.stat().st_mode & 0o777, 0o700)
            for path in (binding, native, backup / "hermes.env", backup / "workflow-app.env"):
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            # An invalid approver is rejected before either file is changed.
            before = binding.read_bytes(), native.read_bytes()
            answers = iter(["", "", "*"])
            with self.assertRaises(ValueError):
                setup_bridge.configure(root, lambda _: next(answers), lambda _: "")
            self.assertEqual(before, (binding.read_bytes(), native.read_bytes()))


@dataclass
class Source:
    chat_id: str = "oc_group"
    user_id: str = "ou_admin"
    user_name: str = "测试审批人"
    platform: str = "feishu"
    is_bot: bool = False


def event(
    kind="im.message.receive_v1",
    *,
    actor="ou_admin",
    chat="oc_group",
    text="讨论需求",
    value=None,
    reason=None,
    message="om_parent",
    primary=None,
):
    source = Source(chat_id=chat, user_id=primary or actor)
    if kind == "card.action.trigger":
        raw = NS(
            operator=NS(open_id=actor),
            context=NS(open_chat_id=chat, open_message_id=message),
            action=NS(tag="button", value=value, form_value={"reason": reason} if reason is not None else {}),
        )
        text = "/card button " + json.dumps(value, ensure_ascii=False)
    else:
        raw = NS(sender=NS(sender_type="user", sender_id=NS(open_id=actor)), message=NS(chat_id=chat))
    envelope = NS(header=NS(app_id="cli_bridge", event_type=kind), event=raw)
    return NS(source=source, raw_message=envelope, text=text)


class BridgeTest(unittest.TestCase):
    def setUp(self):
        conversations.ConversationTest.setUp(self)
        self.env.write_text(
            self.env.read_text() + "WORKFLOW_FEISHU_CHAT_ID=oc_group\n"
            "WORKFLOW_FEISHU_APPROVERS=ou_admin\nWORKFLOW_FEISHU_MEMBERS=ou_member,ou_admin\n"
            "WORKFLOW_DASHBOARD_URL=http://localhost:9119\n"
        )
        self.workflow = self.api.bound_workflow(json.loads(self.config.read_text()))
        self.bridge = self.api.core_module().workflow_feishu
        self.http = Transport()
        self.app = rest.FeishuClient("cli_bridge", "synthetic-secret", opener=self.http)
        self.addCleanup(rest._tokens.clear)
        client = patch.object(self.bridge, "client_for", return_value=self.app)
        client.start()
        self.addCleanup(client.stop)
        self.referenced = None

        def factory(wf, row, db):
            class Agent:
                session_id = row["session_id"]

                def run_conversation(agent, *args, **kwargs):
                    response = json.dumps(
                        {"reply": "建议核对证据。", "objective": None, "card_id": self.referenced}
                    )
                    if db is not None:
                        db.append_message(
                            agent.session_id,
                            "user",
                            content=kwargs["persist_user_message"],
                            display_metadata=kwargs["persist_user_display_metadata"],
                        )
                        db.append_message(agent.session_id, "assistant", content=response)
                    return {"final_response": response}

                def close(agent):
                    pass

            return Agent()

        fake = patch.object(self.controller, "make_agent", side_effect=factory)
        self.make = fake.start()
        self.addCleanup(fake.stop)
        root = self.config.parent
        name = "workflow_feishu_test_" + self.fixture.execution
        spec = importlib.util.spec_from_file_location(
            name, root / "__init__.py", submodule_search_locations=[str(root)]
        )
        package = importlib.util.module_from_spec(spec)
        sys.modules[name] = package
        spec.loader.exec_module(package)
        self.package = package
        self.addCleanup(
            lambda: [
                sys.modules.pop(key, None)
                for key in tuple(sys.modules)
                if key == name or key.startswith(name + ".")
            ]
        )
        hooks = {}
        package.register(NS(register_hook=lambda name, fn: hooks.update({name: fn})))
        self.hook = hooks["pre_gateway_dispatch"]
        self.gateway_api = importlib.import_module(name + ".feishu_gateway").api
        self.gateway = NS(
            _is_user_authorized_for_source=Mock(return_value=True), _hm_estop_gate=Mock(return_value=None)
        )
        self.jobs = []
        self.addCleanup(
            lambda: [
                self.wait_for(lambda: not self.workflow.load(e).get("feishu_sync", {}).get("pid"))
                for e in self.jobs
            ]
        )

    def wait_for(self, check, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = check()
            if result:
                return result
            time.sleep(0.015)
        self.fail("Expected the offline workflow event before the deadline")

    def handle(self, e):
        return asyncio.run(self.hook(event=e, gateway=self.gateway))

    def task(self):
        response = self.client.post(
            self.url + "/architect/tasks", json={"objective": "Synthetic dual-channel delivery"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        execution = response.json()["execution_id"]
        self.jobs.append(execution)
        self.wait_for(lambda: self.workflow.load(execution).get("feishu_cards"))
        self.settled(execution)
        return execution

    def settled(self, execution):
        self.wait_for(lambda: not self.workflow.load(execution).get("feishu_sync", {}).get("pid"))

    def click(self, execution, action, *, actor="ou_admin", reason=None, card_id=None, message=None):
        manifest = self.workflow.load(execution)
        if card_id is None:
            card_id = self.api.timeline_module().card_for(manifest, {})["card_id"]
        ref = manifest["feishu_cards"][card_id]
        value = {"workflow_card": card_id, "workflow_action": action, "execution": execution}
        return self.handle(
            event(
                "card.action.trigger",
                actor=actor,
                value=value,
                reason=reason,
                message=message or ref["message_id"],
            )
        )

    def test_pinned_adapter_routes_a_real_synthetic_command_through_the_registered_native_hook(self):
        from gateway.config import PlatformConfig
        from gateway.run_inbound_hooks import GatewayInboundHooksMixin
        from hermes_cli import plugins as host
        from plugins.platforms.feishu.adapter import FeishuAdapter
        from gateway.platforms.event import MessageType

        execution = self.task()
        card_id, ref = next(iter(self.workflow.load(execution)["feishu_cards"].items()))
        envelope = event(
            "card.action.trigger",
            message=ref["message_id"],
            reason="已改变范围",
            value={"workflow_card": card_id, "workflow_action": "reject", "execution": execution},
        ).raw_message
        envelope.event.token = "synthetic-callback-token"
        manager = host.PluginManager()
        self.package.register(host.PluginContext(host.PluginManifest(name="workflow"), manager))
        runner = GatewayInboundHooksMixin()
        runner._is_user_authorized_for_source = self.gateway._is_user_authorized_for_source
        runner._hm_estop_gate = self.gateway._hm_estop_gate

        async def route():
            complete = asyncio.Event()
            observed = []
            adapter = FeishuAdapter(PlatformConfig(enabled=True))

            async def handler(e):
                observed.append((e.message_type, e.source.user_id, e.raw_message is envelope))
                consumed = await runner._hm_pre_gateway_dispatch_hook(e, e.source)
                observed.append(consumed)
                complete.set()
                return None

            adapter.set_message_handler(handler)
            with (
                patch.object(host, "_delivery_manager", return_value=manager),
                patch.object(
                    adapter, "get_chat_info", new=AsyncMock(return_value={"name": "测试群", "type": "group"})
                ),
                patch.object(adapter, "_resolve_sender_name_from_api", new=AsyncMock(return_value="测试审批人")),
                patch.object(adapter, "on_processing_start", new=AsyncMock()),
                patch.object(adapter, "on_processing_complete", new=AsyncMock()),
                patch.object(adapter, "send_typing", new=AsyncMock()),
            ):
                await adapter._handle_card_action_event(envelope)
                await asyncio.wait_for(complete.wait(), timeout=6)
                await adapter._handle_card_action_event(envelope)
            return observed

        observed = asyncio.run(route())
        self.assertEqual(observed, [(MessageType.COMMAND, "ou_admin", True), None])
        self.assertEqual(len(self.workflow.load(execution)["decisions_log"]), 1)
        self.assertEqual(self.workflow.load(execution)["workflow_state"], "REJECTED")

    def test_web_and_feishu_contend_for_one_decision_claim(self):
        execution = self.task()
        card_id = next(iter(self.workflow.load(execution)["feishu_cards"]))
        entered, release = threading.Event(), threading.Event()
        original = self.gateway_api.perform

        def hold(*args, **kwargs):
            entered.set()
            release.wait(6)
            return original(*args, **kwargs)

        with patch.object(self.gateway_api, "perform", side_effect=hold):
            t = threading.Thread(target=self.click, args=(execution, "reject"), kwargs={"reason": "范围变化"})
            t.start()
            try:
                self.assertTrue(entered.wait(4))
                response = self.client.post(
                    self.url + "/architect/decisions", json={"card_id": card_id, "action": "approve"}
                )
                self.assertEqual(response.status_code, 409)
                self.assertIn("正在处理", response.text)
            finally:
                release.set()
                t.join(6)
        self.settled(execution)
        log = self.workflow.load(execution)["decisions_log"]
        self.assertEqual(
            [(r["action"], r["by"], r["reason"]) for r in log], [("reject", "feishu:ou_admin", "范围变化")]
        )

    def test_partial_delivery_recovers_after_retry_without_duplicating_progress(self):
        failed = []

        def interrupted(req, **kwargs):
            body = json.loads(req.data)
            if (
                body.get("msg_type") == "interactive"
                and json.loads(body["content"])["header"]["template"] == "orange"
            ):
                failed.append(body["uuid"])
                raise OSError("offline card send")
            return self.http(req, **kwargs)

        self.app.opener = interrupted
        response = self.client.post(self.url + "/architect/tasks", json={"objective": "Synthetic recovery"})
        self.assertEqual(response.status_code, 200, response.text)
        execution = response.json()["execution_id"]
        self.jobs.append(execution)
        self.wait_for(lambda: self.workflow.load(execution).get("feishu_sync", {}).get("retry_after"))
        record = self.workflow.load(execution)
        self.assertTrue(record["feishu_progress"]["message_id"])
        self.assertFalse(record.get("feishu_cards"))
        self.app.opener = self.http
        # A dead publisher left its PID on disk. The next owner tick picks up persisted state.
        import subprocess

        exited = subprocess.Popen([sys.executable, "-c", "pass"])
        exited.wait()
        with self.workflow.locked(execution):
            current = self.workflow.load(execution)
            current["feishu_sync"].update(pid=exited.pid, retry_after=0)
            self.workflow.save(current)
        self.package._advance_pending("default")
        self.wait_for(lambda: self.workflow.load(execution).get("feishu_cards"))
        self.settled(execution)
        sent = [b for _, _, b in self.http.calls if b.get("msg_type") == "interactive"]
        self.assertEqual(len(sent), 2)
        self.assertEqual(sent[-1]["uuid"], failed[0])
        self.assertEqual(self.workflow.load(execution)["feishu_progress"], record["feishu_progress"])

    def test_feishu_patch_age_limit_is_recorded_without_reposting_a_progress_message(self):
        execution = self.task()
        before = self.workflow.load(execution)
        delivered = before["feishu_progress"]

        def closed(req, **kwargs):
            if req.method == "PATCH" and req.full_url.endswith("/" + delivered["message_id"]):
                body = BytesIO(b'{"code":230031,"msg":"older than 14 days"}')
                raise HTTPError(req.full_url, 400, "Bad Request", {}, body)
            return self.http(req, **kwargs)

        self.app.opener = closed
        self.click(execution, "reject", reason="结束测试")
        self.settled(execution)
        current = self.workflow.load(execution)
        self.assertEqual(current["feishu_progress"]["patch_closed"], 230031)
        self.assertEqual(current["feishu_progress"]["digest"], delivered["digest"])
        self.assertEqual(current["workflow_state"], "REJECTED")
        self.assertEqual(len([c for c in self.http.calls if c[2].get("msg_type") == "interactive"]), 2)

    def test_optional_probe_validates_actual_message_and_acknowledges_without_a_model_or_decision(self):
        root = self.workflow.root
        (root / ".env").write_text("FEISHU_APP_ID=cli_bridge\nFEISHU_APP_SECRET=synthetic-secret\n")
        self.assertTrue(setup_bridge.send_probe(root, opener=self.http))
        receipt = json.loads((root / "workflow/feishu-probe.json").read_text())
        value = {"workflow_probe": receipt["probe_id"]}
        self.handle(event("card.action.trigger", value=value, message="om_other"))
        self.assertFalse(self.http.texts())
        self.handle(event("card.action.trigger", value=value, message=receipt["message_id"]))
        self.assertEqual(self.http.texts()[-1][1], "联动正常")
        self.make.assert_not_called()
        self.assertIsNone(self.controller.architect(self.workflow, create_missing=False))

    def test_unbound_group_is_untouched_and_nonmembers_do_not_start_a_model(self):
        self.assertIsNone(self.handle(event(chat="oc_elsewhere")))
        self.assertEqual(self.handle(event(actor="ou_stranger")), {"action": "skip"})
        self.make.assert_not_called()
        self.assertEqual(self.http.calls, [])

    def test_nonapprover_and_typed_card_command_cannot_authorize(self):
        e = self.task()
        self.assertEqual(self.click(e, "approve", actor="ou_member"), {"action": "skip"})
        self.assertIn("你没有审批权限。", [t for _, t in self.http.texts()])
        self.handle(event(text='/card button {"workflow_action":"approve"}'))
        self.assertFalse(self.workflow.load(e)["approved_write"])
        self.assertEqual(self.workflow.load(e).get("decisions_log", []), [])

    def test_empty_members_default_to_approvers_even_with_foreign_ambient_binding(self):
        self.env.write_text(
            self.env.read_text().replace("WORKFLOW_FEISHU_MEMBERS=ou_member,ou_admin", "WORKFLOW_FEISHU_MEMBERS=")
        )
        with patch.dict(
            "os.environ", {"WORKFLOW_FEISHU_MEMBERS": "ou_stranger", "WORKFLOW_FEISHU_CHAT_ID": "oc_elsewhere"}
        ):
            self.assertEqual(self.handle(event(actor="ou_stranger")), {"action": "skip"})
        self.make.assert_not_called()

    def test_shared_thread_batches_do_not_attribute_other_members_text_to_first_sender(self):
        e = event(actor="ou_member", text="第一条\n合并的另一条")
        e.raw_message.event.message.message_id = "om_first"
        e.message_id = "om_last"
        e.source.thread_id = "topic"
        adapter = NS(config=NS(extra={"group_sessions_per_user": True, "thread_sessions_per_user": False}))
        self.gateway._adapter_for_source = lambda source: adapter
        self.handle(e)
        self.make.assert_not_called()
        self.assertTrue(any("合并" in text for _, text in self.http.texts()))

    def test_native_auth_pause_and_readonly_settings_are_enforced(self):
        self.gateway._is_user_authorized_for_source.return_value = False
        self.assertEqual(self.handle(event()), {"action": "skip"})
        self.gateway._is_user_authorized_for_source.return_value = True
        self.gateway._hm_estop_gate.return_value = "暂停"
        self.handle(event())
        self.assertIn("暂停", [t for _, t in self.http.texts()])
        settings = json.loads(self.config.read_text())
        settings["allow_actions"] = False
        self.config.write_text(json.dumps(settings))
        self.handle(event())
        self.make.assert_not_called()

    def test_card_forms_use_verified_reason_and_message_binding(self):
        e = self.task()
        sent = [
            json.loads(body["content"])
            for method, _, body in self.http.calls
            if body.get("msg_type") == "interactive"
        ]
        card = next(item for item in sent if item["header"]["title"]["content"] == "等待确认需求")
        self.assertTrue(card["config"]["update_multi"])
        form = next(el for el in card["body"]["elements"] if el.get("name") == "change_reason")
        self.assertEqual(form["elements"][0]["name"], "reason")
        self.assertEqual(form["elements"][-1]["form_action_type"], "submit")
        self.assertIn("?card=", card["body"]["elements"][-1]["behaviors"][0]["default_url"])
        self.click(e, "reject", reason=" ")
        self.click(e, "reject", reason="forged message", message="om_unrelated")
        self.assertEqual(self.workflow.load(e)["workflow_state"], "WAITING_APPROVAL")
        self.assertIn("请填写原因或修改意见。", [t for _, t in self.http.texts()])

    def test_superseded_card_rejects_click_and_patches_the_actual_old_message(self):
        e = self.task()
        m = self.workflow.load(e)
        card_id, ref = next(iter(m["feishu_cards"].items()))
        self.workflow.reject(e, "synthetic operator decision through the CLI")
        self.click(e, "approve", card_id=card_id)
        self.settled(e)
        self.assertTrue(any("过期" in text for _, text in self.http.texts()))
        expired = self.http.patches(ref["message_id"])[-1]
        self.assertEqual(expired["header"]["title"]["content"], "卡片已过期")
        self.assertNotIn("workflow_action", json.dumps(expired))
        self.assertFalse(self.workflow.load(e)["approved_write"])

    def test_bound_group_without_application_credentials_uses_existing_webhook(self):
        execution = self.task()
        with self.workflow.locked(execution):
            manifest = self.workflow.load(execution)
            manifest["workflow_state"] = "HUMAN_REQUIRED"
            self.workflow.save(manifest)
        self.workflow.env["FEISHU_WEBHOOK_URL"] = "https://open.feishu.cn/open-apis/bot/v2/hook/synthetic"
        opener = Mock(return_value=BytesIO(b'{"code":0}'))
        with patch.object(self.bridge, "client_for", return_value=None):
            result = self.workflow.notify(execution, opener=opener)
        self.assertEqual(result["status"], "sent")
        self.assertIn("?card=", opener.call_args.args[0].data.decode())

    def test_web_decision_patches_the_same_card_and_progress_message(self):
        e = self.task()
        before = self.workflow.load(e)
        card_id, ref = next(iter(before["feishu_cards"].items()))
        response = self.client.post(
            self.url + "/architect/decisions",
            json={"card_id": card_id, "action": "reject", "reason": "只保留当前范围"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.settled(e)
        patched = self.http.patches(ref["message_id"])[-1]
        self.assertIn("在网页不做了", json.dumps(patched, ensure_ascii=False))
        self.assertNotIn("workflow_action", json.dumps(patched))
        progress = before["feishu_progress"]["message_id"]
        self.assertEqual(self.workflow.load(e)["feishu_progress"]["message_id"], progress)
        self.assertTrue(self.http.patches(progress))
        self.assertEqual(len([c for c in self.http.calls if c[2].get("msg_type") == "interactive"]), 2)

    def ready_delivery(self):
        e = self.task()
        case = v2.WorkflowV2Test()
        case.workflow, case.execution = self.workflow, e
        case.calls, case.image_id, case.exit_code = [], "sha256:offline-feishu", 0
        with (
            patch.object(type(self.workflow), "readiness", return_value={"ready": True, "checks": []}),
            patch.object(self.api.core_module().workflow_runtime, "dispatch", return_value={"spawned": []}),
        ):
            self.assertEqual(self.click(e, "approve"), {"action": "skip"})
            approved = self.workflow.load(e)
            self.assertTrue(approved["approved_write"])
            self.assertEqual(approved["decisions_log"][-1]["action"], "approve")
            case.ready()
        self.settled(e)
        card = self.api.timeline_module().card_for(self.workflow.load(e), {})
        self.assertEqual(card["state"], "READY_FOR_ACCEPTANCE")
        key = card["card_id"]
        self.wait_for(lambda: key in self.workflow.load(e).get("feishu_cards", {}))
        return e, key

    def test_feishu_form_requests_one_new_approved_round_with_the_original_reason(self):
        execution, key = self.ready_delivery()
        self.click(execution, "request-changes", reason=" ", card_id=key)
        self.assertEqual(len(self.workflow.load(execution)["rounds"]), 1)
        with (
            patch.object(type(self.workflow), "readiness", return_value={"ready": True, "checks": []}),
            patch.object(self.api.core_module().workflow_runtime, "dispatch", return_value={"spawned": []}),
        ):
            self.click(execution, "request-changes", reason="保留原导出行为", card_id=key)
            self.click(execution, "request-changes", reason="保留原导出行为", card_id=key)
        self.settled(execution)
        manifest = self.workflow.load(execution)
        self.assertEqual(len(manifest["rounds"]), 2)
        self.assertTrue(manifest["approved_write"])
        change, approval = manifest["decisions_log"][-2:]
        self.assertEqual(
            (change["action"], change["round"], change["reason"]), ("request-changes", 0, "保留原导出行为")
        )
        self.assertEqual(
            (approval["action"], approval["round"], approval["by"]), ("approve", 1, "feishu:ou_admin")
        )

    def test_real_acceptance_receipt_shared_by_both_channels_and_duplicate_is_idempotent(self):
        e, key = self.ready_delivery()
        with patch.object(self.gateway_api, "perform", wraps=self.gateway_api.perform) as perform:
            self.assertEqual(self.click(e, "accept", card_id=key), {"action": "skip"})
            self.assertEqual(self.click(e, "accept", card_id=key), {"action": "skip"})
            self.assertEqual(perform.call_count, 1)
        self.settled(e)
        receipt = json.loads((self.workflow.path(e) / "acceptance.json").read_text())
        self.assertEqual(receipt["status"], "ACCEPTED")
        entry = self.workflow.load(e)["decisions_log"][-1]
        self.assertEqual(
            (entry["action"], entry["by"], entry["name"]), ("accept", "feishu:ou_admin", "测试审批人")
        )
        items = self.client.get(self.url + "/architect").json()["items"]
        self.assertEqual(next(i["resolved"]["by"] for i in items if i.get("card_id") == key), "feishu:ou_admin")
        self.assertIn("已处理。", [t for _, t in self.http.texts()])

    def test_group_and_web_messages_share_one_session_and_quote_the_recommended_card(self):
        e = self.task()
        card_id, ref = next(iter(self.workflow.load(e)["feishu_cards"].items()))
        self.referenced = card_id
        self.handle(event(actor="ou_member", primary="tenant-user-id", text="可以"))
        self.wait_for(lambda: any("建议核对" in t for _, t in self.http.texts()))
        self.assertFalse(any(t == "可以" or "你（网页）" in t for _, t in self.http.texts()))
        self.assertTrue(any(url.endswith("/" + ref["message_id"] + "/reply") for url, _ in self.http.texts()))
        self.assertEqual(self.gateway._is_user_authorized_for_source.call_args.args[0].user_id, "ou_member")
        before = self.client.get(self.url + "/architect").json()
        msg = next(i for i in before["items"] if i.get("content") == "可以")
        self.assertEqual((msg["channel"], msg["name"]), ("feishu", "测试审批人"))
        response = self.client.post(self.url + "/architect/messages", json={"message": "请解释风险"})
        self.assertEqual(response.status_code, 200, response.text)
        self.wait_for(lambda: len(self.http.texts()) == 3)
        self.assertIn("你（网页）：请解释风险", [t for _, t in self.http.texts()])
        after = self.client.get(self.url + "/architect").json()
        self.assertEqual(before["conversation"]["id"], after["conversation"]["id"])
        self.assertEqual(after["pending"], 1)

    def test_network_outage_does_not_block_or_undo_web_decision(self):
        e = self.task()
        m = self.workflow.load(e)
        key = next(iter(m["feishu_cards"]))
        entered, release = threading.Event(), threading.Event()

        def failing(req, **kwargs):
            entered.set()
            release.wait(8)
            raise OSError("offline")

        self.app.opener = failing
        try:
            response = self.client.post(
                self.url + "/architect/decisions", json={"card_id": key, "action": "reject", "reason": "确定不做"}
            )
            self.assertEqual(response.status_code, 200, response.text)
            self.assertTrue(entered.wait(4))
            import fcntl

            with (self.workflow.path(e) / "operator.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.workflow.load(e)["workflow_state"], "REJECTED")
        finally:
            release.set()
        self.settled(e)
        self.assertIn("retry_after", self.workflow.load(e)["feishu_sync"])
