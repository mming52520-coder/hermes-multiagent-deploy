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
    from .hermes_baseline import verify_source
else:
    from configure_profiles import load_env_file, read_yaml, worker_mounts, write_yaml
    from hermes_baseline import verify_source

ROLES = ("researcher", "builder", "reviewer", "orchestrator")
FAILURE_KINDS = {"implementation", "test", "environment", "api_model", "permission", "requirements"}


class Rejected(ValueError):
    pass


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
        write_json(self.path(manifest["execution_id"]) / "execution.json", manifest)

    def budget(self, manifest: dict, conn, at_time: float | None = None, new_work: bool = False) -> None:
        policy = manifest["budget"]
        if (time.time() if at_time is None else at_time) - manifest["created_at"] >= policy["max_seconds"]:
            raise Rejected("TIME_BUDGET: operator action requires human intervention")
        tasks = {task for row in manifest["rounds"] for task in row["tasks"].values()}
        attempts = sum(len(self.kb.list_runs(conn, task)) for task in tasks)
        if attempts > policy["max_runs"] or (new_work and attempts >= policy["max_runs"]):
            raise Rejected("RUN_BUDGET: no new work allowed")
        # v0.18.2 task runs have no authoritative actual API billing field.
        # Never convert model-provided metadata or an estimate into a bill.
        if policy["max_cost_usd"] is not None:
            raise Rejected("COST_UNAVAILABLE: this Hermes baseline cannot enforce a hard API cost cap")

    def scoped_profile(self, role: str, execution: str, round_number: int, workspace: Path, writable: bool = False) -> str:
        from hermes_cli.profiles import create_profile, get_profile_dir
        name = f"{role}-{execution[:16]}-{round_number}"
        profile = get_profile_dir(name)
        if not profile.exists():
            create_profile(name, clone_from=role, no_alias=True)
        config = read_yaml(profile / "config.yaml")
        if role == "orchestrator":
            config["toolsets"] = ["kanban","memory","session_search","todo","clarify","skills"]
            config["platform_toolsets"]["cli"] = list(config["toolsets"])
        else:
            output = Path(self.env["OUTPUT_DIR"]).resolve() / execution / str(round_number) / role
            output.mkdir(parents=True, exist_ok=True, mode=0o700)
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
            independent_clone(candidate, review, git(candidate, "rev-parse", "HEAD"))
        row = {"number": number, "tasks": {}, "candidate": str(candidate), "review": str(review), "parent":parent}
        if number:
            row["tasks"]["researcher"] = manifest["rounds"][0]["tasks"]["researcher"]
        # Persist each native ID immediately. Native idempotency handles a crash
        # between create_task and this write; completed IDs stay in the manifest.
        manifest["rounds"].append(row)
        self.save(manifest)
        self.populate_round(manifest, row, conn, parent)
        return row

    def populate_round(self, manifest: dict, row: dict, conn, parent: str | None = None) -> None:
        execution = manifest["execution_id"]
        previous = row.get("parent") or parent
        for role in ROLES:
            if role in row["tasks"]:
                if not (role == "researcher" and row["number"]):
                    previous = row["tasks"][role]
                continue
            workspace = Path(row["review"] if role == "reviewer" else row["candidate"])
            profile = self.scoped_profile(role, execution, row["number"], workspace)
            body = (
                f"Objective: {manifest['objective']}\nExecution ID: {execution}\n"
                f"Source revision: {manifest['source_revision']}\nRole: {role}\n"
                "Container cwd /candidate aliases the task's host workspace.\n"
                "Read all parent handoffs. Never commit, push, merge, deploy, or access hardware.\n"
                "Return execution_id, source_revision, candidate_revision, candidate_digest, "
                "evidence_refs, blockers, residual_risks in completion metadata.\n"
            )
            if role == "builder":
                body += "Modify only this candidate. Include real changed_files and verification commands/results.\n"
            elif role == "reviewer":
                body += "Read-only review of the operator-prepared candidate snapshot. Include verdict PASS/FAIL and findings.\n"
            elif role == "orchestrator":
                body += "Summarize evidence only. Kanban done is NOT acceptance. Do not create unbounded repair cards.\n"
            tid = self.kb.create_task(
                conn, title=f"{role}: {manifest['objective']}", body=body, assignee=profile,
                parents=[previous] if previous else [], triage=True,
                workspace_kind="dir", workspace_path=str(workspace),
                idempotency_key=f"{execution}:{row['number']}:{role}",
                max_runtime_seconds={"researcher":1200,"builder":3600,"reviewer":1800,"orchestrator":900}[role],
                max_retries=1, board=self.board,
            )
            row["tasks"][role] = tid
            self.save(manifest)
            previous = tid

    def submit(self, objective: str, instance: str = "") -> dict:
        revision = git(self.project, "rev-parse", "HEAD")
        execution = execution_identity(objective, revision, instance)
        with self.locked(execution):
            manifest_file = self.path(execution) / "execution.json"
            with self.kb.connect_closing(board=self.board) as conn:
                if manifest_file.exists():
                    manifest = self.load(execution)
                    if manifest["rounds"]:
                        self.populate_round(manifest, manifest["rounds"][-1], conn)
                    return manifest
                if git(self.project, "status", "--porcelain"):
                    raise Rejected("source has uncommitted changes; preserve them and choose a clean source snapshot")
                candidate = self.path(execution) / "candidate"
                if not candidate.exists():
                    independent_clone(self.project, candidate, revision)
                manifest = {
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
                }
                self.new_round(manifest, conn)
                return manifest

    def start(self, execution: str, approve_write: bool) -> dict:
        with self.locked(execution), self.kb.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            self.budget(manifest, conn, new_work=True)
            if not approve_write:
                raise Rejected("WRITE_NOT_APPROVED: explicit operator --approve-write required")
            if not manifest["test_command"].strip():
                raise Rejected("configure a meaningful WORKFLOW_TEST_COMMAND before authorizing work")
            row = manifest["rounds"][-1]
            if any(self.kb.get_task(conn,tid).status == "running" for tid in row["tasks"].values()):
                raise Rejected("a worker is already running; do not change its mounted permissions")
            self.scoped_profile("builder",execution,row["number"],Path(row["candidate"]),writable=True)
            manifest["approved_write"] = True
            self.save(manifest)
            for role in ("researcher", "builder"):
                self.kb.specify_triage_task(conn,row["tasks"][role],author="operator")
            return manifest

    def completed_metadata(self, conn, task: str) -> dict:
        item = self.kb.get_task(conn, task)
        run = self.kb.latest_run(conn, task)
        if item is None or item.status not in {"done","archived"} or run is None or run.outcome != "completed":
            raise Rejected(f"task is not successfully completed: {task}")
        return json.loads(run.metadata or "{}") if isinstance(run.metadata, str) else (run.metadata or {})

    def prepare_review(self, execution: str) -> dict:
        with self.locked(execution), self.kb.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            self.budget(manifest, conn)
            row = manifest["rounds"][-1]
            if not manifest["approved_write"]:
                raise Rejected("WRITE_NOT_APPROVED")
            self.completed_metadata(conn, row["tasks"]["builder"])
            reviewer = self.kb.get_task(conn, row["tasks"]["reviewer"])
            if reviewer.status != "triage":
                raise Rejected("review already released; do not replace its candidate snapshot")
            candidate, review = Path(row["candidate"]), Path(row["review"])
            if (candidate / ".git").is_symlink() or not (candidate / ".git").is_dir():
                raise Rejected("candidate lost its independent Git metadata")
            # Only replace our own unpublished, per-round snapshot.
            shutil.rmtree(review)
            shutil.copytree(candidate, review, symlinks=True)
            row["candidate_revision"] = git(candidate, "rev-parse", "HEAD")
            row["candidate_files"] = tree_files(candidate)
            row["candidate_digest"] = digest(row["candidate_files"])
            self.save(manifest)
            for role in ("reviewer", "orchestrator"):
                self.kb.specify_triage_task(conn,row["tasks"][role],author="operator")
            return manifest

    def verify(self, execution: str, role: str, runner=subprocess.run) -> dict:
        if role not in {"builder", "reviewer"}:
            raise Rejected("only builder and reviewer have verification receipts")
        with self.locked(execution), self.kb.connect_closing(board=self.board) as conn:
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
        metadata = {role:self.completed_metadata(conn, task) for role,task in row["tasks"].items()}
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

    def accept(self, execution: str) -> dict:
        with self.locked(execution), self.kb.connect_closing(board=self.board) as conn:
            result = self.acceptance(self.load(execution), conn)
            write_json(self.path(execution) / "acceptance.json", result)
            self.kb.add_comment(conn, self.load(execution)["rounds"][-1]["tasks"]["orchestrator"],
                                author="operator-quality-gate", body=json.dumps(result, sort_keys=True))
            return result

    def repair(self, execution: str, kind: str, reason: str) -> dict:
        if kind not in FAILURE_KINDS or not reason.strip():
            raise Rejected("a classified, concrete failure reason is required")
        with self.locked(execution), self.kb.connect_closing(board=self.board) as conn:
            manifest = self.load(execution)
            self.budget(manifest, conn, new_work=True)
            row = manifest["rounds"][-1]
            if any(self.kb.get_task(conn,tid).status == "running" for r in manifest["rounds"] for tid in r["tasks"].values()):
                raise Rejected("active workers must terminate before repair")
            review = self.completed_metadata(conn, row["tasks"]["reviewer"])
            if review.get("verdict") != "FAIL":
                raise Rejected("repair requires a completed Reviewer FAIL")
            # Changing the repair request prose must not hide the same review.
            fingerprint = digest([kind,review.get("findings")])
            if kind not in {"implementation","test"}:
                raise Rejected(f"HUMAN_REQUIRED: {kind}; automatic code repair is inappropriate")
            if fingerprint in [item["fingerprint"] for item in manifest["failures"]]:
                raise Rejected("REPEATED_FAILURE: human intervention required")
            if len(manifest["rounds"]) - 1 >= manifest["budget"]["max_rounds"]:
                raise Rejected("REPAIR_BUDGET: maximum repair rounds reached")
            manifest["failures"].append({"kind":kind,"reason":reason,"fingerprint":fingerprint,"at":time.time()})
            self.new_round(manifest, conn, row["tasks"]["reviewer"])
            manifest["approved_write"] = False
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
            return {"execution_id":execution,"acceptance":accepted,
                    "rounds":[{"number":row["number"],"tasks":{
                        role:{"id":tid,"status":self.kb.get_task(conn,tid).status}
                        for role,tid in row["tasks"].items()}} for row in manifest["rounds"]],
                    "budget":manifest["budget"],"actual_api_cost_usd":None,"failures":manifest["failures"]}


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
