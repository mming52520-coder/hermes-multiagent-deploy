"""Pre-authorized auto-acceptance, decision log and the Feishu decision channel."""
import base64
import hashlib
import hmac
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workflow as fixtures
import test_workflow_v2 as v2

wc = fixtures.wc
policy = wc.workflow_policy
notify = wc.workflow_notify


class PolicyUnitTest(unittest.TestCase):
    on = {"auto_accept": True, "max_auto_files": 20, "extra_paths": []}

    def test_disabled_policy_always_asks(self):
        self.assertEqual(policy.decision_reasons(None, ["a.py"], [])[0]["category"], "未开启自动验收")
        self.assertTrue(policy.decision_reasons({**self.on, "auto_accept": False}, ["a.py"], []))

    def test_scope_categories(self):
        self.assertEqual(policy.decision_reasons(self.on, ["src/app.py", "tests/test_app.py"], []), [])
        cases = {"db/migrations/0002_add.py": "数据库结构或迁移", ".github/workflows/ci.yml": "CI、部署或权限配置",
                 ".env.production": "密钥或凭据", "web/package.json": "新增或升级依赖",
                 "requirements.txt": "新增或升级依赖"}
        for path, category in cases.items():
            reasons = policy.decision_reasons(self.on, [path], [])
            self.assertEqual([r["category"] for r in reasons], [category], path)
        self.assertEqual(policy.decision_reasons(self.on, ["old.py"], ["old.py"])[0]["category"], "删除文件")
        many = [f"f{i}.py" for i in range(21)]
        self.assertIn("改动文件超过", policy.decision_reasons(self.on, many, [])[0]["category"])
        extra = {**self.on, "extra_paths": ["billing/*"]}
        self.assertEqual(policy.decision_reasons(extra, ["billing/plan.py"], [])[0]["category"], "操作员指定的路径")

    def test_policy_snapshot_from_env(self):
        self.assertFalse(policy.policy_from_env({})["auto_accept"])
        snap = policy.policy_from_env({"WORKFLOW_AUTO_ACCEPT": "true", "WORKFLOW_DECISION_PATHS": "billing/*, ops/*"})
        self.assertEqual((snap["auto_accept"], snap["extra_paths"]), (True, ["billing/*", "ops/*"]))


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class NotifyUnitTest(unittest.TestCase):
    env = {"FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/x",
           "FEISHU_WEBHOOK_SECRET": "s3cret", "WORKFLOW_DASHBOARD_URL": "http://127.0.0.1:9119/"}
    event = {"execution_id": "a" * 32, "objective": "登录页白屏\n细节", "state": "READY_FOR_ACCEPTANCE",
             "round": 0, "recommendation": "建议确认交付",
             "reasons": [{"category": "新增或升级依赖", "paths": ["package.json"]}]}

    def test_signed_card_with_decision_link(self):
        sent = []
        def opener(request, timeout):
            sent.append(json.loads(request.data))
            return FakeResponse(b'{"code":0}')
        self.assertEqual(notify.send(self.env, self.event, opener)["status"], "sent")
        body = sent[0]
        key = f"{body['timestamp']}\ns3cret".encode()
        self.assertEqual(body["sign"], base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode())
        text = json.dumps(body["card"], ensure_ascii=False)
        self.assertIn("登录页白屏", text)
        self.assertIn("package.json", text)
        self.assertIn("http://127.0.0.1:9119/workflow?execution=" + "a" * 32, text)

    def test_failures_and_unsafe_hosts_never_raise(self):
        def broken(request, timeout):
            raise OSError("down")
        self.assertEqual(notify.send(self.env, self.event, broken)["status"], "error")
        rejected = lambda request, timeout: FakeResponse(b'{"code":19021,"msg":"sign match fail"}')
        self.assertEqual(notify.send(self.env, self.event, rejected)["status"], "error")
        unsafe = {**self.env, "FEISHU_WEBHOOK_URL": "https://example.com/hook"}
        self.assertEqual(notify.send(unsafe, self.event, broken)["error"], "invalid webhook host")
        self.assertEqual(notify.send({}, self.event, broken)["status"], "skipped")


class PolicyWorkflowTest(unittest.TestCase):
    """Native Kanban v2 flow with the policy snapshot enabled after submission."""
    workflow_version = 2
    for _name in ("setUp", "runner", "advance", "research", "deliver", "row", "completed", "metadata"):
        locals()[_name] = getattr(v2.WorkflowV2Test, _name)

    def enable(self, **extra):
        manifest = self.workflow.load(self.execution)
        manifest["policy"] = {"auto_accept": True, "max_auto_files": 20, "extra_paths": [], **extra}
        self.workflow.save(manifest)

    def reviewed(self, *, extra_file=None):
        self.research()
        if extra_file:
            (Path(self.row()["candidate"]) / extra_file).write_text("dependency==1\n", encoding="utf-8")
        self.deliver()
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        self.completed("reviewer", {"verdict": "PASS", "findings": []})
        return self.advance()

    def test_pre_authorized_change_is_accepted_without_a_click(self):
        self.enable()
        result = self.reviewed()
        self.assertEqual((result["state"], result["completed"]), ("ACCEPTED", True))
        record = json.loads((self.workflow.path(self.execution) / "acceptance.json").read_text())
        self.assertEqual(record["accepted_by"], "policy")
        self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"], "ACCEPTED")
        self.assertEqual(wc.git(self.project, "status", "--porcelain"), "")
        self.assertFalse(policy.decisions_directory(self.root, "default").exists())

    def test_dependency_change_waits_for_human_and_is_logged_when_approved(self):
        self.enable()
        self.assertEqual(self.reviewed(extra_file="requirements.txt")["state"], "READY_FOR_ACCEPTANCE")
        decision = self.workflow.load(self.execution)["decision"]
        self.assertEqual(decision["reasons"], [{"category": "新增或升级依赖", "paths": ["requirements.txt"]}])
        self.assertEqual(self.workflow.accept(self.execution, "同意引入这个依赖")["accepted_by"], "operator")
        log = (policy.decisions_directory(self.root, "default") / "approved.md").read_text()
        self.assertIn("> 同意引入这个依赖", log)
        self.assertIn("requirements.txt", log)
        self.assertIn(self.execution, log)

    def test_default_policy_keeps_manual_acceptance(self):
        self.assertFalse(self.workflow.load(self.execution)["policy"]["auto_accept"])
        self.assertEqual(self.reviewed()["state"], "READY_FOR_ACCEPTANCE")
        self.workflow.accept(self.execution)
        self.assertFalse((policy.decisions_directory(self.root, "default") / "approved.md").exists())

    def test_rejection_is_final_and_recorded_for_future_planning(self):
        self.assertEqual(self.reviewed()["state"], "READY_FOR_ACCEPTANCE")
        with self.assertRaisesRegex(wc.Rejected, "原因"):
            self.workflow.reject(self.execution, "  ")
        self.workflow.reject(self.execution, "不做 Safari 兼容，用户量太小")
        self.assertEqual(self.advance()["state"], "REJECTED")
        with self.assertRaisesRegex(wc.Rejected, "决定不做"):
            self.workflow.approve(self.execution)
        with self.assertRaises(wc.Rejected):
            self.workflow.accept(self.execution)
        self.assertIn("不做 Safari 兼容", (policy.decisions_directory(self.root, "default") / "rejected.md").read_text())
        follow_up = self.workflow.submit("Another fixture objective")
        with fixtures.connect_closing(board="default") as conn:
            body = fixtures.kb.get_task(conn, follow_up["rounds"][0]["tasks"]["researcher"]).body
        self.assertIn("不做 Safari 兼容", body)

    def test_one_card_per_decision_point(self):
        self.workflow.env = {**self.workflow.env, "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/x"}
        cards = []
        def opener(request, timeout):
            cards.append(json.loads(request.data))
            return FakeResponse(b'{"code":0}')
        with patch.object(notify.urllib.request, "urlopen", opener):
            self.assertEqual(self.reviewed()["state"], "READY_FOR_ACCEPTANCE")
            self.advance()
            self.workflow.notify(self.execution)
        self.assertEqual(len(cards), 1)
        self.assertEqual(self.workflow.load(self.execution)["notifications"]["0:READY_FOR_ACCEPTANCE"]["status"], "sent")

    def test_notification_failure_does_not_block_progress(self):
        self.workflow.env = {**self.workflow.env, "FEISHU_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/x"}
        with patch.object(notify.urllib.request, "urlopen", side_effect=OSError("offline")):
            self.assertEqual(self.reviewed()["state"], "READY_FOR_ACCEPTANCE")
        self.assertEqual(self.workflow.load(self.execution)["notifications"]["0:READY_FOR_ACCEPTANCE"]["status"], "error")
        self.assertEqual(self.workflow.accept(self.execution)["status"], "ACCEPTED")


if __name__ == "__main__":
    unittest.main()
