"""Project the existing workflow evidence into one architect timeline."""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import sqlite3
import time

STATES = {"WAITING_APPROVAL", "READY_FOR_ACCEPTANCE", "REPAIR_REQUIRED", "HUMAN_REQUIRED"}
PROGRESS = {
    "WAITING_APPROVAL": "等待确认需求", "RUNNING_RESEARCH": "开始方案",
    "RUNNING_BUILD_AND_TEST": "方案完成，开发与独立测试并行", "VERIFYING": "核对平台验证",
    "RUNNING_REVIEW": "平台测试通过，开始独立审查", "REPAIR_REQUIRED": "审查发现阻断问题",
    "HUMAN_REQUIRED": "需要人工处理", "ACCEPTED": "已验收", "REJECTED": "已决定不做",
    "READY_FOR_ACCEPTANCE": "等待确认交付",
}


def task_states(workflow, manifest: dict, *, detailed: bool = False) -> dict:
    database = workflow.kb.kanban_db_path(board=workflow.board)
    if not database.is_file():
        return {role: {"id": tid, "status": "missing", "outcome": None, "run_id": None,
                       "error": "原生任务数据库缺失，无法读取执行状态。"}
                for role, tid in manifest["rounds"][-1]["tasks"].items()} if detailed else {}
    with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        result = {}
        identities = {tid: {"role": role, "round": row["number"]}
                      for row in reversed(manifest["rounds"]) for role, tid in row["tasks"].items()}
        def related(ids):
            return [{"id": tid, **identities.get(tid, {}),
                     "assignee": parent.assignee if (parent := workflow.kb.get_task(conn, tid)) else None,
                     "status": parent.status if parent else "missing"} for tid in ids]
        for role, tid in manifest["rounds"][-1]["tasks"].items():
            task, run = workflow.kb.get_task(conn, tid), workflow.kb.latest_run(conn, tid)
            metadata = (run.metadata or {}) if run else {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            result[role] = {"status": task.status if task else "missing", "outcome": run.outcome if run else None,
                            "run_id": run.id if run else None, "findings": metadata.get("findings", [])}
            if detailed:
                if __package__:
                    from .workflow_control import review_verdict
                else:
                    from workflow_control import review_verdict
                parents = related(workflow.kb.parent_ids(conn, tid))
                pending = task and task.status in {"blocked", "todo", "triage"}
                blocked = conn.execute("SELECT payload FROM task_events WHERE task_id=? "
                                       "AND kind IN ('blocked', 'dependency_wait', 'block_loop_detected') "
                                       "AND (run_id=? OR run_id IS NULL) ORDER BY id DESC LIMIT 1",
                                       (tid, run.id if run else None)).fetchone() if pending else None
                result[role].update(
                    id=tid, round=identities[tid]["round"], assignee=task.assignee if task else None,
                    started_at=run.started_at if run else None, ended_at=run.ended_at if run else None,
                    parents=parents, children=related(workflow.kb.child_ids(conn, tid)),
                    waiting_for=[item for item in parents if item["status"] not in {"done", "archived"}],
                    block_kind=getattr(task, "block_kind", None) if pending else None,
                    block_reason=json.loads(blocked[0] or "{}").get("reason") if blocked else
                                 (run.summary if pending and run and run.outcome == "blocked" else None),
                    error=run.error if run else None, last_failure_error=task.last_failure_error if task else None,
                    result=run.summary if run else (task.result if task else None),
                    reported_status=metadata.get("status"),
                    verification=metadata.get("verification", metadata.get("commands_run", [])),
                    verdict=review_verdict(metadata) if role == "reviewer" else metadata.get("verdict"),
                    evidence_refs=metadata.get("evidence_refs", []), residual_risks=metadata.get("residual_risks", []),
                )
                output = workflow.output_path(manifest["execution_id"], identities[tid]["round"], role)
                result[role]["output_directory"] = str(output)
                result[role]["artifacts"] = sorted(file.relative_to(output).as_posix() for file in output.rglob("*")
                                                   if file.is_file() and file.resolve().is_relative_to(output.resolve()))
        return result


def verification_evidence(workflow, execution: str, number: int, role: str) -> dict:
    """Read the same bounded evidence for the task drawer and controller context."""
    directory = workflow.path(execution) / f"round-{number}"
    receipt_file, log = directory / f"{role}-verification.json", directory / f"{role}-verification.log"
    if not receipt_file.is_file():
        return {"role": role, "available": False}
    if not log.is_file():
        raise FileNotFoundError("验证日志缺失，证据不完整。")
    if not receipt_file.resolve().is_relative_to(directory.resolve()) or not log.resolve().is_relative_to(directory.resolve()):
        raise PermissionError("证据文件不在允许范围内。")
    receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
    with log.open("rb") as stream:
        stream.seek(max(0, log.stat().st_size - 16384))
        tail = stream.read().decode("utf-8", errors="replace")
    return {"available": True, "receipt": receipt, "log_tail": tail,
            "log_matches": hashlib.sha256(log.read_bytes()).hexdigest() == receipt["log_sha256"]}


def execution_context(workflow, manifest: dict) -> dict:
    """Observe existing task/evidence records without dispatching or running verification."""
    execution, row = manifest["execution_id"], manifest["rounds"][-1]
    tasks = task_states(workflow, manifest, detailed=True)
    state = manifest.get("workflow_state")
    card = card_for(manifest, tasks)
    verification = {}
    for role in (("platform",) if workflow.modern(manifest) else ("builder", "reviewer")):
        try:
            evidence = verification_evidence(workflow, execution, row["number"], role)
            if evidence["available"]:
                expected = {"execution_id": execution, "round": row["number"], "role": role,
                            "candidate_digest": row.get("candidate_digest"), "candidate_revision": row.get("candidate_revision")}
                if role == "platform":
                    expected.update(evidence_key=row.get("verification_key"), independent_tests_digest=row.get("independent_tests_digest"),
                                    command=row.get("verification_command"), environment=row.get("verification_environment"),
                                    runs={r: tasks.get(r, {}).get("run_id") for r in ("builder", "tester")})
                else:
                    expected.pop("round")
                    expected.update(task_id=row["tasks"][role], run_id=tasks.get(role, {}).get("run_id"), command=manifest["test_command"])
                evidence["matches_current_inputs"] = all(evidence["receipt"].get(k) == v for k, v in expected.items())
            verification[role] = evidence
        except (ValueError, OSError, KeyError) as exc:
            verification[role] = {"available": False, "error": str(exc)}
    # Only completed candidates need the existing acceptance integrity check. Running
    # verification holds the execution lock, so progress questions must not wait for it.
    acceptance = {"status": "NOT_ACCEPTED", "reason": "当前流程未处于待验收或已验收状态。"}
    if state in {"READY_FOR_ACCEPTANCE", "ACCEPTED"} or not workflow.modern(manifest):
        try:
            acceptance = workflow.status(execution)["acceptance"]
        except (ValueError, OSError, sqlite3.Error, KeyError) as exc:
            acceptance = {"status": "UNKNOWN", "reason": str(exc)}
    files, source = row.get("candidate_files"), manifest["source_files"]
    changed = sorted(key for key in files.keys() | source.keys() if files.get(key) != source.get(key)) if files is not None else []
    readiness = workflow.readiness(execution) if state == "HUMAN_REQUIRED" and not row.get("started_at") else None
    return {"execution_id": execution, "objective": manifest["objective"], "round": row["number"], "state": state,
            "observed_at": time.time(), "source_revision": manifest["source_revision"], "tasks": tasks,
            "current_request": manifest["failures"][-1] if row["number"] and manifest["failures"] else None,
            "failures": manifest["failures"], "readiness": readiness,
            "pending_decision": {k: card[k] for k in ("card_id", "title", "text", "actions", "reasons")} if card else None,
            "rejection": manifest.get("rejection"), "verification": verification, "acceptance": acceptance,
            "delivery": {"snapshot_ready": row.get("snapshot_ready", False), "candidate_revision": row.get("candidate_revision"),
                         "candidate_digest": row.get("candidate_digest"), "changed_files": changed}}


def card_for(manifest: dict, tasks: dict) -> dict | None:
    state = manifest.get("workflow_state")
    if manifest.get("workflow_version", 1) < 2 or state not in STATES:
        return None
    number = manifest["rounds"][-1]["number"]
    exhausted = len(manifest["rounds"]) - 1 >= manifest["budget"]["max_rounds"]
    if state == "WAITING_APPROVAL":
        title, text, actions = "等待确认需求", "请核对需求和本轮范围。批准后由后台协调方案、开发、独立测试和审查。", ["approve", "reject"]
    elif state == "READY_FOR_ACCEPTANCE":
        title, text, actions = "等待确认交付", "项目测试、独立测试和独立审查已通过，请核对交付及需要你决定的改动。", ["accept", "request-changes", "reject"]
        if exhausted:
            actions.remove("request-changes")
    elif state == "REPAIR_REQUIRED":
        title, text, actions = "需要修改", "本轮验证或审查未通过，建议按具体问题批准下一轮修复。", ["repair", "reject"]
        if exhausted:
            title, text, actions = "整改轮次已用完", "已达到本任务的整改上限，请人工核对记录后决定不做。", ["reject"]
    else:
        title, text, actions = "需要处理", "角色被阻塞或运行环境未就绪，请先查看任务抽屉中的原因。", ["reject"]
        retry = next((role for role, task in tasks.items() if task.get("status") == "blocked"
                      and task.get("outcome") in {"crashed", "failed", "spawn_failed", "timeout", "timed_out", "gave_up"}), None)
        if retry:
            actions.insert(0, "retry-worker")
        elif tasks and not any(task.get("status") in {"blocked", "missing"} for task in tasks.values()):
            actions.insert(0, "advance")
    identity = f"{manifest['execution_id']}|{number}|{state}|{len(manifest.get('decisions_log', []))}"
    entered = next((item["at"] for item in reversed(manifest.get("transitions", []))
                    if item["to"] == state and item["round"] == number), manifest["created_at"])
    findings = tasks.get("reviewer", {}).get("findings", [])
    blockers = [item for item in findings if isinstance(item, dict) and item.get("severity") == "blocker"]
    decision = manifest.get("decision", {})
    return {"type": "card", "card_id": hashlib.sha256(identity.encode()).hexdigest()[:16],
            "execution_id": manifest["execution_id"], "round": number, "state": state,
            "objective": manifest["objective"], "source_revision": manifest["source_revision"],
            "candidate_digest": manifest["rounds"][-1].get("candidate_digest"),
            "title": title, "text": text, "actions": actions, "at": entered,
            "advice": manifest.get("advice", {}).get(f"{number}:{state}", {"text": text, "source": "rule"}),
            "reasons": decision.get("reasons", []) if decision.get("round") == number else [],
            "blockers": blockers, "resolved": None,
            "retry": {"role": retry, "run_id": tasks[retry]["run_id"]} if state == "HUMAN_REQUIRED" and retry else None}


def resolved_cards(manifest: dict) -> list[dict]:
    return [{**entry["card"], "resolved": {key: entry[key] for key in ("action", "by", "name", "reason", "at")}}
            for entry in manifest.get("decisions_log", []) if entry.get("card")]


def progress(manifest: dict) -> list[dict]:
    changes = manifest.get("transitions") or [{"to": manifest.get("workflow_state"), "at": manifest["created_at"], "round": 0}]
    result = []
    for index, item in enumerate(changes):
        text = PROGRESS.get(item["to"])
        if not text:
            continue
        if item["to"] == "ACCEPTED" and manifest.get("accepted_by") == "policy":
            text = "已在授权范围内自动验收"
        if item["to"] == "REPAIR_REQUIRED" and item.get("verification") == "FAIL":
            text = "平台测试未通过"
        objective = manifest['objective'].splitlines()[0]
        result.append({"type": "progress", "id": f"{manifest['execution_id']}:{index}",
                       "execution_id": manifest["execution_id"], "objective": objective, "label": text,
                       "text": f"「{objective}」{text}",
                       "at": item["at"]})
    return result


def record_decision(workflow, execution: str, card_id: str, action: str, by: str, name: str,
                    reason: str, *, card: dict) -> None:
    with workflow.locked(execution):
        manifest = workflow.load(execution)
        entries = manifest.setdefault("decisions_log", [])
        if any(entry["card_id"] == card_id for entry in entries):
            return
        entries.append({"card_id": card_id, "action": action, "round": card["round"], "by": by,
                        "name": name, "reason": reason, "at": time.time(), "card": card})
        workflow.save(manifest)


def timeline(workflow, conversation: dict) -> dict:
    if __package__:
        from . import workflow_conversation as chats
    else:
        import workflow_conversation as chats
    items = [{"type": "message", **message} for message in chats.view(workflow, conversation["id"])["messages"]]
    pending = 0
    for execution in conversation.get("execution_ids", []):
        manifest = workflow.load(execution)
        receipt = workflow.path(execution) / "acceptance.json"
        if receipt.is_file():
            manifest["accepted_by"] = json.loads(receipt.read_text()).get("accepted_by")
        items.extend(progress(manifest))
        items.extend(resolved_cards(manifest))
        card = card_for(manifest, task_states(workflow, manifest))
        if card:
            items.append(card)
            pending += 1
    return {"items": sorted(items, key=lambda item: item["at"]), "pending": pending}
