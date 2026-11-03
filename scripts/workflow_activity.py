"""Read real native worker events and public messages; never expose reasoning fields."""
from __future__ import annotations

import json
from pathlib import Path


def activity(workflow, execution: str) -> dict:
    from hermes_cli.profiles import get_profile_dir
    from hermes_state import SessionDB
    from .workflow_runtime import connect_closing

    manifest = workflow.load(execution)
    events, roles = [], {}
    seen = set()
    with connect_closing(board=workflow.board) as conn:
        for row in manifest["rounds"]:
            for role, task_id in row["tasks"].items():
                if task_id in seen:
                    continue
                seen.add(task_id)
                task = workflow.kb.get_task(conn, task_id)
                roles[role] = {"status": task.status if task else "missing"}
                if not task:
                    continue
                for item in conn.execute("SELECT id, kind, payload, created_at, run_id FROM task_events WHERE task_id=? ORDER BY id", (task_id,)):
                    # Native lifecycle events are authoritative; imported tool payloads are data.
                    if item["kind"] not in {"created", "claimed", "completed", "blocked", "owner_admitted", "worker_result", "crashed", "failed", "gave_up", "unblocked"}:
                        continue
                    payload = json.loads(item["payload"] or "{}")
                    events.append({"id": f"event:{item['id']}", "at": item["created_at"], "role": role,
                                   "kind": "status", "name": item["kind"], "text": payload.get("reason") or payload.get("error") or ""})
                for run in workflow.kb.list_runs(conn, task_id):
                    marker = conn.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='owner_admitted' ORDER BY id DESC LIMIT 1", (task_id, run.id)).fetchone()
                    metadata = json.loads(run.metadata) if isinstance(run.metadata, str) else run.metadata or {}
                    binding = json.loads(marker[0]) if marker else {}
                    session = binding.get("session_id") or metadata.get("worker_session_id")
                    database = Path(binding["db"]) if binding.get("db") else get_profile_dir(run.profile) / "state.db"
                    if not session or not database.is_file() or not database.resolve().is_relative_to(workflow.root):
                        continue
                    db = SessionDB(db_path=database, read_only=True)
                    try:
                        messages = db.get_messages(session, include_ancestors=True)
                    finally:
                        db.close()
                    for message in messages:
                        identity = f"message:{run.id}:{message['id']}"
                        common = {"at": message.get("timestamp") or run.started_at, "role": role,
                                  "session_id": session, "run_id": run.id}
                        if message["role"] == "assistant":
                            if message.get("content"):
                                events.append({**common, "id": identity, "kind": "message", "name": "工作摘要", "text": message["content"]})
                            calls = message.get("tool_calls") or []
                            if isinstance(calls, str):
                                calls = json.loads(calls)
                            for index, call in enumerate(calls):
                                function = call.get("function", call)
                                arguments = function.get("arguments", {})
                                events.append({**common, "id": identity + f":tool:{index}", "kind": "tool",
                                               "name": function.get("name", "tool"),
                                               "text": arguments if isinstance(arguments, str) else json.dumps(arguments, ensure_ascii=False)})
                        elif message["role"] == "tool":
                            events.append({**common, "id": identity, "kind": "tool_result", "name": message.get("tool_name") or "tool",
                                           "text": message.get("content") or ""})
                    if run.summary:
                        events.append({"id": f"result:{run.id}", "at": run.ended_at or run.started_at, "role": role,
                                       "kind": "result", "name": "阶段结果", "text": run.summary})
    unique = {event["id"]: event for event in events}
    return {"execution_id": execution, "workflow_state": manifest.get("workflow_state"), "roles": roles,
            "events": sorted(unique.values(), key=lambda item: (item["at"], item["id"]))}
