"""Project a workflow into a bound Feishu group. Execution files remain authoritative."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime

if __package__:
    from . import workflow_notify, workflow_runtime, workflow_timeline as timeline
    from .workflow_feishu_client import client_for
else:
    import workflow_notify
    import workflow_runtime
    import workflow_timeline as timeline
    from workflow_feishu_client import client_for

_log = logging.getLogger(__name__)
ACTIONS = {
    "approve": "批准并开始",
    "accept": "确认验收",
    "repair": "批准修复",
    "request-changes": "提出修改",
    "reject": "不做了",
    "advance": "继续执行",
    "retry-worker": "重试失败角色",
}
REQUIRES_REASON = {"repair", "request-changes", "reject"}
ROLES = {"researcher": "方案", "builder": "开发", "tester": "独立测试", "reviewer": "独立审查"}
STATUS = {
    "triage": "待确认",
    "todo": "等待依赖",
    "ready": "待执行",
    "running": "进行中",
    "blocked": "阻塞",
    "done": "已完成",
    "archived": "已归档",
    "missing": "记录缺失",
}


def _text(content):
    return {"tag": "plain_text", "content": content}


def _line(content):
    return {"tag": "div", "text": _text(content)}


def _card(title, color, elements, link):
    if link:
        elements.append(
            {
                "tag": "button",
                "text": _text("在网页中打开"),
                "behaviors": [{"type": "open_url", "default_url": link}],
            }
        )
    return {
        "schema": "2.0",
        "config": {"update_multi": True},
        "header": {"title": _text(title), "template": color},
        "body": {"elements": elements},
    }


def probe_card(probe_id):
    return _card(
        "飞书联动测试",
        "blue",
        [
            _line("点击按钮检查回调和群内回复。此测试不创建任务。"),
            {
                "tag": "button",
                "text": _text("测试按钮"),
                "type": "primary",
                "behaviors": [{"type": "callback", "value": {"workflow_probe": probe_id}}],
            },
        ],
        "",
    )


def decision_card(card, link):
    elements = [_line(card["objective"].splitlines()[0]), _line(f"第 {card['round'] + 1} 轮")]
    elements.append(_line(card["text"]))
    if card["advice"]["source"] == "model":
        elements.append(_line("架构师建议 · " + card["advice"]["text"]))
    for reason in card["reasons"]:
        elements.append(_line("需要你决定 · " + reason["category"] + " " + "、".join(reason.get("paths", []))))
    for blocker in card["blockers"]:
        elements.append(
            _line("阻断问题 · " + str(blocker.get("summary") or blocker.get("description") or blocker))
        )

    resolution = card.get("resolved")
    if resolution:
        channel = "飞书" if resolution["by"].startswith("feishu:") else "网页"
        at = datetime.fromtimestamp(resolution["at"]).astimezone().strftime("%Y-%m-%d %H:%M %Z")
        label = ACTIONS[resolution["action"]]
        elements.append(_line(f"已由 {resolution['name']} 于 {at} 在{channel}{label}"))
        if resolution.get("reason"):
            elements.append(_line(resolution["reason"]))
        return _card(label, "grey" if resolution["action"] == "reject" else "green", elements, link)

    reason_buttons = []
    for action in card["actions"]:
        label = ACTIONS[action]
        value = {"workflow_card": card["card_id"], "workflow_action": action, "execution": card["execution_id"]}
        button = {
            "tag": "button",
            "name": action.replace("-", "_"),
            "form_action_type": "submit",
            "text": _text(label),
            "type": "danger" if action == "reject" else "primary",
            "confirm": {"title": _text(label), "text": _text(f"第 {card['round'] + 1} 轮 · {card['objective']}")},
            "behaviors": [{"type": "callback", "value": value}],
        }
        if action in REQUIRES_REASON:
            reason_buttons.append(button)
        else:
            elements.append({"tag": "form", "name": "form_" + button["name"], "elements": [button]})
    if reason_buttons:
        field = {"tag": "input", "name": "reason", "required": True, "placeholder": _text("填写原因或修改意见")}
        elements.append({"tag": "form", "name": "change_reason", "elements": [field, *reason_buttons]})
    return _card(card["title"], "orange", elements, link)


def progress_card(manifest, states, link):
    status = manifest["workflow_state"]
    changes = timeline.progress(manifest)
    label = changes[-1]["label"] if changes else status
    elements = [
        _line(manifest["objective"].splitlines()[0]),
        _line(f"第 {manifest['rounds'][-1]['number'] + 1} 轮 · {label}"),
    ]
    for role, label in ROLES.items():
        value = states.get(role, {}).get("status", "missing")
        elements.append(_line(label + " · " + STATUS.get(value, value)))
    return _card("任务进展", {"ACCEPTED": "green", "REJECTED": "grey"}.get(status, "blue"), elements, link)


def _delivery_id(*parts):
    return str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(parts, ensure_ascii=False)))


def _matches(ref, client, chat):
    return bool(
        ref
        and ref.get("message_id")
        and ref.get("chat_id") == chat
        and ref.get("app_id") == client.app_id
        and ref.get("host") == client.host
    )


def matches_message(ref, client, chat, message_id):
    return _matches(ref, client, chat) and ref["message_id"] == message_id


def _publish(workflow, client, manifest, chat, card_id, data):
    execution = manifest["execution_id"]
    ref = manifest.get("feishu_cards", {}).get(card_id) if card_id else manifest.get("feishu_progress")
    digest = hashlib.sha256(json.dumps(data, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if _matches(ref, client, chat):
        if ref.get("patch_closed") or ref.get("digest") == digest:
            return True
        message = ref["message_id"]
        if not client.patch_card(message, data):
            if client.last_error_code != 230031:
                return False
            # Feishu permanently closes PATCH after 14 days. Retain the last actual digest.
            receipt = {**ref, "patch_closed": 230031}
        else:
            receipt = {**ref, "digest": digest}
    else:
        event_id = _delivery_id(
            client.host,
            client.app_id,
            chat,
            str(workflow.project),
            workflow.board,
            execution,
            card_id or "progress",
        )
        message = client.send_card(chat, data, delivery_id=event_id)
        if not message:
            return False
        receipt = {
            "message_id": message,
            "chat_id": chat,
            "app_id": client.app_id,
            "host": client.host,
            "digest": digest,
        }
    with workflow.locked(execution):
        current = workflow.load(execution)
        if card_id:
            current.setdefault("feishu_cards", {})[card_id] = receipt
        else:
            current["feishu_progress"] = receipt
        workflow.save(current)
    return True


def _revision(manifest, client, chat):
    number = manifest["rounds"][-1]["number"]
    state = manifest["workflow_state"]
    advice = manifest.get("advice", {}).get(f"{number}:{state}", {})
    return [
        client.host,
        client.app_id,
        chat,
        number,
        state,
        len(manifest.get("decisions_log", [])),
        advice.get("at"),
    ]


def _publish_snapshot(workflow, client, manifest, chat):
    execution = manifest["execution_id"]
    states = timeline.task_states(workflow, manifest)
    link = workflow_notify.dashboard_link(workflow.env, execution)
    if manifest.get("workflow_state") == "ACCEPTED":
        receipt = workflow.path(execution) / "acceptance.json"
        if receipt.is_file():
            manifest = {**manifest, "accepted_by": json.loads(receipt.read_text()).get("accepted_by")}
    ok = _publish(workflow, client, manifest, chat, None, progress_card(manifest, states, link))
    active = timeline.card_for(manifest, states)
    resolved = {item["card_id"]: item for item in timeline.resolved_cards(manifest)}
    for card_id, ref in manifest.get("feishu_cards", {}).items():
        if not _matches(ref, client, chat) or (active and active["card_id"] == card_id):
            continue
        link = workflow_notify.dashboard_link(workflow.env, execution, card_id)
        if card_id in resolved:
            rendered = decision_card(resolved[card_id], link)
        else:
            rendered = _card("卡片已过期", "grey", [_line("任务状态已变化，请在网页查看当前决定。")], link)
        ok = _publish(workflow, client, manifest, chat, card_id, rendered) and ok
    if active:
        link = workflow_notify.dashboard_link(workflow.env, execution, active["card_id"])
        ok = _publish(workflow, client, manifest, chat, active["card_id"], decision_card(active, link)) and ok
    return ok


def _alive(pid):
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def _sync_worker(workflow, execution, client, chat):
    if __package__:
        from . import workflow_advisor, workflow_conversation
    else:
        import workflow_advisor
        import workflow_conversation
    try:
        with workflow_runtime.home_scope(workflow.root):
            # CLI-created tasks must also be visible when a Feishu deep link opens the web timeline.
            row = workflow_conversation.architect(workflow)
            if execution not in row["execution_ids"]:
                # An active conversation still owns its file. Retry after that turn finishes.
                raise RuntimeError("Conversation admission pending")
            while True:
                manifest = workflow.load(execution)
                if manifest.get("workflow_state") in timeline.STATES:
                    workflow_advisor.advise(workflow, execution)
                manifest = workflow.load(execution)
                revision = _revision(manifest, client, chat)
                ok = _publish_snapshot(workflow, client, manifest, chat)
                with workflow.locked(execution):
                    current = workflow.load(execution)
                    sync = current["feishu_sync"]
                    if _alive(current.get("decision_claim", {}).get("pid")):
                        sync.pop("pid", None)
                        workflow.save(current)
                        return  # The decision owner schedules the final state after releasing its claim.
                    if ok and _revision(current, client, chat) != revision:
                        continue  # A decision arrived while an HTTP request was in flight.
                    if ok:
                        sync["checked_revision"] = revision
                        sync.pop("retry_after", None)
                    else:
                        sync["retry_after"] = time.time() + 30
                    sync.pop("pid", None)
                    workflow.save(current)
                    return
    except Exception as exc:
        _log.warning("Feishu task synchronization deferred (%s)", type(exc).__name__)
        with workflow.locked(execution):
            current = workflow.load(execution)
            sync = current.setdefault("feishu_sync", {})
            sync.pop("pid", None)
            sync["retry_after"] = time.time() + 30
            workflow.save(current)


def sync_progress(workflow, execution):
    """Claim one publisher across Dashboard and Gateway. No HTTP runs under the flock."""
    if not workflow.env.get("WORKFLOW_FEISHU_CHAT_ID"):
        return False
    try:
        client = client_for(workflow)
        if not client:
            return False  # No application credentials: keep the existing webhook path.
        chat = workflow.env["WORKFLOW_FEISHU_CHAT_ID"].strip()
        with workflow.locked(execution):
            current = workflow.load(execution)
            if current.get("workflow_version", 1) < 2 or _alive(current.get("decision_claim", {}).get("pid")):
                return True
            sync = current.setdefault("feishu_sync", {})
            revision = _revision(current, client, chat)
            if (
                sync.get("checked_revision") == revision
                or _alive(sync.get("pid"))
                or (sync.get("attempt") == revision and sync.get("retry_after", 0) > time.time())
            ):
                return True
            sync.update(attempt=revision, pid=os.getpid())
            workflow.save(current)
        try:
            threading.Thread(
                target=_sync_worker,
                args=(workflow, execution, client, chat),
                name="workflow-feishu-sync",
                daemon=True,
            ).start()
        except RuntimeError:
            with workflow.locked(execution):
                current = workflow.load(execution)
                current["feishu_sync"].pop("pid", None)
                workflow.save(current)
            raise
    except Exception as exc:
        _log.warning("Feishu task scheduling deferred (%s)", type(exc).__name__)
    return True


def sync_card(workflow, execution, card_id):
    """Reconcile the authoritative decision log, including the requested old card."""
    return sync_progress(workflow, execution)


def mirror_turn(workflow, row, channel, text, reply, card_id, started):
    """The caller has already persisted and unlocked this conversation turn."""
    try:
        client = client_for(workflow)
        if not client:
            return
        chat = workflow.env["WORKFLOW_FEISHU_CHAT_ID"].strip()
        identity = (chat, row["id"], started)
        if channel == "web":
            client.send_text(chat, "你（网页）：" + text, delivery_id=_delivery_id(*identity, "user"))
        reply_to = None
        if card_id:
            for execution in row.get("execution_ids", []):
                ref = workflow.load(execution).get("feishu_cards", {}).get(card_id)
                if _matches(ref, client, chat):
                    reply_to = ref["message_id"]
                    break
        if reply:
            client.send_text(
                chat, reply, reply_to=reply_to, delivery_id=_delivery_id(*identity, "assistant")
            )
        elif channel == "feishu":
            client.send_text(chat, "本次回复失败，请在总控台对话查看原因后重试。")
    except Exception as exc:
        _log.warning("Feishu conversation delivery failed (%s)", type(exc).__name__)
