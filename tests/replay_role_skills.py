"""Opt-in live replay: python tests/replay_role_skills.py SOURCE CASE.json OUTPUT.

Uses the configured role model, native tools/preload and real Docker verification.
The owner/dispatcher is replaced by this finite sequential driver; no gateway,
notifications, acceptance, or production task writes. OUTPUT must be new.
This is an evaluation utility, not a deployment command or an offline unit test.
"""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from unittest.mock import patch


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


@contextmanager
def worker_session(task, session_id):
    from gateway.session_context import set_session_vars, clear_session_vars
    tokens = set_session_vars(session_key=f"agent:{task.assignee}:evaluation", session_id=session_id,
                              profile=task.assignee, cwd=task.workspace_path)
    try:
        yield
    finally:
        clear_session_vars(tokens)


def main():
    source, case_path, output = map(lambda s: Path(s).resolve(), sys.argv[1:4])
    case = json.loads(case_path.read_text())
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    dump(output / "input.json", case)
    # Resolve only the requested model connection through the existing provider
    # mechanism. Keep credentials in memory; never serialize config/runtime.
    import hermes_cli.main  # native bootstrap before entering an isolated home
    from hermes_cli.config import load_config
    from hermes_cli.runtime_provider import resolve_runtime_provider
    from hermes_constants import get_hermes_home, set_hermes_home_override, resolve_reasoning_config
    from run_agent import AIAgent
    from hermes_state import SessionDB
    original_home = get_hermes_home()
    role = case.get("role", "architect")
    connection_home = original_home if role == "architect" else original_home / "profiles" / role
    os.environ["HERMES_HOME"] = str(connection_home)
    set_hermes_home_override(connection_home)
    config = load_config()
    model = config["model"]
    runtime = resolve_runtime_provider(requested=model.get("provider"), target_model=model["default"])
    runtime_keys = ("provider", "requested_provider", "base_url", "api_key", "api_mode", "credential_pool",
                    "command", "args", "request_overrides")
    connection = {k: runtime.get(k) for k in runtime_keys}
    reasoning = resolve_reasoning_config(config, model["default"])
    # Native model dictionaries may contain inline api_key. The resolver above
    # owns credentials; fixture configuration only needs these routing labels.
    fixture_model = {key: model[key] for key in ("default", "provider") if key in model}
    sys.path.insert(0, str(source / "scripts"))
    import workflow_control as wc
    import workflow_conversation as conversation
    from configure_profiles import write_yaml, read_yaml
    home = output / "home"
    home.mkdir(mode=0o700)
    os.environ["HERMES_HOME"] = str(home)
    set_hermes_home_override(None)
    os.environ["HERMES_SINGLE_QUERY_SESSION"] = "1"
    os.environ["HERMES_KANBAN_BOARD"] = "default"
    for key in ("HERMES_KANBAN_DB", "HERMES_KANBAN_HOME", "HERMES_PROFILE", "HERMES_KANBAN_TASK"):
        os.environ.pop(key, None)
    write_yaml(home / "config.yaml", {"model": fixture_model, "approvals": config.get("approvals", {})})
    project = output / "project"
    project.mkdir()
    for relative, content in case.get("files", {"README.md": "Isolated role-skill evaluation fixture.\n"}).items():
        file = project / relative
        if not file.resolve().is_relative_to(project):
            raise ValueError("fixture file outside project")
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content)
    limits = {"max_iterations": 24, "run_budget_seconds": 240, "max_tokens": 4096}
    import hermes_cli.kanban_db as kb
    meta = {"model": model["default"], "provider": model.get("provider"), "reasoning": reasoning,
            "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "limits": limits, "source": str(source), "hermes_revision": subprocess.check_output(
                ["git", "-C", str(Path(kb.__file__).parents[1]), "rev-parse", "HEAD"], text=True).strip()}
    meta["source_hashes"] = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                             for root in (source / "souls", source / "skills", source / "scripts")
                             for p in sorted(root.rglob("*")) if p.is_file() and p.suffix in {".md", ".py"}}
    dump(output / "conditions.json", meta)
    if role == "architect":
        prompt = conversation.PROMPT
        if hasattr(conversation, "workflow_skills"):
            prompt += "\n\n" + conversation.workflow_skills.architect_guidance()
        db = SessionDB(db_path=home / "state.db")
        agent = AIAgent(model=model["default"], **connection, **limits, reasoning_config=reasoning,
                        enabled_toolsets=[], skip_context_files=True, skip_memory=True,
                        skip_background_review=True, quiet_mode=True, cwd=str(project),
                        platform="workflow-controller", session_id="role-skill-evaluation", session_db=db)
        try:
            started = time.monotonic()
            result = agent.run_conversation(case["prompt"], system_message=prompt)
            recorded = {"response": result.get("final_response"), "error": result.get("error"),
                        "elapsed": time.monotonic() - started}
            dump(output / "result.json", recorded)
            try:
                recorded["decoded"] = conversation.decode(result.get("final_response", ""))
            except (ValueError, TypeError) as exc:
                recorded["protocol_error"] = str(exc)
            dump(output / "result.json", recorded)
        finally:
            agent.close()
            db.close()
        return

    # The fixture alone is committed to support the existing immutable clone gate.
    # Agents are still forbidden to commit their candidate.
    subprocess.run(["git", "init", "--quiet", str(project)], check=True)
    subprocess.run(["git", "-C", str(project), "add", "."], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Evaluation Fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "--quiet", "-m", "fixture"], check=True)
    for worker_role in wc.ROLES:
        directory = home / "profiles" / worker_role
        base_config = read_yaml(original_home / "profiles" / worker_role / "config.yaml")
        tools = base_config.get("platform_toolsets", {}).get("cli", base_config.get("toolsets", []))
        write_yaml(directory / "config.yaml", {
            "model": fixture_model, "approvals": base_config.get("approvals", {}), "toolsets": tools,
            "platform_toolsets": {"cli": tools}, "kanban": {"dispatch_in_gateway": False},
            "terminal": {"backend": "docker", "docker_image": case["image"],
                         "docker_mount_cwd_to_workspace": False, "container_cpu": 1, "container_memory": 1024},
        })
        shutil.copyfile(source / "souls" / (worker_role + ".md"), directory / "SOUL.md")
    workflow = wc.Workflow(home, {"PROJECT_DIR": str(project), "OUTPUT_DIR": str(output / "outputs"),
        "BOARD_SLUG": "default", "DOCKER_IMAGE": case["image"], "WORKFLOW_TEST_COMMAND": case["test_command"]})
    meta.update(worker_conditions={}, network=False,
                image_id=subprocess.check_output(["docker", "image", "inspect", case["image"],
                                                   "--format", "{{.Id}}"], text=True).strip())
    dump(output / "conditions.json", meta)
    # Same seam as the existing offline integration suite; workers below are real.
    with patch.object(wc.workflow_runtime, "dispatch", return_value={"spawned": []}), \
            patch.object(workflow, "notify"):
        manifest = workflow.submit(case["prompt"], notify=False)
        execution = manifest["execution_id"]
        workflow.approve(execution)
        # Prerequisites are actually checked; do not mock model or Docker readiness.
        readiness = workflow.readiness(execution)
        # Credentials are deliberately memory-only, so profile readiness cannot
        # see them. Record that distinction; all other checks must be ready.
        dump(output / "readiness.json", readiness)
        if any(not item["ready"] for item in readiness["checks"] if item["code"] not in wc.ROLES):
            raise RuntimeError("evaluation runtime not ready")
        with patch.object(workflow, "readiness", return_value={"ready": True, "checks": readiness["checks"]}):
            workflow.advance(execution)
        from hermes_cli import kanban_db as kb
        from gateway.session_kanban import _run_task_turns
        from tools.terminal_scope import install_and_reset_profile_terminal_scope
        from tools.terminal_tool import _get_env_config, terminal_tool
        results = []
        for worker_role in wc.ROLES:
            row = workflow.load(execution)["rounds"][-1]
            with wc.workflow_runtime.connect_closing(board="default") as conn:
                kb.recompute_ready(conn)
                task = kb.get_task(conn, row["tasks"][worker_role])
                if task.status not in {"todo", "ready"}:
                    results.append({"role": worker_role, "not_run": task.status})
                    dump(output / "results.json", results)
                    break
                kb.claim_task(conn, task.id)
                task = kb.get_task(conn, task.id)
                run = kb.latest_run(conn, task.id)
                context = kb.build_worker_context(conn, task.id)
                db_path = kb.kanban_db_path(board="default")
            profile = home / "profiles" / task.assignee
            scoped = read_yaml(profile / "config.yaml")
            tools = scoped["platform_toolsets"]["cli"]
            meta["worker_conditions"][worker_role] = {
                "toolsets": [*tools, "kanban"], "terminal": scoped["terminal"], "skills": task.skills or [],
            }
            dump(output / "conditions.json", meta)
            if case.get("omit_research") and worker_role == "builder":
                # Fault injection after a genuine research handoff, before the
                # builder reads it. Both variants receive the same missing file.
                (workflow.handoff_path(execution, 0) / "researcher/artifacts/DESIGN.md").unlink()
            env = {"HERMES_HOME": str(profile), "HERMES_PROFILE": task.assignee,
                   "HERMES_KANBAN_TASK": task.id, "HERMES_KANBAN_DB": str(db_path),
                   "HERMES_KANBAN_RUN_ID": str(run.id), "HERMES_KANBAN_CLAIM_LOCK": task.claim_lock,
                   "HERMES_KANBAN_WORKSPACE": task.workspace_path}
            session_id = f"evaluation-{worker_role}"
            with patch.dict(os.environ, env), wc.workflow_runtime.home_scope(profile), \
                    install_and_reset_profile_terminal_scope(profile), worker_session(task, session_id):
                if _get_env_config()["env_type"] != "docker":
                    raise RuntimeError("worker terminal policy was not bound")
                db = SessionDB(db_path=profile / "state.db")
                agent = AIAgent(model=model["default"], **connection, **limits, reasoning_config=reasoning,
                    enabled_toolsets=[*tools, "kanban"], skip_memory=True, skip_background_review=True,
                    quiet_mode=True, cwd=task.workspace_path, platform="cli",
                    session_id=session_id, session_db=db)
                try:
                    probe = json.loads(terminal_tool("pwd && test -d /handoff && test -d /output && "
                                                    "grep ' /candidate ' /proc/self/mountinfo",
                                                    workdir="/candidate", task_id=agent.session_id))
                    dump(output / (worker_role + "-container-probe.json"), probe)
                    lines = probe.get("output", "").splitlines()
                    expected = "rw" if worker_role == "builder" else "ro"
                    if (probe.get("exit_code") != 0 or len(lines) != 2 or lines[0] != "/candidate"
                            or lines[1].split()[5].split(",")[0] != expected):
                        raise RuntimeError("worker container paths or mount permissions differ from role policy")
                    started = time.monotonic()
                    result = _run_task_turns(agent, {"text": f"work kanban task {task.id}"}, [], {
                        "skills": task.skills or [], "context": context, "goal_mode": False, "task_id": task.id,
                        # This driver owns a genuine claim but is not an adopted
                        # managed worker. Native recovery must refuse its unbound
                        # claim; do not synthesize worker_bound proof for evaluation.
                        "db": str(db_path), "run_id": run.id, "claim_lock": task.claim_lock,
                    })
                    results.append({"role": worker_role, "response": result.get("final_response"),
                                    "error": result.get("error"), "elapsed": time.monotonic() - started})
                finally:
                    agent.close()
                    db.close()
            dump(output / "results.json", results)
            workflow.advance(execution)
        dump(output / "final.json", workflow.status(execution))


if __name__ == "__main__":
    main()
