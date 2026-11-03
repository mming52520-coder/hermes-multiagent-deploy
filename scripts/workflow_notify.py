"""Single outbound channel for human decisions: a Feishu bot card.

Uses a Feishu custom-bot webhook (群机器人). Cards carry the Agent's
recommendation ("票拟") and a button that opens the decision in the
Dashboard, where the authenticated click is recorded ("批红"). Delivery
failures are logged and never block the workflow.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from urllib.parse import urlencode, urlsplit
import urllib.request

_log = logging.getLogger(__name__)
FEISHU_HOSTS = {"open.feishu.cn", "open.larksuite.com"}

TITLES = {
    "READY_FOR_ACCEPTANCE": ("需要你确认交付", "orange"),
    "REPAIR_REQUIRED": ("审查发现阻断问题，需要批准修复", "red"),
    "HUMAN_REQUIRED": ("任务需要人工处理", "red"),
    "ACCEPTED": ("已按授权范围自动验收", "green"),
}


def configured(env: dict) -> bool:
    return bool(env.get("FEISHU_WEBHOOK_URL", "").strip())


def sign(secret: str, timestamp: int) -> str:
    """Feishu custom-bot signature: HMAC-SHA256 keyed by "timestamp\\nsecret"."""
    key = f"{timestamp}\n{secret}".encode("utf-8")
    return base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode("ascii")


def dashboard_link(env: dict, execution: str) -> str:
    base = env.get("WORKFLOW_DASHBOARD_URL", "").strip().rstrip("/")
    return f"{base}/workflow?{urlencode({'execution': execution})}" if base else ""


def card(env: dict, event: dict) -> dict:
    title, template = TITLES.get(event["state"], ("工作流通知", "blue"))
    objective = event.get("objective", "").strip().splitlines()
    lines = [f"**任务**：{(objective[0] if objective else event['execution_id'])[:120]}",
             f"**轮次**：第 {event.get('round', 0) + 1} 轮"]
    if event.get("recommendation"):
        lines.append(f"**Agent 建议**：{event['recommendation'][:300]}")
    for reason in event.get("reasons", [])[:6]:
        paths = "、".join(reason.get("paths", [])[:5])
        lines.append(f"- {reason['category']}" + (f"：{paths}" if paths else ""))
    elements = [{"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}}]
    link = dashboard_link(env, event["execution_id"])
    if link:
        elements.append({"tag": "action", "actions": [
            {"tag": "button", "text": {"tag": "plain_text", "content": "去工作台处理"}, "type": "primary",
             "url": link}]})
    return {"msg_type": "interactive", "card": {
        "config": {"wide_screen_mode": True},
        "header": {"title": {"tag": "plain_text", "content": title}, "template": template},
        "elements": elements}}


def send(env: dict, event: dict, opener=None) -> dict:
    """Post one card. Returns a status record; never raises."""
    opener = opener or urllib.request.urlopen
    url = env.get("FEISHU_WEBHOOK_URL", "").strip()
    if not url:
        return {"status": "skipped"}
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in FEISHU_HOSTS:
        _log.error("FEISHU_WEBHOOK_URL must be an https Feishu/Lark bot webhook")
        return {"status": "error", "error": "invalid webhook host"}
    body = card(env, event)
    secret = env.get("FEISHU_WEBHOOK_SECRET", "").strip()
    if secret:
        timestamp = int(time.time())
        body.update(timestamp=str(timestamp), sign=sign(secret, timestamp))
    request = urllib.request.Request(url, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                     headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener(request, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
        code = data.get("code", data.get("StatusCode", 0))
        if code not in (0, None):
            # Never log the webhook URL: it is a credential.
            _log.error("Feishu rejected the card: code=%s msg=%s", code, data.get("msg"))
            return {"status": "error", "error": f"code {code}"}
        return {"status": "sent", "at": time.time()}
    except (OSError, ValueError) as exc:
        _log.error("Feishu notification failed: %s", type(exc).__name__)
        return {"status": "error", "error": type(exc).__name__}
