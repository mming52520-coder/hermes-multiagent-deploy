#!/usr/bin/env python3
"""Operator-side P0 adapter. Hermes owns tasks, scheduling, claims and recovery.

Manifests bind an execution to inputs and evidence, not a second task database.
This directory must never be mounted into Worker containers.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import time

if __package__:
    from .configure_profiles import load_env_file, read_yaml, worker_mounts, write_yaml
    from .hermes_baseline import verify_workflow_source as verify_source
    from . import workflow_runtime, workflow_policy, workflow_notify
else:
    from configure_profiles import load_env_file, read_yaml, worker_mounts, write_yaml
    from hermes_baseline import verify_workflow_source as verify_source
    import workflow_runtime, workflow_policy, workflow_notify

LEGACY_ROLES = ("researcher", "builder", "reviewer", "orchestrator")
ROLES = ("researcher", "builder", "tester", "reviewer")
CURRENT_WORKFLOW_VERSION = 2
FAILURE_KINDS = {"implementation", "test", "environment", "api_model", "permission", "requirements"}


class Rejected(ValueError):
    pass


SEVERITIES = {"blocker", "minor"}


def review_verdict(metadata: dict) -> str | None:
    """Derive the effective Reviewer verdict from graded findings.

    Graded findings are objects with ``severity`` blocker/minor. Any blocker
    means FAIL and only blockers can cause FAIL, so minor or style notes cannot
    trigger another repair round. Ungraded (legacy) findings keep the reported
    verdict unchanged.
    """
    findings = metadata.get("findings")
    graded = [item for item in findings if isinstance(item, dict) and item.get("severity") in SEVERITIES] \
        if isinstance(findings, list) else []
    if not graded:
        return metadata.get("verdict")
    return "FAIL" if any(item["severity"] == "blocker" for item in graded) else "PASS"


def blocker_findings(metadata: dict) -> list:
    findings = metadata.get("findings")
    if not isinstance(findings, list):
        return findings
    graded = [item for item in findings if isinstance(item, dict) and item.get("severity") in SEVERITIES]
    return [item for item in graded if item["severity"] == "blocker"] if graded else findings


def git(path: Path, *args: str) -> str:
    # An edited .git/config must not execute an fsmonitor or an external diff.
    return subprocess.check_output(
        ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
         "-C", str(path), *args], text=True, stderr=subprocess.PIPE,
    ).strip()


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def tree_files(path: Path) -> dict[str, str]:
    files = {}
    for file in sorted(path.rglob("*")):
        relative = file.relative_to(path)
        if ".git" in relative.parts:
            continue
        if file.is_symlink():
            files[str(relative)] = digest(["link", os.readlink(file)])
        elif file.is_file():
            with file.open("rb") as stream:
                content = hashlib.file_digest(stream, "sha256").hexdigest()
            files[str(relative)] = digest([file.stat().st_mode & 0o777, content])
    return files


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(data, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")
    temporary.chmod(0o600)
    temporary.replace(path)


def independent_clone(source: Path, target: Path, revision: str) -> None:
    subprocess.run(["git", "clone", "--quiet", "--no-hardlinks", "--no-checkout",
                    "--", str(source), str(target)], check=True, capture_output=True)
    git(target, "checkout", "--quiet", "--detach", revision)


def execution_identity(goal: str, revision: str, instance: str = "") -> str:
    return digest([goal, revision, instance])[:32]


class Workflow:
    def __init__(self, root: Path, env: dict):
        from hermes_cli import kanban_db
        self.kb = kanban_db
        self.root = root.resolve()
        self.env = env
        self.project = Path(env["PROJECT_DIR"]).resolve()
        self.board = env["BOARD_SLUG"]
        self.store = self.root / "workflow" / "executions"
        exposed_paths = [self.project]
        if env.get("OUTPUT_DIR"):
            exposed_paths.append(Path(env["OUTPUT_DIR"]).resolve())
        for exposed in exposed_paths:
            operator = self.store.parent
            if exposed.is_relative_to(operator) or operator.is_relative_to(exposed):
                raise Rejected("project and output must not expose operator records")
        self.store.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, execution: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", execution):
            raise Rejected("invalid execution ID")
        return self.store / execution

    @contextmanager
    def locked(self, execution: str):
        directory = self.path(execution)
        directory.mkdir(exist_ok=True, mode=0o700)
        with (directory / "operator.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield directory

    def load(self, execution: str) -> dict:
        manifest = json.loads((self.path(execution) / "execution.json").read_text(encoding="utf-8"))
        if manifest["project"] != str(self.project) or manifest["board"] != self.board:
            raise Rejected("execution belongs to another project or board")
        return manifest

    def save(self, manifest: dict) -> None:
        path = self.path(manifest["execution_id"]) / "execution.json"
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            previous = {}
        manifest["transitions"] = list(previous.get("transitions", []))
        if previous.get("workflow_state") != manifest.get("workflow_state"):
            transition = {"from": previous.get("workflow_state"), "to": manifest.get("workflow_state"),
                          "round": manifest["rounds"][-1]["number"], "at": time.time()}
            if transition["to"] == "REPAIR_REQUIRED":
                receipt = self.path(manifest["execution_id"]) / f"round-{transition['round']}" / "platform-verification.json"
                if receipt.is_file():
                    transition["verification"] = json.loads(receipt.read_text()).get("status")
            manifest["transitions"].append(transition)
        write_json(path, manifest)

    @staticmethod
    def roles(manifest: dict | None = None) -> tuple[str, ...]:
        return ROLES if manifest is None or manifest.get("workflow_version", 1) >= 2 else LEGACY_ROLES

    @staticmethod
    def modern(manifest: dict) -> bool:
        return manifest.get("workflow_version", 1) >= 2

    def timing(self, manifest: dict, conn, at_time: float | None = None) -> dict:
        now = time.time() if at_time is None else at_time
        intervals = []
        tasks = {task for row in manifest["rounds"] for task in row["tasks"].values()}
        for task in tasks:
            for run in self.kb.list_runs(conn, task):
                intervals.append((run.started_at, min(run.ended_at or now, now)))
        for row in manifest["rounds"]:
            if row.get("verification_intervals"):
                intervals.extend((start, min(stop or now, now)) for start, stop in row["verification_intervals"])
            elif row.get("verification_started_at"):
                intervals.append((row["verification_started_at"], min(row.get("verification_finished_at") or now, now)))
        running, end = 0.0, 0.0
        for start, stop in sorted(intervals):
            running += max(0, stop - max(start, end))
            end = max(end, stop)
        return {"running_seconds": running,
                "waiting_seconds": max(0, now - manifest["created_at"] - running)}

    def budget(self, manifest: dict, conn, at_time: float | None = None, new_work: bool = False) -> None:
        policy = manifest["budget"]
        elapsed = (self.timing(manifest, conn, at_time)["running_seconds"] if self.modern(manifest)
                   else (time.time() if at_time is None else at_time) - manifest["created_at"])
        if elapsed >= policy["max_seconds"]:
            raise Rejected("TIME_BUDGET: operator action requires human intervention")
        tasks = {task for row in manifest["rounds"] for task in row["tasks"].values()}
        attempts = sum(len(self.kb.list_runs(conn, task)) for task in tasks)
        if attempts > policy["max_runs"] or (new_work and attempts >= policy["max_runs"]):
            raise Rejected("RUN_BUDGET: no new work allowed")
        # v0.18.2 task runs have no authoritative actual API billing field.
        # Never convert model-provided metadata or an estimate into a bill.
        if policy["max_cost_usd"] is not None:
            raise Rejected("COST_UNAVAILABLE: this Hermes baseline cannot enforce a hard API cost cap")

    def output_path(self, execution: str, number: int, role: str) -> Path:
        return Path(self.env["OUTPUT_DIR"]).resolve() / execution / str(number) / role

    def handoff_path(self, execution: str, number: int) -> Path:
        return Path(self.env["OUTPUT_DIR"]).resolve() / execution / f"handoff-{number}"

    def scoped_profile(self, role: str, execution: str, round_number: int, workspace: Path, writable: bool = False) -> str:
        from hermes_cli.profiles import create_profile, get_profile_dir
        name = f"{role}-{execution[:16]}-{round_number}"
        profile = get_profile_dir(name)
        if not profile.exists():
            create_profile(name, clone_from=role, no_alias=True)
            if self.modern(self.load(execution)):
                souls = Path(__file__).resolve().parent / "souls"
                if not souls.is_dir():
                    souls = Path(__file__).resolve().parents[1] / "souls"
                soul = souls / f"{role}.md"
                shutil.copyfile(soul, profile / "SOUL.md")
        config = read_yaml(profile / "config.yaml")
        config.setdefault("terminal", {})
        config.setdefault("platform_toolsets", {})
        if role == "orchestrator":
            config["toolsets"] = ["kanban","memory","session_search","todo","clarify","skills"]
            config["platform_toolsets"]["cli"] = list(config["toolsets"])
        else:
            output = self.output_path(execution, round_number, role)
            output.mkdir(parents=True, exist_ok=True, mode=0o700)
            handoff = self.handoff_path(execution, round_number)
            handoff.mkdir(parents=True, exist_ok=True, mode=0o700)
            config["terminal"].update({
                "backend":"docker",
                "cwd": "/candidate",
                "docker_mount_cwd_to_workspace": False,
                "docker_volumes": worker_mounts(
                    role if writable else "reviewer", self.project, self.root / "kanban", output, workspace
                ),
                "docker_persist_across_processes": False,
                "docker_extra_args":[], "docker_forward_env":[],
                "docker_env":{"CI":"1","PYTHONUNBUFFERED":"1"},
                "docker_network":False, "docker_run_as_host_user":True,
                "docker_orphan_reaper":False,
            })
            config["terminal"]["docker_volumes"].extend([f"{output}:/output:rw", f"{handoff}:/handoff:ro"])
            # Delegated children could otherwise share this one writable clone.
            for key in ("toolsets",):
                config[key] = [tool for tool in config.get(key, []) if tool not in {"delegation", "code_execution"}]
            config["platform_toolsets"]["cli"] = list(config["toolsets"])
        write_yaml(profile / "config.yaml", config)
        return name

    def new_round(self, manifest: dict, conn, parent: str | None = None) -> dict:
        number = len(manifest["rounds"])
        directory = self.path(manifest["execution_id"]) / f"round-{number}"
        directory.mkdir(exist_ok=True, mode=0o700)
        candidate = self.path(manifest["execution_id"]) / "candidate"
        review = directory / "review"
        if not review.exists():
            if self.modern(manifest) and number:
                # Repairs start from the last failed candidate, including its
                # uncommitted feature files. Tester must see that baseline.
                shutil.copytree(candidate, review, symlinks=True)
            else:
                independent_clone(candidate, review, git(candidate, "rev-parse", "HEAD"))
        row = {"number": number, "tasks": {}, "candidate": str(candidate), "review": str(review), "parent":parent}
        if number:
            row["tasks"]["researcher"] = manifest["rounds"][0]["tasks"]["researcher"]
        # Persist each native ID immediately. Native idempotency handles a crash
        # between create_task and this write; completed IDs stay in the manifest.
        # Revoke the previous round's grant before persisting or creating cards.
        manifest["approved_write"] = False
        if self.modern(manifest):
            manifest["workflow_state"] = "WAITING_APPROVAL"
        manifest["rounds"].append(row)
        self.save(manifest)
        self.populate_round(manifest, row, conn, parent)
        return row

    def populate_round(self, manifest: dict, row: dict, conn, parent: str | None = None) -> None:
        execution = manifest["execution_id"]
        previous = row.get("parent") or parent
        for role in self.roles(manifest):
            if role in row["tasks"]:
                if not (role == "researcher" and row["number"]):
                    previous = row["tasks"][role]
                continue
            workspace = Path(row["review"] if role in {"tester", "reviewer"} else row["candidate"])
            profile = self.scoped_profile(role, execution, row["number"], workspace)
            body = (
                f"Objective: {manifest['objective']}\nExecution ID: {execution}\n"
                f"Source revision: {manifest['source_revision']}\nRole: {role}\n"
                "Container cwd /candidate aliases the task's host workspace.\n"
                "Read all parent handoffs. Never commit, push, merge, deploy, or access hardware.\n"
            )
            if not self.modern(manifest):
                body += ("Return execution_id, source_revision, candidate_revision, candidate_digest, "
                         "evidence_refs, blockers, residual_risks in completion metadata.\n")
            if role == "builder":
                body += ("Modify only this candidate. Include "
                         + ("round_changed_files" if self.modern(manifest) else "real changed_files")
                         + " and verification commands/results.\n")
            elif role == "reviewer":
                body += "Read-only review of the operator-prepared candidate snapshot. Include verdict PASS/FAIL and findings.\n"
            elif role == "orchestrator":
                body += "Summarize evidence only. Kanban done is NOT acceptance. Do not create unbounded repair cards.\n"
            if self.modern(manifest):
                body += (
                    "Read /handoff for upstream reports and owner-bound result.json. Write persistent reports/artifacts to /output.\n"
                    "Completion metadata: verification (commands/results), findings, evidence_refs, residual_risks. "
                    "The owner records immutable execution/source/candidate identity and cumulative changed_files; do not calculate them.\n"
                )
                if row["number"]:
                    body += (
                        "Repair round: read /handoff/repair/result.json, any platform-verification.log and reviewer report. "
                        "The previous independent failing tests are in /handoff/repair/independent-tests. "
                        "Address the concrete findings; do not rely on the user to copy them into this task.\n"
                    )
                if role == "researcher":
                    body += "Write /output/DESIGN.md with requirements, observable outputs and an acceptance-scenario matrix.\n"
                    recorded = workflow_policy.read_decisions(self.root, self.board, limit=3000)
                    if any(recorded.values()):
                        body += ("Human decisions already made for this project (follow them; do not re-ask; "
                                 "if the objective conflicts with one, say so in DESIGN.md):\n"
                                 + recorded["approved"] + "\n" + recorded["rejected"] + "\n")
                elif role == "tester":
                    body += (
                        "In parallel with Builder, design independent acceptance tests from the Researcher handoff. "
                        "The baseline /candidate is read-only. Write actual Python unittest test_*.py files under /output/tests "
                        "and a report /output/TEST_DESIGN.md. Tests execute later from the finished candidate cwd; "
                        "use pathlib.Path.cwd() for candidate files, not report locations. "
                        "Baseline failures for unimplemented requirements are expected; report status TESTS_READY when tests are ready. "
                        "Do not rerun the complete project suite; the platform runs it once with your tests on the frozen candidate.\n"
                    )
                elif role == "reviewer":
                    body += (
                        "Review /handoff/platform verification and the independent tests, inspect the frozen code, "
                        "including the exact executed files at /handoff/platform/independent-tests. "
                        "Run only additional focused probes needed for concrete gaps. Reuse the complete platform test receipt. "
                        "Grade each finding severity blocker or minor; style suggestions are not findings. "
                        "Return verdict FAIL only for blocker findings, otherwise PASS, with findings and verification.\n"
                    )
            parents = [previous] if previous else []
            if self.modern(manifest):
                if role in {"builder", "tester"}:
                    parents = [row.get("parent") or row["tasks"]["researcher"]]
                elif role == "reviewer":
                    parents = [row["tasks"]["builder"], row["tasks"]["tester"]]
            tid = self.kb.create_task(
                conn, title=f"{role}: {manifest['objective']}", body=body, assignee=profile,
                parents=parents, triage=True,
                workspace_kind="dir", workspace_path=str(workspace),
                idempotency_key=f"{execution}:{row['number']}:{role}",
                max_runtime_seconds={"researcher":1200,"builder":3600,"tester":1800,"reviewer":1800,"orchestrator":900}[role],
                max_retries=1, board=self.board,
            )
            row["tasks"][role] = tid
            self.save(manifest)
            previous = tid

    def submit(self, objective: str, instance: str = "") -> dict:
        for key in ("OUTPUT_DIR", "DOCKER_IMAGE"):
            if not self.env.get(key):
                raise Rejected(f"项目绑定配置缺少 {key}")
        revision = git(self.project, "rev-parse", "HEAD")
        execution = execution_identity(objective, revision, instance)
        with self.locked(execution):
            manifest_file = self.path(execution) / "execution.json"
            with workflow_runtime.connect_closing(board=self.board) as conn:
                if manifest_file.exists():
                    manifest = self.load(execution)
                    if manifest["rounds"]:
                        self.populate_round(manifest, manifest["rounds"][-1], conn)
                    return manifest
                if CURRENT_WORKFLOW_VERSION >= 2:
                    if __package__:
                        from .workflow_models import ensure_profiles
                    else:
                        from workflow_models import ensure_profiles
                    ensure_profiles(self, list(ROLES))
                if git(self.project, "status", "--porcelain"):
                    raise Rejected("source has uncommitted changes; preserve them and choose a clean source snapshot")
                candidate = self.path(execution) / "candidate"
                if not candidate.exists():
                    independent_clone(self.project, candidate, revision)
                manifest = {
                    "workflow_version": CURRENT_WORKFLOW_VERSION,
                    "execution_id":execution, "instance":instance, "objective":objective, "project":str(self.project),
                    "board":self.board, "source_revision":revision, "source_files":tree_files(candidate),
                    "created_at":time.time(), "rounds":[], "failures":[], "approved_write":False,
                    "test_command":self.env.get("WORKFLOW_TEST_COMMAND", ""),
                    "image":self.env["DOCKER_IMAGE"],
                    "budget":{
                        "max_rounds":int(self.env.get("WORKFLOW_MAX_REPAIR_ROUNDS", "2")),
                        "max_seconds":int(self.env.get("WORKFLOW_MAX_SECONDS", "7200")),
                        "max_runs":int(self.env.get("WORKFLOW_MAX_RUNS", "12")),
                        "max_cost_usd":self.env.get("WORKFLOW_MAX_COST_USD") or None,
                    },
                    # Snapshot: later env edits never widen an existing execution's scope.
                    "policy":workflow_policy.policy_from_env(self.env),
                }
                self.new_round(manifest, conn)
                return manifest

    def start(self, execution: str, approve_write: bool, *, approved_round: int | None = None) -> dict:
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if approved_round is not None and (not manifest["approved_write"] or manifest["rounds"][-1]["number"] != approved_round):
                raise Rejected("WRITE_NOT_APPROVED: the current round requires fresh approval")
            self.budget(manifest, conn, new_work=True)
            if not approve_write:
                raise Rejected("WRITE_NOT_APPROVED: explicit operator --approve-write required")
            if not manifest["test_command"].strip():
                raise Rejected("configure a meaningful WORKFLOW_TEST_COMMAND before authorizing work")
            row = manifest["rounds"][-1]
            if "candidate_digest" in row:
                raise Rejected("review already prepared; use a new repair round for further changes")
            if not manifest["approved_write"]:
                if any(self.kb.get_task(conn,tid).status == "running" for tid in row["tasks"].values()):
                    raise Rejected("a worker is already running; do not change its mounted permissions")
                self.scoped_profile("builder",execution,row["number"],Path(row["candidate"]),writable=True)
                manifest["approved_write"] = True
                self.save(manifest)
            # A retried start only releases remaining triage cards. It must not
            # rewrite a profile that a previously released worker is using.
            for role in (("researcher",) if self.modern(manifest) else ("researcher", "builder")):
                self.kb.specify_triage_task(conn,row["tasks"][role],author="operator")
            return manifest

    def approve(self, execution: str, *, expected_round: int | None = None) -> dict:
        """Grant this round only; keep every native card in triage until launch."""
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if expected_round is not None and manifest["rounds"][-1]["number"] != expected_round:
                raise Rejected("ROUND_CHANGED: review the current round before approving")
            if manifest.get("workflow_state") == "REJECTED":
                raise Rejected("这项任务已决定不做；如需重做请新建任务。")
            self.budget(manifest, conn, new_work=True)
            row = manifest["rounds"][-1]
            if "candidate_digest" in row:
                raise Rejected("review already prepared; use a new repair round for further changes")
            if not manifest["approved_write"]:
                if any(self.kb.get_task(conn, tid).status == "running" for tid in row["tasks"].values()):
                    raise Rejected("a worker is already running; do not change its mounted permissions")
                self.scoped_profile("builder", execution, row["number"], Path(row["candidate"]), writable=True)
                manifest["approved_write"] = True
                manifest["approval"] = {"at": time.time(), "source_revision": manifest["source_revision"], "round": row["number"]}
                self.save(manifest)
                self.kb.add_comment(conn, row["tasks"]["researcher"], author="operator", body="Human approval recorded; execution has not been started.")
            return manifest

    def readiness(self, execution: str | None = None) -> dict:
        with workflow_runtime.home_scope(self.root):
            manifest = self.load(execution) if execution else None
            result = workflow_runtime.readiness(self, manifest)
            try:
                revision = git(self.project, "rev-parse", "HEAD")
                clean = not git(self.project, "status", "--porcelain")
                source_ready = clean and (manifest is None or revision == manifest["source_revision"])
            except (OSError, subprocess.CalledProcessError):
                revision = None
                source_ready = False
            result["checks"].insert(0, {"code": "project", "label": "项目源版本", "ready": source_ready,
                                       "revision": revision,
                                       "detail": "使用干净且版本一致的项目；候选修改保存在独立副本。"})
            result["ready"] = result["ready"] and source_ready
            return result

    def launch(self, execution: str, *, expected_round: int | None = None) -> dict:
        # Readiness is checked before releasing cards; failed checks leave them in triage.
        manifest = self.load(execution)
        if expected_round is not None and manifest["rounds"][-1]["number"] != expected_round:
            raise Rejected("ROUND_CHANGED: review the current round before launching")
        if not manifest["approved_write"]:
            raise Rejected("WRITE_NOT_APPROVED")
        checks = self.readiness(execution)
        if not checks["ready"]:
            missing = "; ".join(item["label"] + ": " + item["detail"] for item in checks["checks"] if not item["ready"])
            raise Rejected("EXECUTION_NOT_READY: " + missing)
        number = manifest["rounds"][-1]["number"]
        if "candidate_digest" not in manifest["rounds"][-1]:
            self.start(execution, approve_write=True, approved_round=number)
        else:
            with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
                current = self.load(execution)
                if not current["approved_write"] or current["rounds"][-1]["number"] != number:
                    raise Rejected("WRITE_NOT_APPROVED")
                self.budget(current, conn)
        result = workflow_runtime.dispatch(self)
        return {"execution_id": execution, "dispatch": result}

    def completed_metadata(self, conn, task: str) -> dict:
        item = self.kb.get_task(conn, task)
        run = self.kb.latest_run(conn, task)
        if item is None or item.status not in {"done","archived"} or run is None or run.outcome != "completed":
            raise Rejected(f"task is not successfully completed: {task}")
        return json.loads(run.metadata or "{}") if isinstance(run.metadata, str) else (run.metadata or {})

    def result_metadata(self, manifest: dict, row: dict, role: str, conn) -> dict:
        raw = self.completed_metadata(conn, row["tasks"][role])
        if not self.modern(manifest):
            return raw
        metadata = dict(raw)
        metadata["verification"] = raw.get("verification", raw.get("commands_run", []))
        if role == "reviewer":
            metadata["reported_verdict"] = raw.get("verdict")
            metadata["verdict"] = review_verdict(raw)
        metadata.update({"schema_version": 2, "execution_id": manifest["execution_id"],
                         "task_id": row["tasks"][role], "run_id": self.kb.latest_run(conn, row["tasks"][role]).id,
                         "source_revision": manifest["source_revision"],
                         "candidate_revision": row.get("candidate_revision", manifest["source_revision"]),
                         "candidate_digest": row.get("candidate_digest", digest(manifest["source_files"]))})
        if role == "builder" and "candidate_files" in row:
            metadata["round_changed_files"] = raw.get("round_changed_files", raw.get("changed_files", []))
            metadata["changed_files"] = sorted(
                key for key in row["candidate_files"].keys() | manifest["source_files"].keys()
                if row["candidate_files"].get(key) != manifest["source_files"].get(key))
        return metadata

    @staticmethod
    def publish_directory(bundle: Path, name: str, directory: Path) -> None:
        # Readers keep seeing the last complete generation while a new handoff
        # is prepared. Only the relative pointer is replaced atomically.
        pointer = bundle / f".{name}.next"
        pointer.unlink(missing_ok=True)
        pointer.symlink_to(directory.name, target_is_directory=True)
        pointer.replace(bundle / name)

    def publish_handoff(self, manifest: dict, row: dict, role: str, conn) -> None:
        if not self.modern(manifest):
            return
        metadata = self.result_metadata(manifest, row, role, conn)
        identity = [metadata["run_id"], metadata["candidate_digest"]]
        if row.get("handoffs", {}).get(role) == identity:
            return
        bundle = self.handoff_path(manifest["execution_id"], row["number"])
        bundle.mkdir(parents=True, exist_ok=True, mode=0o700)
        generation = bundle / f".{role}-{metadata['run_id']}-{metadata['candidate_digest'][:12]}"
        generation.mkdir(exist_ok=True, mode=0o700)
        source_round = 0 if role == "researcher" else row["number"]
        output = self.output_path(manifest["execution_id"], source_round, role)
        if role == "researcher" and not (output / "DESIGN.md").is_file():
            raise Rejected("Researcher must write the design handoff to /output/DESIGN.md")
        shutil.copytree(output, generation / "artifacts", symlinks=True, dirs_exist_ok=True)
        write_json(generation / "raw-result.json", self.completed_metadata(conn, row["tasks"][role]))
        write_json(generation / "result.json", metadata)
        self.publish_directory(bundle, role, generation)
        row.setdefault("handoffs", {})[role] = identity
        self.save(manifest)

    def publish_repair_handoff(self, manifest: dict, row: dict, conn) -> None:
        if not row["number"] or row.get("repair_handoff_ready"):
            return
        previous = manifest["rounds"][row["number"] - 1]
        old_directory = self.path(manifest["execution_id"]) / f"round-{previous['number']}"
        receipt_file = old_directory / "platform-verification.json"
        result = {"previous_round":previous["number"], "candidate_digest":previous["candidate_digest"],
                  "candidate_revision":previous["candidate_revision"],
                  "operator_request":manifest["failures"][-1]}
        if receipt_file.is_file():
            result["platform"] = json.loads(receipt_file.read_text(encoding="utf-8"))
        review = self.kb.get_task(conn, previous["tasks"]["reviewer"])
        review_run = self.kb.latest_run(conn, review.id)
        if review.status in {"done","archived"} and review_run and review_run.outcome == "completed":
            result["reviewer"] = self.result_metadata(manifest, previous, "reviewer", conn)
        bundle = self.handoff_path(manifest["execution_id"], row["number"])
        generation = bundle / f".repair-{previous['number']}-{digest(result)[:12]}"
        generation.mkdir(exist_ok=True, mode=0o700)
        write_json(generation / "result.json", result)
        for name in ("platform-verification.json", "platform-verification.log"):
            if (old_directory / name).is_file():
                shutil.copyfile(old_directory / name, generation / name)
        tests = old_directory / "independent-tests"
        if tests.is_dir():
            shutil.copytree(tests, generation / "independent-tests", symlinks=True, dirs_exist_ok=True)
        reviewer_output = self.output_path(manifest["execution_id"], previous["number"], "reviewer")
        if reviewer_output.is_dir():
            shutil.copytree(reviewer_output, generation / "reviewer-report", symlinks=True, dirs_exist_ok=True)
        self.publish_directory(bundle, "repair", generation)
        row["repair_handoff_ready"] = True
        self.save(manifest)

    def prepare_review(self, execution: str) -> dict:
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            self.budget(manifest, conn)
            row = manifest["rounds"][-1]
            if not manifest["approved_write"]:
                raise Rejected("WRITE_NOT_APPROVED")
            self.completed_metadata(conn, row["tasks"]["builder"])
            if self.modern(manifest):
                self.completed_metadata(conn, row["tasks"]["tester"])
            reviewer = self.kb.get_task(conn, row["tasks"]["reviewer"])
            candidate, review = Path(row["candidate"]), Path(row["review"])
            if (candidate / ".git").is_symlink() or not (candidate / ".git").is_dir():
                raise Rejected("candidate lost its independent Git metadata")
            if "candidate_digest" in row:
                # Resume a partial release without replacing a published copy.
                if any(git(path,"rev-parse","HEAD") != row["candidate_revision"]
                       or digest(tree_files(path)) != row["candidate_digest"] for path in (candidate,review)):
                    raise Rejected("candidate/review snapshot changed after preparation")
            else:
                if reviewer.status != "triage":
                    raise Rejected("review already released; do not replace its candidate snapshot")
                revision, files = git(candidate,"rev-parse","HEAD"), tree_files(candidate)
                # Only replace our own unpublished, per-round snapshot.
                shutil.rmtree(review)
                shutil.copytree(candidate, review, symlinks=True)
                if any(git(path,"rev-parse","HEAD") != revision or tree_files(path) != files
                       for path in (candidate,review)):
                    raise Rejected("candidate/review snapshot changed during preparation")
                row["candidate_revision"] = revision
                row["candidate_files"] = files
                row["candidate_digest"] = digest(files)
                self.save(manifest)
            if self.modern(manifest):
                tests = self.path(execution) / f"round-{row['number']}" / "independent-tests"
                if not tests.exists():
                    source_tests = self.output_path(execution, row["number"], "tester") / "tests"
                    if source_tests.is_symlink() or not source_tests.is_dir() or not any(source_tests.rglob("test*.py")):
                        raise Rejected("Tester must deliver independent Python unittest files in /output/tests")
                    temporary = tests.with_name(".independent-tests.tmp")
                    if temporary.exists():
                        shutil.rmtree(temporary)
                    shutil.copytree(source_tests, temporary, symlinks=True)
                    temporary.replace(tests)
                tests_digest = digest(tree_files(tests))
                if row.get("independent_tests_digest", tests_digest) != tests_digest:
                    raise Rejected("independent tests changed after snapshot")
                row["independent_tests_digest"] = tests_digest
                for role in ("researcher", "builder", "tester"):
                    self.publish_handoff(manifest, row, role, conn)
                self.save(manifest)
                row["snapshot_ready"] = True
                self.save(manifest)
                return manifest
            for role in ("reviewer", "orchestrator"):
                self.kb.specify_triage_task(conn,row["tasks"][role],author="operator")
            return manifest

    def verify(self, execution: str, role: str, runner=subprocess.run) -> dict:
        if role == "platform":
            return self.verify_platform(execution, runner)
        if self.modern(self.load(execution)):
            raise Rejected("workflow v2 uses one platform verification receipt")
        if role not in {"builder", "reviewer"}:
            raise Rejected("only builder and reviewer have verification receipts")
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            self.budget(manifest, conn)
            row = manifest["rounds"][-1]
            self.completed_metadata(conn, row["tasks"][role])
            if "candidate_digest" not in row:
                raise Rejected("prepare-review must freeze a candidate before verification")
            source = Path(row["candidate"] if role == "builder" else row["review"])
            before = digest(tree_files(source))
            if before != row["candidate_digest"]:
                raise Rejected("candidate changed after snapshot")
            if not manifest["test_command"].strip():
                raise Rejected("missing verification command")
            remaining = manifest["budget"]["max_seconds"] - (time.time() - manifest["created_at"])
            timeout = max(1, min(900, int(remaining)))
            # A fresh, networkless native Docker container gets a read-only
            # input and private scratch. It cannot forge host receipts or edit
            # another role's checkout, even if the test command writes files.
            container_name = f"hermes-verify-{execution[:16]}-{role}-{time.time_ns()}"
            command = [
                "docker", "--host=unix:///var/run/docker.sock", "run", "--rm", "--pull=never",
                "--name",container_name,
                "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                "--pids-limit=256", "--cpus=1", "--memory=1024m", "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:rw,exec,mode=1777,size=512m",
                "--mount", f"type=bind,src={source},dst=/input,readonly",
                "--entrypoint", "/bin/sh", manifest["image"], "-c",
                'cp -a /input/. /tmp/candidate && cd /tmp/candidate && exec /bin/sh -c "$1"',
                "verification", manifest["test_command"],
            ]
            docker_env = {key:value for key,value in os.environ.items()
                          if key not in {"DOCKER_HOST","DOCKER_CONTEXT","DOCKER_TLS","DOCKER_TLS_VERIFY","DOCKER_CERT_PATH"}}
            try:
                result = runner(command, capture_output=True, text=True, timeout=timeout, env=docker_env)
                code, output = result.returncode, result.stdout + result.stderr
            except subprocess.TimeoutExpired:
                cleanup = runner(["docker","--host=unix:///var/run/docker.sock","rm","--force",container_name],
                                 capture_output=True,text=True,timeout=20,env=docker_env)
                code = 124
                output = "Verification timed out.\n"
                if cleanup.returncode:
                    output += f"NOT_VERIFIED: cleanup failed for {container_name}; operator inspection required.\n"
            if digest(tree_files(source)) != before:
                raise Rejected("candidate mutated during verification")
            run = self.kb.latest_run(conn, row["tasks"][role])
            directory = self.path(execution) / f"round-{row['number']}"
            log = directory / f"{role}-verification.log"
            log.write_text(output, encoding="utf-8")
            log.chmod(0o600)
            receipt = {
                "execution_id":execution, "task_id":row["tasks"][role], "run_id":run.id,
                "role":role, "candidate_revision":row["candidate_revision"], "candidate_digest":before,
                "command":manifest["test_command"], "exit_code":code, "status":"PASS" if code == 0 else "FAIL",
                "log_sha256":hashlib.sha256(log.read_bytes()).hexdigest(), "recorded_at":time.time(),
                "actual_api_cost_usd":None,
            }
            write_json(directory / f"{role}-verification.json", receipt)
            return receipt

    def verify_platform(self, execution: str, runner=subprocess.run) -> dict:
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if not self.modern(manifest):
                raise Rejected("legacy executions require separate builder/reviewer receipts")
            self.budget(manifest, conn)
            row = manifest["rounds"][-1]
            for role in ("builder", "tester"):
                self.completed_metadata(conn, row["tasks"][role])
            if "independent_tests_digest" not in row:
                raise Rejected("prepare-review must freeze the candidate and independent tests")
            directory = self.path(execution) / f"round-{row['number']}"
            source, tests = Path(row["review"]), directory / "independent-tests"
            if digest(tree_files(source)) != row["candidate_digest"] or digest(tree_files(tests)) != row["independent_tests_digest"]:
                raise Rejected("candidate or independent tests changed after snapshot")
            docker = ["docker", "--host=unix:///var/run/docker.sock"]
            docker_env = {key:value for key,value in os.environ.items()
                          if key not in {"DOCKER_HOST","DOCKER_CONTEXT","DOCKER_TLS","DOCKER_TLS_VERIFY","DOCKER_CERT_PATH"}}
            image = runner(docker + ["image", "inspect", "--format", "{{.Id}}", manifest["image"]],
                           capture_output=True, text=True, timeout=20, env=docker_env)
            if image.returncode or not image.stdout.strip():
                raise Rejected("configured verification image is not available locally")
            image_id = image.stdout.strip()
            independent_command = (
                "python -B -c 'import sys, unittest; "
                'suite=unittest.defaultTestLoader.discover("/independent-tests"); '
                'print("Independent test cases:", suite.countTestCases()); '
                "sys.exit(0 if suite.countTestCases() and unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)'"
            )
            command_text = f"{manifest['test_command']} && {independent_command}"
            environment = {"image_id": image_id, "network": "none", "cpus": 1, "memory_mb": 1024,
                           "user": f"{os.getuid()}:{os.getgid()}", "python_bytecode": False,
                           "cwd": "/tmp/candidate"}
            inputs = {"candidate_digest": row["candidate_digest"], "candidate_revision":row["candidate_revision"], "environment": environment,
                      "command": command_text, "independent_tests_digest": row["independent_tests_digest"]}
            evidence_key = digest(inputs)
            receipt_file, log = directory / "platform-verification.json", directory / "platform-verification.log"
            cache = self.path(execution) / "verification-cache"
            cache.mkdir(exist_ok=True, mode=0o700)
            cached_file, cached_log = cache / f"{evidence_key}.json", cache / f"{evidence_key}.log"
            receipt = None
            for saved, saved_log in ((receipt_file, log), (cached_file, cached_log)):
                if saved.is_file() and saved_log.is_file():
                    previous = json.loads(saved.read_text(encoding="utf-8"))
                    if (previous.get("evidence_key") == evidence_key and previous.get("status") == "PASS"
                            and previous.get("log_sha256") == hashlib.sha256(saved_log.read_bytes()).hexdigest()):
                        receipt = {**previous, "reused": True}
                        if saved_log != log:
                            shutil.copyfile(saved_log, log)
                        break
            if receipt is None:
                remaining = manifest["budget"]["max_seconds"] - self.timing(manifest, conn)["running_seconds"]
                timeout = max(1, min(900, int(remaining)))
                container_name = f"hermes-verify-{execution[:16]}-platform-{time.time_ns()}"
                command = docker + [
                    "run", "--rm", "--pull=never", "--name", container_name,
                    "--network=none", "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
                    "--pids-limit=256", "--cpus=1", "--memory=1024m", "--user", environment["user"],
                    "--tmpfs", "/tmp:rw,exec,mode=1777,size=512m", "--env", "PYTHONDONTWRITEBYTECODE=1",
                    "--mount", f"type=bind,src={source},dst=/input,readonly",
                    "--mount", f"type=bind,src={tests},dst=/independent-tests,readonly",
                    "--entrypoint", "/bin/sh", image_id, "-c",
                    'cp -a /input/. /tmp/candidate && cd /tmp/candidate && printf "Verification cwd: " && pwd -P && exec /bin/sh -c "$1"',
                    "verification", command_text,
                ]
                row["verification_started_at"] = time.time()
                row.pop("verification_finished_at", None)
                row.setdefault("verification_intervals", []).append([row["verification_started_at"], None])
                self.save(manifest)
                try:
                    result = runner(command, capture_output=True, text=True, timeout=timeout, env=docker_env)
                    code, output = result.returncode, result.stdout + result.stderr
                except subprocess.TimeoutExpired:
                    cleanup = runner(docker + ["rm", "--force", container_name],
                                     capture_output=True, text=True, timeout=20, env=docker_env)
                    code, output = 124, "Verification timed out.\n"
                    if cleanup.returncode:
                        output += f"NOT_VERIFIED: cleanup failed for {container_name}; operator inspection required.\n"
                row["verification_finished_at"] = time.time()
                row["verification_intervals"][-1][1] = row["verification_finished_at"]
                self.save(manifest)
                if digest(tree_files(source)) != row["candidate_digest"] or digest(tree_files(tests)) != row["independent_tests_digest"]:
                    raise Rejected("candidate or tests mutated during verification")
                log.write_text(output, encoding="utf-8")
                log.chmod(0o600)
                receipt = {**inputs, "evidence_key": evidence_key, "reused": False,
                           "exit_code": code, "status": "PASS" if code == 0 else "FAIL",
                           "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
                           "recorded_at": time.time(), "actual_api_cost_usd": None}
                if code == 0:
                    shutil.copyfile(log, cached_log)
                    write_json(cached_file, receipt)
            receipt.update({"execution_id": execution, "role": "platform", "round": row["number"],
                            "candidate_revision": row["candidate_revision"],
                            "runs": {role: self.kb.latest_run(conn, row["tasks"][role]).id for role in ("builder", "tester")}})
            write_json(receipt_file, receipt)
            row["verification_environment"] = environment
            row["verification_command"] = command_text
            row["verification_key"] = evidence_key
            bundle = self.handoff_path(execution, row["number"])
            generation = bundle / f".platform-{digest(receipt)[:16]}"
            generation.mkdir(exist_ok=True, mode=0o700)
            shutil.copyfile(log, generation / "verification.log")
            if not (generation / "independent-tests").exists():
                shutil.copytree(tests, generation / "independent-tests", symlinks=True)
            write_json(generation / "result.json", receipt)
            self.publish_directory(bundle, "platform", generation)
            self.save(manifest)
            return receipt

    def acceptance(self, manifest: dict, conn, at_time: float | None = None) -> dict:
        self.budget(manifest, conn, at_time=at_time)
        if not manifest["approved_write"]:
            raise Rejected("WRITE_NOT_APPROVED")
        row = manifest["rounds"][-1]
        if "candidate_digest" not in row:
            raise Rejected("candidate snapshot is missing")
        if git(self.project, "rev-parse", "HEAD") != manifest["source_revision"]:
            raise Rejected("source revision changed")
        if git(self.project,"status","--porcelain"):
            raise Rejected("original source now has uncommitted changes")
        candidate = Path(row["candidate"])
        if git(candidate, "rev-parse", "HEAD") != row["candidate_revision"]:
            raise Rejected("candidate revision changed")
        if git(Path(row["review"]), "rev-parse", "HEAD") != row["candidate_revision"]:
            raise Rejected("review revision mismatch")
        if any(digest(tree_files(Path(row[key]))) != row["candidate_digest"] for key in ("candidate","review")):
            raise Rejected("candidate/review content mismatch")
        current_files = row["candidate_files"]
        changed = sorted(key for key in current_files.keys() | manifest["source_files"].keys()
                         if current_files.get(key) != manifest["source_files"].get(key))
        if not changed:
            raise Rejected("no real code-change evidence")
        metadata = {role:self.result_metadata(manifest, row, role, conn) for role in row["tasks"]}
        if self.modern(manifest):
            if review_verdict(metadata["reviewer"]) != "PASS":
                raise Rejected("Reviewer did not return PASS")
            directory = self.path(manifest["execution_id"]) / f"round-{row['number']}"
            receipt_file, log = directory / "platform-verification.json", directory / "platform-verification.log"
            if not receipt_file.is_file() or not log.is_file():
                raise Rejected("missing operator platform verification receipt")
            receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            tests_digest = digest(tree_files(directory / "independent-tests"))
            inputs = {"candidate_digest":row["candidate_digest"], "candidate_revision":row["candidate_revision"], "environment":row["verification_environment"],
                      "command":row["verification_command"], "independent_tests_digest":tests_digest}
            expected = {**inputs, "execution_id":manifest["execution_id"], "role":"platform",
                        "round":row["number"], "candidate_revision":row["candidate_revision"],
                        "evidence_key":digest(inputs), "exit_code":0, "status":"PASS",
                        "runs":{role:self.kb.latest_run(conn,row["tasks"][role]).id for role in ("builder","tester")},
                        "log_sha256":hashlib.sha256(log.read_bytes()).hexdigest()}
            if tests_digest != row["independent_tests_digest"] or any(receipt.get(key) != value for key,value in expected.items()):
                raise Rejected("failed, stale, or altered platform verification receipt")
            return {"status":"ACCEPTED", "execution_id":manifest["execution_id"], "workflow_version":2,
                    "source_revision":manifest["source_revision"], "candidate_revision":row["candidate_revision"],
                    "candidate_digest":row["candidate_digest"], "changed_files":changed,
                    "policy_digest":digest([manifest["budget"],inputs]),
                    "verification_receipts":{"platform":digest(receipt)},
                    "accepted_at":time.time(), "actual_api_cost_usd":None}
        refs = {}
        for role in ("builder","reviewer"):
            md = metadata[role]
            for key,value in {"execution_id":manifest["execution_id"], "source_revision":manifest["source_revision"],
                              "candidate_revision":row["candidate_revision"], "candidate_digest":row["candidate_digest"]}.items():
                if md.get(key) != value:
                    raise Rejected(f"{role} handoff mismatch: {key}")
            if not md.get("verification"):
                raise Rejected(f"{role} missing verification handoff")
            directory = self.path(manifest["execution_id"]) / f"round-{row['number']}"
            receipt_file = directory / f"{role}-verification.json"
            if not receipt_file.exists():
                raise Rejected(f"{role} missing operator verification receipt")
            receipt = json.loads(receipt_file.read_text(encoding="utf-8"))
            log = directory / f"{role}-verification.log"
            if not log.is_file():
                raise Rejected(f"{role} missing operator verification log")
            expected = {"execution_id":manifest["execution_id"], "task_id":row["tasks"][role],
                        "run_id":self.kb.latest_run(conn,row["tasks"][role]).id,
                        "role":role, "candidate_digest":row["candidate_digest"],
                        "candidate_revision":row["candidate_revision"], "command":manifest["test_command"],
                        "exit_code":0,"status":"PASS", "log_sha256":hashlib.sha256(log.read_bytes()).hexdigest()}
            if any(receipt.get(key) != value for key,value in expected.items()):
                raise Rejected(f"{role} failed, stale, or altered verification receipt")
            refs[role] = digest(receipt)
        if metadata["builder"].get("changed_files") != changed:
            raise Rejected("Builder changed_files does not match the actual candidate")
        if metadata["reviewer"].get("verdict") != "PASS":
            raise Rejected("Reviewer did not return PASS")
        return {"status":"ACCEPTED", "execution_id":manifest["execution_id"],
                "source_revision":manifest["source_revision"], "candidate_revision":row["candidate_revision"],
                "candidate_digest":row["candidate_digest"], "changed_files":changed,
                "policy_digest":digest([manifest["budget"],manifest["test_command"],manifest["image"]]),
                "verification_receipts":refs, "accepted_at":time.time(), "actual_api_cost_usd":None}

    def record_acceptance(self, manifest: dict, conn, accepted_by: str = "operator") -> dict:
        """Write the acceptance record. Caller holds the execution lock."""
        result = {**self.acceptance(manifest, conn), "accepted_by": accepted_by}
        write_json(self.path(manifest["execution_id"]) / "acceptance.json", result)
        self.kb.add_comment(conn, manifest["rounds"][-1]["tasks"]["reviewer" if self.modern(manifest) else "orchestrator"],
                            author="operator-quality-gate", body=json.dumps(result, sort_keys=True))
        if self.modern(manifest):
            manifest["workflow_state"] = "ACCEPTED"
            self.save(manifest)
        return result

    def accept(self, execution: str, note: str = "", *, expected_round: int | None = None,
               expected_candidate: str | None = None) -> dict:
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if expected_round is not None and manifest["rounds"][-1]["number"] != expected_round:
                raise Rejected("ROUND_CHANGED")
            if expected_candidate is not None and manifest["rounds"][-1].get("candidate_digest") != expected_candidate:
                raise Rejected("卡片已过期，请重新核对交付内容。")
            result = self.record_acceptance(manifest, conn)
            reasons = [item for item in manifest.get("decision", {}).get("reasons", [])
                       if item["category"] != "未开启自动验收"]
            if note.strip() or reasons:
                summary = "；".join(item["category"] + ("：" + "、".join(item["paths"][:5]) if item["paths"] else "")
                                   for item in reasons)
                workflow_policy.record_decision(self.root, self.board, "approved", execution=execution,
                    objective=manifest["objective"],
                    text=(note.strip() or "确认交付") + (f"\n（批准的改动：{summary}）" if summary else ""))
            return result

    def reject(self, execution: str, reason: str, *, expected_round: int | None = None) -> dict:
        """The human decided not to do this. Record it so it is not raised again."""
        if not reason.strip():
            raise Rejected("请写明不做的原因，之后遇到同类请求会按此回答。")
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if expected_round is not None and manifest["rounds"][-1]["number"] != expected_round:
                raise Rejected("ROUND_CHANGED")
            if (self.path(execution) / "acceptance.json").exists():
                raise Rejected("已验收任务不能再标记为不做。")
            if any(self.kb.get_task(conn, tid).status == "running" for tid in manifest["rounds"][-1]["tasks"].values()):
                raise Rejected("仍有角色在运行，请等待其结束后再决定。")
            manifest["approved_write"] = False
            manifest["workflow_state"] = "REJECTED"
            manifest["rejection"] = {"reason": reason.strip(), "at": time.time()}
            self.save(manifest)
            workflow_policy.record_decision(self.root, self.board, "rejected", execution=execution,
                                            objective=manifest["objective"], text=reason.strip())
            return manifest

    def retry_review(self, execution: str, reason: str, *, expected_run_id: int,
                     runner=subprocess.run) -> dict:
        """Operator-only re-review after an evidence/environment correction.

        Reuse the frozen candidate and passing platform evidence. The native
        Dashboard reopen operation preserves the original FAIL run; a new claim
        creates a separate Reviewer run. This never starts implementation work.
        """
        if not reason.strip():
            raise Rejected("a concrete review-retry reason is required")
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if not self.modern(manifest) or not manifest["approved_write"]:
                raise Rejected("review retry requires an approved workflow v2 round")
            if (self.path(execution) / "acceptance.json").exists():
                raise Rejected("accepted execution cannot be retried")
            row = manifest["rounds"][-1]
            run = self.kb.latest_run(conn, row["tasks"]["reviewer"])
            recorded = any(item["previous_run_id"] == expected_run_id for item in row.get("review_retries", []))
            if recorded:
                already_retried = True
            elif run is None or run.id != expected_run_id:
                raise Rejected("Reviewer run changed; review the latest result before retrying")
            else:
                metadata = self.completed_metadata(conn, row["tasks"]["reviewer"])
                if review_verdict(metadata) != "FAIL":
                    raise Rejected("review retry requires a completed Reviewer FAIL")
                self.budget(manifest, conn, new_work=True)
                already_retried = False
            expected_round = row["number"]
        if already_retried:
            return self.advance(execution, runner)

        self.prepare_review(execution)
        receipt = self.verify_platform(execution, runner)
        if receipt["status"] != "PASS":
            raise Rejected("review retry requires passing platform verification")
        from plugins.kanban.dashboard.plugin_api import _set_status_direct
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            row = manifest["rounds"][-1]
            run = self.kb.latest_run(conn, row["tasks"]["reviewer"])
            if row["number"] != expected_round or run is None or run.id != expected_run_id:
                raise Rejected("Reviewer round or run changed while preparing retry")
            if not manifest["approved_write"]:
                raise Rejected("WRITE_NOT_APPROVED")
            self.budget(manifest, conn, new_work=True)
            task = self.kb.get_task(conn, row["tasks"]["reviewer"])
            if task.status not in {"done", "ready"}:
                raise Rejected("Reviewer is not available for a completed-review retry")
            retry = {"previous_run_id":expected_run_id, "reason":reason.strip(), "at":time.time(),
                     "candidate_digest":row["candidate_digest"], "verification_key":receipt["evidence_key"]}
            if not _set_status_direct(conn, task.id, "ready"):
                raise Rejected("native Reviewer reopen was refused")
            self.kb.add_comment(conn, task.id, author="operator-review-retry", body=(
                f"Review retry after evidence/environment correction: {reason.strip()}\n"
                f"Prior FAIL run {expected_run_id} is retained. Re-review the same frozen candidate; "
                "read /handoff/platform/result.json, /handoff/platform/verification.log and the actual "
                "executed tests at /handoff/platform/independent-tests. No Builder or Tester rerun was requested."
            ))
            row.setdefault("review_retries", []).append(retry)
            manifest["workflow_state"] = "RUNNING_REVIEW"
            self.save(manifest)
        return self.advance(execution, runner)

    DECISION_STATES = {"READY_FOR_ACCEPTANCE", "REPAIR_REQUIRED", "HUMAN_REQUIRED"}

    def advance(self, execution: str, runner=subprocess.run) -> dict:
        result = self._advance(execution, runner)
        if result.get("state") in self.DECISION_STATES:
            self.notify(execution)
        return result

    def notify(self, execution: str, opener=None) -> dict | None:
        """Push one card per decision point; never blocks or fails the workflow."""
        if not workflow_notify.configured(self.env):
            return None
        if __package__:
            from . import workflow_advisor, workflow_timeline
        else:
            import workflow_advisor, workflow_timeline
        advice = workflow_advisor.advise(self, execution)
        with self.locked(execution):
            manifest = self.load(execution)
            state, row = manifest.get("workflow_state"), manifest["rounds"][-1]
            key = f"{row['number']}:{state}"
            sent = manifest.setdefault("notifications", {})
            if state not in self.DECISION_STATES or key in sent:
                return None
            sent[key] = {"status": "pending", "at": time.time()}
            self.save(manifest)
            decision = manifest.get("decision", {}) if manifest.get("decision", {}).get("round") == row["number"] else {}
            event = {"execution_id": execution, "objective": manifest["objective"], "state": state,
                     "round": row["number"], "reasons": decision.get("reasons", []),
                     "recommendation": {"READY_FOR_ACCEPTANCE": "测试与审查已通过，建议确认交付；请核对下列需要你决定的改动。",
                                        "REPAIR_REQUIRED": "按审查发现的阻断问题再修一轮。",
                                        "HUMAN_REQUIRED": "有角色被阻塞或执行环境未就绪，需要你检查。"}[state]}
            card = workflow_timeline.card_for(manifest, {})
            event.update(card_id=card["card_id"] if card else "", recommendation=advice["text"])
        # Network call happens outside the execution lock.
        status = workflow_notify.send(self.env, event, **({"opener": opener} if opener else {}))
        with self.locked(execution):
            manifest = self.load(execution)
            manifest.setdefault("notifications", {})[key] = status
            self.save(manifest)
        return status

    def _advance(self, execution: str, runner=subprocess.run) -> dict:
        """Advance approved native cards; never grant approval.

        The native owner calls this at dispatch ticks. State, triage releases,
        snapshots and receipts are durable, so a replacement owner resumes here.
        """
        def response(manifest, state, waiting_for=None):
            return {"execution_id": execution, "workflow_version": manifest.get("workflow_version", 1),
                    "state": state, "workflow_state": state, "waiting_for": waiting_for,
                    "completed": state in {"READY_FOR_ACCEPTANCE", "ACCEPTED"}}

        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if not self.modern(manifest):
                return response(manifest, "LEGACY_MANUAL")
            if manifest.get("workflow_state") == "REJECTED":
                return response(manifest, "REJECTED")
            if not manifest["approved_write"]:
                return response(manifest, "WAITING_APPROVAL", "approval")
            if manifest.get("workflow_state") in {"READY_FOR_ACCEPTANCE", "ACCEPTED", "REPAIR_REQUIRED", "REJECTED"}:
                return response(manifest, manifest["workflow_state"])
            self.budget(manifest, conn)
            row = manifest["rounds"][-1]
            if not row.get("started_at"):
                checks = self.readiness(execution)
                if not checks["ready"]:
                    manifest["workflow_state"] = "HUMAN_REQUIRED"
                    self.save(manifest)
                    return {**response(manifest, "HUMAN_REQUIRED", "readiness"), "readiness":checks}
                row["started_at"] = time.time()
                self.save(manifest)
            def done(role):
                task = self.kb.get_task(conn, row["tasks"][role])
                run = self.kb.latest_run(conn, row["tasks"][role])
                return task.status in {"done", "archived"} and run is not None and run.outcome == "completed"

            def release(role):
                task = self.kb.get_task(conn, row["tasks"][role])
                if task.status == "triage":
                    self.budget(manifest, conn, new_work=True)
                    self.kb.specify_triage_task(conn, task.id, author="operator")

            blocked = [role for role in self.roles(manifest)
                       if self.kb.get_task(conn, row["tasks"][role]).status == "blocked"]
            if blocked:
                manifest["workflow_state"] = "HUMAN_REQUIRED"
                self.save(manifest)
                return response(manifest, "HUMAN_REQUIRED", blocked)
            if not done("researcher"):
                release("researcher")
                state = "RUNNING_RESEARCH"
            else:
                self.publish_handoff(manifest, row, "researcher", conn)
                self.publish_repair_handoff(manifest, row, conn)
                if not done("builder") or not done("tester"):
                    for role in ("builder", "tester"):
                        release(role)
                    state = "RUNNING_BUILD_AND_TEST"
                else:
                    state = "VERIFYING"
            manifest["workflow_state"] = state
            self.save(manifest)
        if state != "VERIFYING":
            return {**response(manifest, state), "dispatch": workflow_runtime.dispatch(self)}

        if not row.get("snapshot_ready"):
            self.prepare_review(execution)
        manifest = self.load(execution)
        row = manifest["rounds"][-1]
        receipt = self.verify_platform(execution, runner)
        expected_round = row["number"]
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            row = manifest["rounds"][-1]
            if row["number"] != expected_round or not manifest["approved_write"]:
                return response(manifest, "WAITING_APPROVAL", "approval")
            if receipt["status"] != "PASS":
                manifest["workflow_state"] = "REPAIR_REQUIRED"
                self.save(manifest)
                return response(manifest, "REPAIR_REQUIRED", "platform")
            reviewer = self.kb.get_task(conn, row["tasks"]["reviewer"])
            review_run = self.kb.latest_run(conn, reviewer.id)
            if reviewer.status in {"done", "archived"} and review_run and review_run.outcome == "completed":
                metadata = self.completed_metadata(conn, reviewer.id)
                self.publish_handoff(manifest, row, "reviewer", conn)
                verdict = review_verdict(metadata)
                if verdict == "FAIL":
                    state = "REPAIR_REQUIRED"
                elif verdict == "PASS":
                    self.acceptance(manifest, conn)
                    files = row["candidate_files"]
                    changed = sorted(key for key in files.keys() | manifest["source_files"].keys()
                                     if files.get(key) != manifest["source_files"].get(key))
                    deleted = sorted(manifest["source_files"].keys() - files.keys())
                    reasons = workflow_policy.decision_reasons(manifest.get("policy"), changed, deleted)
                    manifest["decision"] = {"round": row["number"], "reasons": reasons, "at": time.time()}
                    if reasons:
                        state = "READY_FOR_ACCEPTANCE"
                    else:
                        # Inside the pre-authorized scope: same evidence checks, no human click.
                        self.record_acceptance(manifest, conn, accepted_by="policy")
                        state = "ACCEPTED"
                else:
                    raise Rejected("Reviewer must return verdict PASS or FAIL")
            else:
                if reviewer.status == "triage":
                    self.budget(manifest, conn, new_work=True)
                    self.kb.specify_triage_task(conn, reviewer.id, author="operator")
                state = "RUNNING_REVIEW"
            manifest["workflow_state"] = state
            self.save(manifest)
        result = response(manifest, state)
        if state == "RUNNING_REVIEW":
            result["dispatch"] = workflow_runtime.dispatch(self)
        return result

    def retry_worker(self, execution: str, role: str, expected_round: int, expected_run_id: int, reason: str) -> dict:
        """Explicitly retry one terminal failed role through native unblock/claim history."""
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            row = manifest["rounds"][-1]
            if not self.modern(manifest) or not manifest["approved_write"] or row["number"] != expected_round:
                raise Rejected("ROUND_CHANGED")
            if role not in row["tasks"] or (self.path(execution) / "acceptance.json").exists():
                raise Rejected("当前角色不能重试。")
            task = self.kb.get_task(conn, row["tasks"][role])
            run = self.kb.latest_run(conn, task.id)
            if (task.status != "blocked" or run is None or run.id != expected_run_id
                    or run.outcome not in {"crashed", "failed", "spawn_failed", "timeout", "timed_out", "gave_up"}):
                raise Rejected("角色状态已经变化，请重新查看运行结果。")
            self.budget(manifest, conn, new_work=True)
            self.kb.add_comment(conn, task.id, author="operator-retry", body=reason.strip() or "环境问题已处理，按原授权重试此角色，保留失败记录并复用已有有效产物。")
            if not self.kb.unblock_task(conn, task.id):
                raise Rejected("原生任务重试被拒绝。")
        return self.advance(execution)

    def request_changes(self, execution: str, reason: str, expected_round: int) -> dict:
        """Record an explicit customer revision without fabricating a Reviewer FAIL."""
        if not reason.strip():
            raise Rejected("请填写修改意见。")
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            row = manifest["rounds"][-1]
            if not self.modern(manifest) or row["number"] != expected_round:
                raise Rejected("ROUND_CHANGED")
            if (self.path(execution) / "acceptance.json").exists():
                raise Rejected("已验收任务请创建后续任务。")
            self.acceptance(manifest, conn)
            if len(manifest["rounds"]) - 1 >= manifest["budget"]["max_rounds"]:
                raise Rejected("REPAIR_BUDGET")
            manifest["failures"].append({"kind": "implementation", "reason": reason.strip(),
                "fingerprint": digest(["customer-change", row["number"], reason.strip()]),
                "at": time.time(), "requested_by": "customer"})
            self.new_round(manifest, conn, row["tasks"]["reviewer"])
            workflow_policy.record_decision(self.root, self.board, "approved", execution=execution,
                                            objective=manifest["objective"], text="要求修改：" + reason.strip())
            return manifest

    def repair(self, execution: str, kind: str, reason: str, *, expected_round: int | None = None) -> dict:
        if kind not in FAILURE_KINDS or not reason.strip():
            raise Rejected("a classified, concrete failure reason is required")
        if kind not in {"implementation","test"}:
            raise Rejected(f"HUMAN_REQUIRED: {kind}; automatic code repair is inappropriate")
        with self.locked(execution), workflow_runtime.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            if expected_round is not None and manifest["rounds"][-1]["number"] != expected_round:
                raise Rejected("ROUND_CHANGED")
            self.budget(manifest, conn, new_work=True)
            row = manifest["rounds"][-1]
            if any(self.kb.get_task(conn,tid).status == "running" for r in manifest["rounds"] for tid in r["tasks"].values()):
                raise Rejected("active workers must terminate before repair")
            if row.get("parent") and not manifest["approved_write"]:
                # The prior FAIL was already recorded. Resume its card creation
                # after a crash instead of consuming another repair round.
                self.populate_round(manifest,row,conn)
                return manifest
            parent = row["tasks"]["reviewer"]
            platform = self.path(execution) / f"round-{row['number']}" / "platform-verification.json"
            if self.modern(manifest) and platform.is_file() and (receipt := json.loads(platform.read_text(encoding="utf-8")))["status"] == "FAIL":
                review = {"findings":[{"role":"platform", "evidence_key":receipt["evidence_key"],
                                       "log_sha256":receipt["log_sha256"]}]}
                parent = row["tasks"]["builder"]
            else:
                review = self.completed_metadata(conn, parent)
                if (review_verdict(review) if self.modern(manifest) else review.get("verdict")) != "FAIL":
                    raise Rejected("repair requires a completed Reviewer FAIL")
                if self.modern(manifest):
                    # Minor notes may change between rounds; repeated blockers may not.
                    review = {**review, "findings": blocker_findings(review)}
            # Changing the repair request prose must not hide the same review.
            fingerprint = digest([kind,review.get("findings")])
            if fingerprint in [item["fingerprint"] for item in manifest["failures"]]:
                raise Rejected("REPEATED_FAILURE: human intervention required")
            if len(manifest["rounds"]) - 1 >= manifest["budget"]["max_rounds"]:
                raise Rejected("REPAIR_BUDGET: maximum repair rounds reached")
            manifest["failures"].append({"kind":kind,"reason":reason,"fingerprint":fingerprint,"at":time.time()})
            self.new_round(manifest, conn, parent)
            self.save(manifest)
            return manifest

    def status(self, execution: str) -> dict:
        # Browsing must not create or migrate the native board database.
        database = self.kb.kanban_db_path(board=self.board).resolve()
        with self.locked(execution), closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            manifest = self.load(execution)
            try:
                receipt = self.path(execution) / "acceptance.json"
                recorded = json.loads(receipt.read_text(encoding="utf-8")) if receipt.exists() else None
                accepted = self.acceptance(manifest, conn, at_time=recorded["accepted_at"] if recorded else None)
                if not receipt.exists():
                    accepted["status"] = "READY_FOR_ACCEPTANCE"
                else:
                    if any(recorded.get(key) != accepted[key] for key in (
                        "execution_id","source_revision","candidate_revision","candidate_digest","verification_receipts","policy_digest"
                    )):
                        raise Rejected("acceptance record is stale")
                    accepted = recorded
            except Rejected as exc:
                accepted = {"status":"NOT_ACCEPTED","reason":str(exc)}
            state = manifest.get("workflow_state", "LEGACY_MANUAL")
            return {"execution_id":execution,"workflow_version":manifest.get("workflow_version",1),
                    "workflow_state":state,"state":state,"acceptance":accepted,
                    "rounds":[{"number":row["number"],"tasks":{
                        role:{"id":tid,"status":task.status if (task := self.kb.get_task(conn,tid)) else "missing"}
                        for role,tid in row["tasks"].items()}} for row in manifest["rounds"]],
                    "budget":manifest["budget"],"timing":self.timing(manifest,conn),
                    "actual_api_cost_usd":None,"failures":manifest["failures"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env", type=Path, required=True)
    sub = parser.add_subparsers(dest="action", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("objective")
    submit.add_argument("--instance", default=os.environ.get("WORKFLOW_EXECUTION_ID") or os.environ.get("JOB_KEY", ""))
    for action in ("start","prepare-review","verify","accept","repair","status"):
        command = sub.add_parser(action)
        command.add_argument("execution")
        if action == "start":
            command.add_argument("--approve-write", action="store_true")
        elif action == "verify":
            command.add_argument("--role", choices=("builder","reviewer"), required=True)
        elif action == "repair":
            command.add_argument("--kind", choices=sorted(FAILURE_KINDS), required=True)
            command.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        from hermes_cli import kanban_db
        archive = os.environ.get("HERMES_BASELINE_ARCHIVE")
        verify_source(Path(kanban_db.__file__).resolve().parents[1], Path(archive) if archive else None)
        env = load_env_file(args.env)
        root = Path(os.environ.get("HERMES_HOME") or str(Path.home()/".hermes")).expanduser().resolve()
        workflow = Workflow(root,env)
        if args.action == "submit":
            result = workflow.submit(args.objective,args.instance)
        elif args.action == "start":
            result = workflow.start(args.execution,args.approve_write)
        elif args.action == "prepare-review":
            result = workflow.prepare_review(args.execution)
        elif args.action == "verify":
            result = workflow.verify(args.execution,args.role)
        elif args.action == "repair":
            result = workflow.repair(args.execution,args.kind,args.reason)
        else:
            result = getattr(workflow,args.action)(args.execution)
        # Manifest contains only non-secret paths/policy. No credential env dump.
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        return 1 if result.get("status") == "FAIL" else 0
    except (Rejected, ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1,f"WORKFLOW REJECTED: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
