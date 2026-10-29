"""Offline P0 integration: real v0.18.2 Kanban, isolated clones, worker doubles.

No commit, deployment script, model request, service, or Docker container is run.
Docker execution is deliberately a test double; physical mount enforcement is
NOT_TESTED by this suite.
"""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import configure_profiles as configs
import workflow_control as wc
from hermes_cli import kanban_db as kb

REPOSITORY = Path(__file__).resolve().parents[1]


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hermes-workflow-test-")
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.project = self.directory / "project"
        # Reuse an existing commit. Tests never create commits or worktrees.
        wc.independent_clone(REPOSITORY,self.project,wc.git(REPOSITORY,"rev-parse","HEAD"))
        self.root = self.directory / "hermes"
        self.root.mkdir()
        environment = dict(os.environ)
        for key in ("HERMES_KANBAN_DB","HERMES_KANBAN_WORKSPACES_ROOT","HERMES_KANBAN_HOME","HERMES_PROFILE"):
            environment.pop(key,None)
        environment.update(HERMES_HOME=str(self.root),HERMES_KANBAN_BOARD="default")
        self.env_patch = patch.dict(os.environ,environment,clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.env = {
            "PROJECT_DIR":str(self.project),"OUTPUT_DIR":str(self.directory/"outputs"),
            "BOARD_SLUG":"default","DOCKER_IMAGE":"test-image:offline",
            "WORKFLOW_TEST_COMMAND":"python -m unittest discover -s tests",
        }
        self.output = io.StringIO()
        self.stdout = redirect_stdout(self.output)
        self.stdout.__enter__()
        self.addCleanup(self.stdout.__exit__,None,None,None)
        for role in wc.ROLES:
            profile = self.root / "profiles" / role
            profile.mkdir(parents=True)
            tools = ["kanban","memory","skills"] if role == "orchestrator" else ["terminal","file","delegation","code_execution"]
            configs.write_yaml(profile/"config.yaml",{
                "toolsets":tools,"platform_toolsets":{"cli":tools},
                "terminal":{"backend":"local" if role == "orchestrator" else "docker"},
            })
        self.workflow = wc.Workflow(self.root,self.env)
        self.manifest = self.workflow.submit("Add an auditable test fixture")
        self.execution = self.manifest["execution_id"]

    def row(self):
        return self.workflow.load(self.execution)["rounds"][-1]

    def completed(self,role,metadata=None):
        with kb.connect_closing(board="default") as conn:
            tid = self.row()["tasks"][role]
            kb.recompute_ready(conn)
            self.assertIsNotNone(kb.claim_task(conn,tid))
            self.assertTrue(kb.complete_task(conn,tid,result="offline worker result",metadata=metadata or {}))

    def metadata(self,row=None):
        row = row or self.row()
        return {
            "execution_id":self.execution,"source_revision":self.manifest["source_revision"],
            "candidate_revision":wc.git(Path(row["candidate"]),"rev-parse","HEAD"),
            "candidate_digest":wc.digest(wc.tree_files(Path(row["candidate"]))),
            "verification":[{"command":self.env["WORKFLOW_TEST_COMMAND"],"status":"reported-only"}],
            "changed_files":["LICENSE"],
        }

    def build(self):
        self.workflow.start(self.execution,True)
        self.completed("researcher",{"findings":["source inspected"]})
        candidate = Path(self.row()["candidate"])
        with (candidate/"LICENSE").open("a",encoding="utf-8") as out:
            out.write("\nOffline test candidate change.\n")
        self.completed("builder",self.metadata())
        self.workflow.prepare_review(self.execution)

    @staticmethod
    def passing_runner(command,**kwargs):
        return subprocess.CompletedProcess(command,0,stdout="Ran 3 fixture checks: OK\n",stderr="")

    def finish(self,verdict="PASS",verify=True):
        self.build()
        self.completed("reviewer",dict(self.metadata(),verdict=verdict,findings=["independent fixture review"]))
        self.completed("orchestrator",{"verdict":"ACCEPTED"})
        if verify:
            for role in ("builder","reviewer"):
                self.workflow.verify(self.execution,role,self.passing_runner)

    def test_default_off_and_no_approval_cannot_write(self):
        with kb.connect_closing(board="default") as conn:
            result=kb.dispatch_once(conn,spawn_fn=lambda task,workspace: self.fail("unapproved dispatch"),board="default")
            self.assertEqual(result.spawned,[])
            for role,tid in self.row()["tasks"].items():
                self.assertEqual(kb.get_task(conn,tid).status,"triage")
                if role != "orchestrator":
                    cfg=configs.read_yaml(self.root/"profiles"/kb.get_task(conn,tid).assignee/"config.yaml")
                    workspace=self.row()["review" if role == "reviewer" else "candidate"]
                    self.assertIn(f"{workspace}:{workspace}:ro",cfg["terminal"]["docker_volumes"])
        with self.assertRaisesRegex(wc.Rejected,"WRITE_NOT_APPROVED"):
            self.workflow.start(self.execution,False)

    def test_status_does_not_recreate_missing_native_database(self):
        database = kb.kanban_db_path(board="default")
        database.unlink()
        with self.assertRaises(sqlite3.OperationalError):
            self.workflow.status(self.execution)
        self.assertFalse(database.exists())

    def test_pass_requires_explicit_gate_and_current_receipts(self):
        self.finish()
        self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"],"READY_FOR_ACCEPTANCE")
        accepted=self.workflow.accept(self.execution)
        self.assertEqual(accepted["status"],"ACCEPTED")
        self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"],"ACCEPTED")
        self.assertEqual(wc.git(self.project,"status","--porcelain"),"")

    def test_native_done_cannot_forge_acceptance(self):
        self.finish(verify=False)
        with self.assertRaisesRegex(wc.Rejected,"missing operator verification"):
            self.workflow.accept(self.execution)

    def test_reviewer_fail_is_not_accepted(self):
        self.finish(verdict="FAIL")
        with self.assertRaisesRegex(wc.Rejected,"Reviewer did not return PASS"):
            self.workflow.accept(self.execution)

    def test_failed_test_is_not_accepted(self):
        self.finish()
        self.workflow.verify(self.execution,"reviewer",lambda command,**kwargs:subprocess.CompletedProcess(command,1,"FAIL",""))
        with self.assertRaisesRegex(wc.Rejected,"failed, stale, or altered"):
            self.workflow.accept(self.execution)

    def test_missing_test_handoff_rejected(self):
        self.build()
        md=self.metadata()
        md.pop("verification")
        self.completed("reviewer",dict(md,verdict="PASS"))
        self.completed("orchestrator")
        self.workflow.verify(self.execution,"builder",self.passing_runner)
        with self.assertRaisesRegex(wc.Rejected,"reviewer missing verification"):
            self.workflow.accept(self.execution)

    def test_wrong_commit_rejected(self):
        self.build()
        self.completed("reviewer",dict(self.metadata(),verdict="PASS",candidate_revision="f"*40))
        self.completed("orchestrator")
        for role in ("builder","reviewer"):
            self.workflow.verify(self.execution,role,self.passing_runner)
        with self.assertRaisesRegex(wc.Rejected,"candidate_revision"):
            self.workflow.accept(self.execution)

    def test_candidate_mutation_revokes_acceptance(self):
        self.finish()
        self.workflow.accept(self.execution)
        (Path(self.row()["candidate"])/"LICENSE").write_text("changed later",encoding="utf-8")
        self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"],"NOT_ACCEPTED")

    def test_altered_log_rejected(self):
        self.finish()
        log=self.workflow.path(self.execution)/"round-0"/"reviewer-verification.log"
        log.write_text("forged",encoding="utf-8")
        with self.assertRaisesRegex(wc.Rejected,"altered"):
            self.workflow.accept(self.execution)

    def test_missing_actual_changes_rejected(self):
        self.finish()
        row=self.row()
        git_source=Path(row["candidate"])
        wc.git(git_source,"restore","LICENSE")
        wc.git(Path(row["review"]),"restore","LICENSE")
        manifest=self.workflow.load(self.execution)
        manifest["rounds"][-1]["candidate_files"]=wc.tree_files(git_source)
        manifest["rounds"][-1]["candidate_digest"]=wc.digest(wc.tree_files(git_source))
        self.workflow.save(manifest)
        with self.assertRaisesRegex(wc.Rejected,"no real code-change"):
            self.workflow.accept(self.execution)

    def test_builder_failure_never_releases_review(self):
        self.workflow.start(self.execution,True)
        self.completed("researcher")
        with kb.connect_closing(board="default") as conn:
            kb.recompute_ready(conn)
            tid=self.row()["tasks"]["builder"]
            self.assertIsNotNone(kb.claim_task(conn,tid))
            kb.block_task(conn,tid,reason="implementation failed")
        with self.assertRaisesRegex(wc.Rejected,"not successfully completed"):
            self.workflow.prepare_review(self.execution)

    def test_idempotent_completed_execution_and_instances(self):
        self.finish()
        self.workflow.accept(self.execution)
        again=self.workflow.submit(self.manifest["objective"])
        self.assertEqual(again["rounds"],self.workflow.load(self.execution)["rounds"])
        with kb.connect_closing(board="default") as conn:
            for tid in self.row()["tasks"].values():
                kb.archive_task(conn,tid)
        self.assertEqual(again["rounds"],self.workflow.submit(self.manifest["objective"])["rounds"])
        separate=self.workflow.submit(self.manifest["objective"],"new-run")
        self.assertNotEqual(separate["execution_id"],self.execution)
        self.assertNotEqual(wc.execution_identity("goal","a"*40),wc.execution_identity("goal","b"*40))

    def test_accepted_history_does_not_expire_as_if_new_work_were_running(self):
        self.finish()
        self.workflow.accept(self.execution)
        with patch.object(wc.time,"time",return_value=time.time()+100000):
            self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"],"ACCEPTED")
            with self.assertRaisesRegex(wc.Rejected,"TIME_BUDGET"):
                self.workflow.start(self.execution,True)

    def test_controlled_repair_reuses_research_and_starts_unapproved(self):
        self.finish(verdict="FAIL")
        repaired=self.workflow.repair(self.execution,"implementation","fix the reported defect")
        self.assertEqual(len(repaired["rounds"]),2)
        self.assertEqual(repaired["rounds"][0]["tasks"]["researcher"],repaired["rounds"][1]["tasks"]["researcher"])
        self.assertFalse(repaired["approved_write"])
        with kb.connect_closing(board="default") as conn:
            self.assertIn(repaired["rounds"][0]["tasks"]["reviewer"],kb.parent_ids(conn,repaired["rounds"][1]["tasks"]["builder"]))

    def test_irrecoverable_categories_require_human(self):
        self.finish(verdict="FAIL")
        for kind in ("environment","api_model","permission","requirements"):
            with self.subTest(kind=kind),self.assertRaisesRegex(wc.Rejected,"HUMAN_REQUIRED"):
                self.workflow.repair(self.execution,kind,"concrete failure")

    def test_repair_round_limit(self):
        self.finish(verdict="FAIL")
        manifest=self.workflow.load(self.execution)
        manifest["budget"]["max_rounds"]=0
        self.workflow.save(manifest)
        with self.assertRaisesRegex(wc.Rejected,"REPAIR_BUDGET"):
            self.workflow.repair(self.execution,"test","test expectation needs repair")

    def test_repeated_failure_requires_human(self):
        self.finish(verdict="FAIL")
        manifest=self.workflow.load(self.execution)
        fingerprint=wc.digest(["implementation",["independent fixture review"]])
        manifest["failures"].append({"fingerprint":fingerprint})
        self.workflow.save(manifest)
        with self.assertRaisesRegex(wc.Rejected,"REPEATED_FAILURE"):
            self.workflow.repair(self.execution,"implementation","same defect")

    def test_global_time_run_and_unknown_cost_limits(self):
        for key,value,expected in (("max_seconds",0,"TIME_BUDGET"),("max_runs",-1,"RUN_BUDGET"),("max_cost_usd","1.00","COST_UNAVAILABLE")):
            manifest=self.workflow.load(self.execution)
            original=dict(manifest["budget"])
            manifest["budget"][key]=value
            self.workflow.save(manifest)
            with self.subTest(key=key),self.assertRaisesRegex(wc.Rejected,expected):
                self.workflow.start(self.execution,True)
            manifest["budget"]=original
            self.workflow.save(manifest)

    def test_verification_container_has_only_readonly_candidate(self):
        self.finish(verify=False)
        calls=[]
        def runner(command,**kwargs):
            calls.append(command)
            return self.passing_runner(command,**kwargs)
        self.workflow.verify(self.execution,"reviewer",runner)
        command=calls[0]
        self.assertIn("--network=none",command)
        self.assertIn("--read-only",command)
        self.assertIn("--pull=never",command)
        self.assertEqual(command.count("--mount"),1)
        self.assertTrue(command[command.index("--mount")+1].endswith(",readonly"))
        self.assertNotIn("--privileged",command)
        self.assertNotIn("-v",command)

    def test_verification_timeout_is_failure_and_cleans_only_own_container(self):
        self.finish(verify=False)
        calls=[]
        def runner(command,**kwargs):
            calls.append(command)
            if "run" in command:
                raise subprocess.TimeoutExpired(command,1)
            return subprocess.CompletedProcess(command,0,"","")
        receipt=self.workflow.verify(self.execution,"reviewer",runner)
        self.assertEqual(receipt["exit_code"],124)
        self.assertEqual(calls[1][2:4],["rm","--force"])
        self.assertEqual(calls[1][-1],calls[0][calls[0].index("--name")+1])

    def test_native_dispatch_claim_recovery_and_duplicate_dispatch(self):
        self.workflow.start(self.execution,True)
        calls=[]
        def spawn(task,workspace,board=None):
            calls.append(task.id)
            return os.getpid()  # a live process; no Worker or model is launched
        with kb.connect_closing(board="default") as conn:
            first=kb.dispatch_once(conn,spawn_fn=spawn,board="default",max_in_progress=1)
            self.assertEqual(len(first.spawned),1)
            kb.dispatch_once(conn,spawn_fn=spawn,board="default",max_in_progress=1)
            self.assertEqual(len(calls),1)
            # Reopen the real DB as a replacement gateway process would.
        with kb.connect_closing(board="default") as conn:
            kb.dispatch_once(conn,spawn_fn=spawn,board="default",max_in_progress=1)
            self.assertEqual(len(calls),1)
            tid=calls[0]
            self.assertTrue(kb.complete_task(conn,tid,result="recovered handoff"))
            next_tick=kb.dispatch_once(conn,spawn_fn=spawn,board="default",max_in_progress=1)
            self.assertEqual(next_tick.spawned[0][0],self.row()["tasks"]["builder"])

    def test_native_timeout_and_worker_crash_do_not_auto_accept(self):
        self.workflow.start(self.execution,True)
        with kb.connect_closing(board="default") as conn:
            kb.recompute_ready(conn)
            tid=self.row()["tasks"]["researcher"]
            self.assertIsNotNone(kb.claim_task(conn,tid))
            # Fault injection into a temporary native DB, never a production DB.
            conn.execute("UPDATE tasks SET started_at=?,max_runtime_seconds=1 WHERE id=?",(int(time.time())-5,tid))
            conn.commit()
            kb.enforce_max_runtime(conn)
            self.assertNotEqual(kb.get_task(conn,tid).status,"done")
            self.assertEqual(self.workflow.status(self.execution)["acceptance"]["status"],"NOT_ACCEPTED")

    def test_native_crashed_worker_trips_existing_failure_limit(self):
        self.workflow.start(self.execution,True)
        with kb.connect_closing(board="default") as conn:
            kb.recompute_ready(conn)
            tid=self.row()["tasks"]["researcher"]
            self.assertIsNotNone(kb.claim_task(conn,tid))
            kb._set_worker_pid(conn,tid,999999999)
            conn.execute("UPDATE tasks SET started_at=? WHERE id=?",(int(time.time())-kb._resolve_crash_grace_seconds()-1,tid))
            conn.commit()
            kb.detect_crashed_workers(conn)
            self.assertEqual(kb.get_task(conn,tid).status,"blocked")
            self.assertNotEqual(kb.latest_run(conn,tid).outcome,"completed")

    def test_scoped_profile_cwd_reaches_exact_mount_through_native_config(self):
        from tools.terminal_tool import _get_env_config
        self.workflow.start(self.execution,True)
        with kb.connect_closing(board="default") as conn:
            for role in ("researcher","builder","reviewer"):
                tid=self.row()["tasks"][role]
                config=configs.read_yaml(self.root/"profiles"/kb.get_task(conn,tid).assignee/"config.yaml")
                terminal=config["terminal"]
                self.assertEqual(terminal["cwd"],"/candidate")
                with patch.dict(os.environ,{
                    "TERMINAL_ENV":"docker","TERMINAL_CWD":terminal["cwd"],
                    "TERMINAL_DOCKER_MOUNT_CWD_TO_WORKSPACE":"false",
                    "TERMINAL_DOCKER_VOLUMES":json.dumps(terminal["docker_volumes"]),
                }):
                    native=_get_env_config()
                self.assertEqual(native["cwd"],"/candidate")
                source=self.row()["review" if role == "reviewer" else "candidate"]
                self.assertIn(f"{source}:/candidate:{'rw' if role == 'builder' else 'ro'}",native["docker_volumes"])

    def test_configuration_refresh_preserves_custom_soul_and_provider_routes(self):
        fixture=self.directory/"deploy.env"
        template=(REPOSITORY/"deploy.env.example").read_text(encoding="utf-8")
        fixture.write_text(template,encoding="utf-8")
        fixture.chmod(0o600)
        custom=self.root/"profiles"/"reviewer"/"SOUL.md"
        custom.write_text("Operator custom review contract",encoding="utf-8")
        fixture_env={
            "HERMES_USER":"testuser","PROJECT_DIR":str(self.project),
            "OUTPUT_DIR":self.env["OUTPUT_DIR"],"BACKUP_DIR":str(self.directory/"backup"),
            # Test fixture strings only. No network operation uses them.
            "PACKY_CLAUDE_API_KEY":"unit-test-not-a-credential",
            "PACKY_CODEX_API_KEY":"unit-test-not-a-credential",
            "DEEPSEEK_API_KEY":"unit-test-not-a-credential",
        }
        with patch.dict(os.environ,fixture_env),patch.object(sys,"argv",["configure_profiles.py",str(fixture)]):
            self.assertEqual(configs.main(),0)
        self.assertEqual(custom.read_text(encoding="utf-8"),"Operator custom review contract")
        for role,provider in (("orchestrator","custom:packy-claude"),("researcher","deepseek"),("builder","custom:packy-codex"),("reviewer","custom:packy-claude")):
            profile=self.root/"profiles"/role
            data=configs.read_yaml(profile/"config.yaml")
            self.assertEqual(data["model"]["provider"],provider)
            self.assertEqual((profile/".env").stat().st_mode & 0o777,0o600)
            if role != "orchestrator":
                self.assertIn(f"{self.project}:{self.project}:ro",data["terminal"]["docker_volumes"])

    def test_partial_submission_recovers_without_duplicate_native_cards(self):
        with patch.object(self.workflow,"populate_round",side_effect=RuntimeError("simulated interrupted submission")):
            with self.assertRaisesRegex(RuntimeError,"interrupted"):
                self.workflow.submit("Interrupted execution","resume")
        recovered=self.workflow.submit("Interrupted execution","resume")
        self.assertEqual(set(recovered["rounds"][0]["tasks"]),set(wc.ROLES))
        self.assertEqual(recovered,self.workflow.submit("Interrupted execution","resume"))

    def test_native_docker_arguments_keep_mount_permissions(self):
        from tools.environments import docker as native_docker
        from tools import credential_files
        self.workflow.start(self.execution,True)
        for role in ("builder","reviewer"):
            with self.subTest(role=role),kb.connect_closing(board="default") as conn:
                cfg=configs.read_yaml(self.root/"profiles"/kb.get_task(conn,self.row()["tasks"][role]).assignee/"config.yaml")
                calls=[]
                def fake_docker(command,**kwargs):
                    calls.append(command)
                    return subprocess.CompletedProcess(command,0,"fake-container-id\n" if "run" in command else "","")
                with patch.object(native_docker.subprocess,"run",side_effect=fake_docker), \
                     patch.object(native_docker.DockerEnvironment,"init_session",return_value=None), \
                     patch.object(native_docker,"_cgroup_limits_available",return_value=True), \
                     patch.object(native_docker,"find_docker",return_value="/fake/docker"), \
                     patch.object(credential_files,"get_credential_file_mounts",return_value=[]), \
                     patch.object(credential_files,"get_skills_directory_mount",return_value=[]), \
                     patch.object(credential_files,"get_cache_directory_mounts",return_value=[]):
                    environment=native_docker.DockerEnvironment(
                        image="test-image:offline",cwd=cfg["terminal"]["cwd"],timeout=5,
                        cpu=1,memory=512,disk=0,task_id="offline-fixture",
                        volumes=cfg["terminal"]["docker_volumes"],network=False,
                        persistent_filesystem=False,run_as_host_user=True,persist_across_processes=False,
                    )
                    args=environment._all_run_args
                    for volume in cfg["terminal"]["docker_volumes"]:
                        self.assertIn(volume,args)
                    self.assertIn("--network=none",args)
                    self.assertNotIn("--privileged",args)
                    self.assertIn(f"{self.project}:{self.project}:ro",args)
                    self.assertTrue(any("run" in command for command in calls))
                    # No real container exists; avoid a later destructor trying
                    # to clean a fake handle after subprocess mocking ends.
                    environment._container_id=None

    def test_existing_shell_invocation_uses_native_interpreter_and_job_key(self):
        fixture=self.directory/"wrapper.env"
        entries=[
            f"PROJECT_DIR={self.project}",f"OUTPUT_DIR={self.directory/'outputs'}",
            "BOARD_SLUG=default","DOCKER_IMAGE=test-image:offline",
            f"HERMES_PYTHON={sys.executable}","WORKFLOW_EXECUTION_ID=", "JOB_KEY=legacy-instance",
        ]
        archive=Path(os.environ.get("HERMES_BASELINE_ARCHIVE") or (str(Path(kb.__file__).resolve().parents[1])+".tar.gz"))
        if archive.exists():
            entries.append(f"HERMES_BASELINE_ARCHIVE={archive}")
        fixture.write_text("\n".join(entries)+"\n",encoding="utf-8")
        # This is the analyzed submission wrapper, not a deployment/smoke script.
        result=subprocess.run(["bash",str(REPOSITORY/"scripts"/"submit-feature.sh"),str(fixture),"Wrapper fixture"],
                              env=dict(os.environ),capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stderr)
        payload=json.loads(result.stdout)
        self.assertEqual(payload["instance"],"legacy-instance")
        self.assertEqual(set(payload["rounds"][0]["tasks"]),set(wc.ROLES))


class BaselineTest(unittest.TestCase):
    def test_wrong_commit_and_unverified_archives_are_rejected(self):
        from hermes_baseline import verify_source
        with self.assertRaisesRegex(ValueError,"unsupported Hermes source commit"):
            verify_source(REPOSITORY)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            archive=root/"source.tar.gz"
            archive.write_bytes(b"not the signed-off source archive")
            with self.assertRaisesRegex(ValueError,"checksum mismatch"):
                verify_source(root,archive)

    def test_source_without_provenance_is_rejected(self):
        from hermes_baseline import verify_source
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,"cannot be established"):
                verify_source(Path(directory))


class MountPolicyTest(unittest.TestCase):
    def test_original_and_shared_storage_readonly_and_exact_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            candidate=root/"candidate"
            (candidate/".git").mkdir(parents=True)
            for role in ("researcher","builder","reviewer"):
                mounts=configs.worker_mounts(role,root/"project",root/"kanban",root/"out"/role,candidate)
                self.assertIn(f"{root}/project:{root}/project:ro",mounts)
                self.assertIn(f"{root}/kanban:{root}/kanban:ro",mounts)
                self.assertIn(f"{candidate}:{candidate}:{'rw' if role == 'builder' else 'ro'}",mounts)

    def test_rejects_shared_git_metadata_and_overlapping_writable_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            workspace=root/"workspace"
            workspace.mkdir()
            (workspace/".git").write_text("gitdir: ../project/.git/worktrees/x",encoding="utf-8")
            with self.assertRaisesRegex(ValueError,"independent Git clone"):
                configs.worker_mounts("builder",root/"project",root/"kanban",root/"out",workspace)
            with self.assertRaisesRegex(ValueError,"writable"):
                configs.worker_mounts("builder",root/"project",root/"kanban",root/"project"/"outputs")


if __name__ == "__main__":
    unittest.main()
