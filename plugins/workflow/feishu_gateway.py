"""Feishu gateway ingress. Only the installed workflow's bound group is claimed."""

from __future__ import annotations

from copy import copy
from functools import partial
import json
import logging
from pathlib import Path

from fastapi import HTTPException
from .dashboard import plugin_api as api

_log = logging.getLogger(__name__)
SKIP = {"action": "skip"}


def _ids(value):
    return {item.strip() for item in value.split(",") if item.strip()}


def _click(workflow, settings, bridge, client, event, raw, actor, name):
    chat = event.source.chat_id
    value = raw.action.value
    execution, card_id, action = (value.get(key) for key in ("execution", "workflow_card", "workflow_action"))
    context = raw.context
    if context.open_chat_id != chat or event.source.user_id != actor:
        return
    if not all(isinstance(item, str) and item for item in (execution, card_id, action)):
        client.send_text(chat, "卡片已过期，请在网页查看当前决定。")
        return
    try:
        manifest = api.load_manifest(settings, execution)
    except HTTPException:
        client.send_text(chat, "卡片已过期，请在网页查看当前决定。")
        return
    ref = manifest.get("feishu_cards", {}).get(card_id)
    if not bridge.matches_message(ref, client, chat, context.open_message_id):
        client.send_text(chat, "卡片已过期，请打开本项目群中的原卡片。")
        return

    def previous():
        return next(
            (entry for entry in workflow.load(execution).get("decisions_log", []) if entry["card_id"] == card_id),
            None,
        )

    already = previous()
    if already:
        bridge.sync_card(workflow, execution, card_id)
        client.send_text(chat, "已处理。" if already["action"] == action else "卡片已过期，原决定已记录。")
        return
    form = getattr(raw.action, "form_value", None) or {}
    reason = form.get("reason", "") if isinstance(form, dict) else ""
    if not isinstance(reason, str) or len(reason) > 2000:
        client.send_text(chat, "原因须为不超过 2000 字的文本。")
        return
    decision = api.ArchitectDecision(card_id=card_id, action=action, reason=reason)
    try:
        api.decide(settings, decision, by="feishu:" + actor, name=name, execution_id=execution)
    except HTTPException as exc:
        # A web operator may have completed this exact decision since the first read.
        already = previous()
        bridge.sync_card(workflow, execution, card_id)
        detail = (
            exc.detail
            if exc.detail
            in {
                "这张卡片不允许此操作。",
                "请填写原因或修改意见。",
                "这项决策正在处理，请稍候刷新。",
                "卡片已过期，请刷新。",
            }
            else "操作未完成，请在总控台对话查看任务状态。"
        )
        client.send_text(chat, "已处理。" if already and already["action"] == action else detail)
        return
    client.send_text(chat, "已记录 · " + bridge.ACTIONS[action], reply_to=context.open_message_id)


def _unattributed_batch(event, message, gateway):
    # In a shared topic Hermes keeps the first raw sender and the last message ID
    # when it concatenates a burst. Only a per-user native batch has one proven author.
    first, last = getattr(message, "message_id", None), getattr(event, "message_id", None)
    if not first or not last or first == last:
        return False
    adapter = gateway._adapter_for_source(event.source)
    if adapter is None:
        return True
    extra = adapter.config.extra
    return not extra.get("group_sessions_per_user", True) or (
        getattr(event.source, "thread_id", None) and not extra.get("thread_sessions_per_user", False)
    )


def dispatch(event, gateway):
    from hermes_constants import get_hermes_home

    config = api.PLUGIN_ROOT / "config.json"
    if not config.is_file():
        return None
    settings = json.loads(config.read_text())
    if Path(settings["hermes_home"]).resolve() != Path(get_hermes_home()).resolve():
        return None
    env = api.bound_environment(settings)
    chat = env.get("WORKFLOW_FEISHU_CHAT_ID", "").strip()
    if not chat or chat != event.source.chat_id:
        return None
    # The native pre-dispatch hook fails open on exceptions. Once we own a message,
    # every failure must consume it so it cannot fall through to a second agent.
    try:
        if settings.get("allow_actions") is not True or getattr(event.source, "is_bot", False):
            return SKIP
        envelope = event.raw_message
        header = getattr(envelope, "header", None)
        kind = getattr(header, "event_type", "")
        raw = getattr(envelope, "event", None)
        if kind == "card.action.trigger":
            value = getattr(getattr(raw, "action", None), "value", None)
            if not isinstance(value, dict) or not ({"workflow_card", "workflow_probe"} & value.keys()):
                return None  # A different card handler owns this callback.
            if getattr(raw.action, "tag", None) != "button" or getattr(raw, "context", None) is None:
                return SKIP
            actor = getattr(getattr(raw, "operator", None), "open_id", None)
        elif kind == "im.message.receive_v1":
            sender = getattr(raw, "sender", None)
            if (
                getattr(sender, "sender_type", None) != "user"
                or getattr(getattr(raw, "message", None), "chat_id", None) != chat
            ):
                return SKIP
            actor = getattr(getattr(sender, "sender_id", None), "open_id", None)
        else:
            return SKIP
        approvers = _ids(env.get("WORKFLOW_FEISHU_APPROVERS", ""))
        members = _ids(env.get("WORKFLOW_FEISHU_MEMBERS", "")) or approvers
        if not actor or (kind == "im.message.receive_v1" and actor not in members):
            _log.info("Workflow ignored Feishu message from a non-member")
            return SKIP
        workflow = api.bound_workflow(settings)
        bridge = api.core_module().workflow_feishu
        with api.core_module().workflow_runtime.home_scope(workflow.root):
            client = bridge.client_for(workflow)
            if not client or getattr(header, "app_id", None) != client.app_id:
                return SKIP
            if kind == "card.action.trigger" and actor not in approvers:
                client.send_text(chat, "你没有审批权限。")
                return SKIP
            # Generic messages can use a tenant user_id; the raw event supplies the app-scoped open_id.
            source = copy(event.source)
            source.user_id = actor
            if gateway is None or not gateway._is_user_authorized_for_source(source):
                return SKIP
            paused = gateway._hm_estop_gate(event, source, False)
            if paused is not None:
                if paused:
                    client.send_text(chat, paused)
                return SKIP
            api.verify_operator_source(settings)
            name = event.source.user_name or "飞书成员"
            if kind == "card.action.trigger" and "workflow_probe" in value:
                receipt_file = workflow.root / "workflow/feishu-probe.json"
                receipt = json.loads(receipt_file.read_text()) if receipt_file.is_file() else {}
                if (
                    raw.context.open_chat_id == chat
                    and event.source.user_id == actor
                    and value["workflow_probe"] == receipt.get("probe_id")
                    and bridge.matches_message(receipt, client, chat, raw.context.open_message_id)
                ):
                    client.send_text(chat, "联动正常", reply_to=raw.context.open_message_id)
                return SKIP
            if kind == "card.action.trigger":
                _click(workflow, settings, bridge, client, event, raw, actor, name)
            else:
                if _unattributed_batch(event, raw.message, gateway):
                    client.send_text(chat, "群消息已合并，无法核对每条消息的发送人。请将需求作为单条消息重发。")
                    return SKIP
                message = event.text.strip()
                if message.startswith("/card "):
                    client.send_text(chat, "请点击原决策卡上的按钮。")
                    return SKIP
                if not message or len(message) > 4000:
                    client.send_text(chat, "请发送 1 至 4000 字的需求。")
                    return SKIP
                chats = api.conversations_module()
                row = chats.architect(workflow)
                try:
                    chats.start(
                        workflow,
                        row["id"],
                        message,
                        api.architect_context(workflow, row),
                        channel="feishu",
                        name=name,
                        publish_task=(partial(api.publish_conversation_task, settings, workflow,
                                              by="feishu:" + actor, name=name) if actor in approvers else None),
                    )
                except ValueError:
                    client.send_text(chat, "总控台暂时无法接收这条消息，请稍后重试。")
    except Exception as exc:
        _log.warning("Workflow Feishu input could not be handled (%s)", type(exc).__name__)
    return SKIP
