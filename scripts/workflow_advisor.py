"""Bounded, advisory-only model suggestions; rules remain available immediately."""
from __future__ import annotations

import logging
import threading
import time
import uuid

if __package__:
    from . import workflow_conversation as chats, workflow_timeline as timeline, workflow_runtime, workflow_policy
else:
    import workflow_conversation as chats
    import workflow_timeline as timeline
    import workflow_runtime
    import workflow_policy

TIMEOUT = 60
_active = set()
_guard = threading.Lock()
_log = logging.getLogger(__name__)
PROMPT = """你是项目架构师，只提供建议，不执行操作。根据给出的证据，用不超过300字给出建议、理由和需用户核对的风险。
current_request 非空时，以其中的本轮人工修改或修复要求为准，不用初始 objective 的旧限制覆盖它；是否已批准或验收仍以 state 为准。
不要声称已经批准、验收、修改或运行任何内容。未知信息明确说未知。只返回 JSON：{"reply":"建议","objective":null}。"""


def advise(workflow, execution: str) -> dict:
    manifest = workflow.load(execution)
    key = f"{manifest['rounds'][-1]['number']}:{manifest.get('workflow_state')}"
    if key in manifest.get("advice", {}):
        return manifest["advice"][key]
    tasks = timeline.task_states(workflow, manifest)
    card = timeline.card_for(manifest, tasks)
    if card is None:
        return {"text": "", "source": "rule"}
    fallback = {"text": card["text"], "source": "rule"}
    identity = (str(workflow.root), execution, key)
    with _guard:
        if identity in _active:
            return fallback
        _active.add(identity)
    done, result = threading.Event(), {}
    cancelled = threading.Event()
    def generate():
        agent = None
        try:
            with workflow_runtime.home_scope(workflow.root):
                agent = chats.make_agent(workflow, {"session_id": uuid.uuid4().hex}, None)
                result["agent"] = agent
                if cancelled.is_set():
                    return
                import json
                files = manifest["rounds"][-1].get("candidate_files")
                source = manifest["source_files"]
                changed = sorted(key for key in files.keys() | source.keys() if files.get(key) != source.get(key)) if files is not None else []
                context = {"objective": manifest["objective"], "state": card["state"], "reasons": card["reasons"],
                           "current_request": manifest["failures"][-1] if manifest["rounds"][-1]["number"] else None,
                           "findings": tasks.get("reviewer", {}).get("findings", []),
                           "changed_files": changed[:50],
                           "decisions": workflow_policy.read_decisions(workflow.root, workflow.board)}
                reply = agent.run_conversation(json.dumps(context, ensure_ascii=False), system_message=PROMPT)
                if reply.get("error"):
                    raise ValueError(str(reply["error"]))
                text = chats.decode(reply.get("final_response", ""))["reply"].strip()[:300]
                if text:
                    result["advice"] = {"text": text, "source": "model"}
        except Exception as exc:
            _log.info("Architect advice unavailable (%s); using the rule explanation", type(exc).__name__)
        finally:
            try:
                if agent is not None:
                    agent.close()
            finally:
                done.set()
    try:
        current = workflow.load(execution)
        if key in current.get("advice", {}):
            return current["advice"][key]
        threading.Thread(target=generate, name="workflow-advice", daemon=True).start()
        completed = done.wait(TIMEOUT)
        if not completed:
            cancelled.set()
            if result.get("agent") is not None:
                result["agent"].interrupt("Architect advice deadline reached", hard_cancel=True)
        advice = {**(result.get("advice", fallback) if completed else fallback), "at": time.time()}
        with workflow.locked(execution):
            current = workflow.load(execution)
            if f"{current['rounds'][-1]['number']}:{current.get('workflow_state')}" != key:
                return fallback
            advice = current.setdefault("advice", {}).setdefault(key, advice)
            workflow.save(current)
        return advice
    finally:
        with _guard:
            _active.discard(identity)


def schedule(workflow, execution: str) -> None:
    threading.Thread(target=advise, args=(workflow, execution), name="workflow-advice-start", daemon=True).start()
