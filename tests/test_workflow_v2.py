"""Native Kanban integration for approved parallel build/test design.

Workers and Docker are doubles. The tests exercise native dependencies, durable
handoffs, snapshots, evidence reuse and explicit human acceptance offline.
"""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

import test_workflow as fixtures

configs, kb, wc = fixtures.configs, fixtures.kb, fixtures.wc


class WorkflowV2Test(unittest.TestCase):
    workflow_version = 2
    row = fixtures.WorkflowTest.row
    completed = fixtures.WorkflowTest.completed
    metadata = fixtures.WorkflowTest.metadata

    def setUp(self):
        fixtures.WorkflowTest.setUp(self)
        self.dispatch_patch = patch.object(wc.workflow_runtime, "dispatch", return_value={"spawned":[]})
        self.dispatch = self.dispatch_patch.start()
        self.addCleanup(self.dispatch_patch.stop)
        readiness_patch = patch.object(self.workflow,"readiness",return_value={"ready":True,"checks":[]})
        self.readiness = readiness_patch.start()
        self.addCleanup(readiness_patch.stop)
        self.calls = []
        self.image_id = "sha256:offline-fixture-image"
        self.exit_code = 0

    def runner(self, command, **kwargs):
        self.calls.append(command)
        if "inspect" in command:
            return subprocess.CompletedProcess(command, 0, self.image_id + "\n", "")
        return subprocess.CompletedProcess(command, self.exit_code, "Independent test cases: 1\nOK\n", "")

    def advance(self):
        return self.workflow.advance(self.execution, self.runner)

    def research(self):
        self.workflow.approve(self.execution)
        self.assertEqual(self.advance()["state"], "RUNNING_RESEARCH")
        output = self.workflow.output_path(self.execution, 0, "researcher")
        (output / "DESIGN.md").write_text("Requirement: LICENSE includes the feature fixture.\n", encoding="utf-8")
        self.completed("researcher", {"findings":["fixture acceptance contract"]})
        self.assertEqual(self.advance()["state"], "RUNNING_BUILD_AND_TEST")

    def deliver(self, round_number=0):
        row = self.row()
        candidate = Path(row["candidate"])
        with (candidate / "LICENSE").open("a", encoding="utf-8") as output:
            output.write(f"\nIndependent feature fixture {round_number}.\n")
        tests = self.workflow.output_path(self.execution, round_number, "tester") / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class FeatureTest(unittest.TestCase):\n"
            "    def test_requirement(self):\n"
            "        self.assertIn('feature fixture', (Path.cwd()/'LICENSE').read_text())\n", encoding="utf-8")
        self.completed("builder", {"changed_files":["round-delta"], "commands_run":["focused compile"]})
        self.completed("tester", {"status":"TESTS_READY", "verification":["baseline expected failure"]})

    def ready(self):
        self.research()
        self.deliver()
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        self.completed("reviewer", {"verdict":"PASS", "commands_run":["platform receipt inspected"]})
        self.assertEqual(self.advance()["state"], "READY_FOR_ACCEPTANCE")

    def test_parallel_native_dependencies_and_readable_readonly_handoff(self):
        self.assertEqual(self.workflow.load(self.execution)["workflow_version"], 2)
        self.assertEqual(set(self.row()["tasks"]), set(wc.ROLES))
        self.assertEqual(self.advance()["state"], "WAITING_APPROVAL")
        self.assertFalse(self.dispatch.called)
        self.research()
        row = self.row()
        with fixtures.connect_closing(board="default") as conn:
            research = row["tasks"]["researcher"]
            for role in ("builder", "tester"):
                self.assertEqual(kb.parent_ids(conn, row["tasks"][role]), [research])
                task = kb.get_task(conn, row["tasks"][role])
                self.assertIn(task.status, {"todo", "ready"})
                config = configs.read_yaml(self.root / "profiles" / task.assignee / "config.yaml")
                self.assertIn(f"{self.workflow.handoff_path(self.execution,0)}:/handoff:ro", config["terminal"]["docker_volumes"])
                workspace = row["candidate" if role == "builder" else "review"]
                self.assertIn(f"{workspace}:/candidate:{'rw' if role == 'builder' else 'ro'}", config["terminal"]["docker_volumes"])
            self.assertEqual(set(kb.parent_ids(conn, row["tasks"]["reviewer"])), {row["tasks"]["builder"],row["tasks"]["tester"]})
            self.assertEqual(kb.get_task(conn,row["tasks"]["reviewer"]).status,"triage")
        handoff = self.workflow.handoff_path(self.execution,0) / "researcher"
        self.assertIn("LICENSE", (handoff / "artifacts" / "DESIGN.md").read_text())
        self.assertTrue(handoff.is_symlink())
        self.assertEqual(self.readiness.call_count,1)

    def test_customer_revision_preserves_pass_and_requires_a_new_grant(self):
        self.ready()
        previous = self.row()["tasks"]["reviewer"]
        self.workflow.request_changes(self.execution, "Adjust the fixture output", 0)
        manifest = self.workflow.load(self.execution)
        self.assertEqual(len(manifest["rounds"]), 2)
        self.assertFalse(manifest["approved_write"])
        self.assertEqual(manifest["workflow_state"], "WAITING_APPROVAL")
        self.assertEqual(manifest["failures"][-1]["requested_by"], "customer")
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(self.workflow.completed_metadata(conn, previous)["verdict"], "PASS")
        self.assertFalse((self.workflow.path(self.execution) / "acceptance.json").exists())

    def test_operator_retry_preserves_failed_run_and_uses_native_unblock(self):
        self.workflow.approve(self.execution)
        self.advance()
        task_id = self.row()["tasks"]["researcher"]
        with fixtures.connect_closing(board="default") as conn:
            fixtures.kb.recompute_ready(conn)
            fixtures.kb.claim_task(conn, task_id)
            run = fixtures.kb.latest_run(conn, task_id)
            conn.execute("UPDATE task_runs SET status='blocked', outcome='crashed', ended_at=? WHERE id=?", (time.time(), run.id))
            conn.execute("UPDATE tasks SET status='blocked', claim_lock=NULL, claim_expires=NULL WHERE id=?", (task_id,))
            conn.commit()
        with self.assertRaisesRegex(wc.Rejected, "角色状态已经变化"):
            self.workflow.retry_worker(self.execution, "researcher", 0, run.id + 1, "resolved fixture")
        result = self.workflow.retry_worker(self.execution, "researcher", 0, run.id, "environment corrected; reuse output")
        self.assertEqual(result["state"], "RUNNING_RESEARCH")
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(fixtures.kb.latest_run(conn, task_id).outcome, "crashed")
            self.assertEqual(fixtures.kb.get_task(conn, task_id).status, "ready")
            self.assertTrue(conn.execute("SELECT 1 FROM task_events WHERE task_id=? AND kind='unblocked'", (task_id,)).fetchone())

    def test_initial_readiness_failure_releases_no_cards_and_can_resume(self):
        self.workflow.approve(self.execution)
        self.readiness.return_value = {"ready":False,"checks":[{"code":"docker","ready":False}]}
        self.assertEqual(self.advance()["waiting_for"],"readiness")
        self.assertFalse(self.dispatch.called)
        with fixtures.connect_closing(board="default") as conn:
            self.assertTrue(all(kb.get_task(conn,task).status == "triage" for task in self.row()["tasks"].values()))
        self.readiness.return_value = {"ready":True,"checks":[]}
        self.assertEqual(self.advance()["state"],"RUNNING_RESEARCH")
        self.advance()
        self.assertEqual(self.readiness.call_count,2)

    def test_one_complete_receipt_and_manual_acceptance(self):
        self.ready()
        self.assertEqual(sum("run" in command for command in self.calls), 1)
        directory = self.workflow.path(self.execution) / "round-0"
        self.assertTrue((directory / "platform-verification.json").is_file())
        self.assertFalse((directory / "builder-verification.json").exists())
        self.assertFalse((self.workflow.path(self.execution) / "acceptance.json").exists())
        self.assertEqual(self.workflow.accept(self.execution)["status"],"ACCEPTED")
        self.assertEqual(self.advance()["state"],"ACCEPTED")
        self.assertEqual(wc.git(self.project,"status","--porcelain"),"")

    def test_normalized_result_keeps_native_metadata_and_cumulative_diff(self):
        self.ready()
        row = self.row()
        handoff = self.workflow.handoff_path(self.execution,0) / "builder"
        normalized = json.loads((handoff / "result.json").read_text())
        raw = json.loads((handoff / "raw-result.json").read_text())
        self.assertEqual(normalized["changed_files"],["LICENSE"])
        self.assertEqual(normalized["round_changed_files"],["round-delta"])
        self.assertEqual(normalized["verification"],["focused compile"])
        self.assertEqual(normalized["candidate_digest"],row["candidate_digest"])
        self.assertEqual(raw["changed_files"],["round-delta"])
        with fixtures.connect_closing(board="default") as conn:
            self.assertNotIn("candidate_digest",self.workflow.completed_metadata(conn,row["tasks"]["builder"]))

    def test_receipt_reuse_and_environment_change_rerun(self):
        self.research()
        self.deliver()
        self.advance()
        self.assertTrue(self.workflow.verify(self.execution,"platform",self.runner)["reused"])
        self.assertEqual(sum("run" in command for command in self.calls),1)
        self.image_id = "sha256:changed-environment"
        self.assertEqual(self.advance()["state"],"RUNNING_REVIEW")
        receipt_file = self.workflow.path(self.execution) / "round-0" / "platform-verification.json"
        self.assertFalse(json.loads(receipt_file.read_text())["reused"])
        self.assertEqual(sum("run" in command for command in self.calls),2)
        self.assertEqual(len(self.row()["verification_intervals"]),2)

    def test_platform_runner_discovers_real_cases_and_rejects_empty_suite(self):
        self.research()
        self.deliver()
        self.advance()
        directory = self.workflow.path(self.execution) / "round-0"
        receipt = json.loads((directory / "platform-verification.json").read_text())
        self.assertEqual(receipt["environment"]["cwd"], "/tmp/candidate")
        invocation = next(command for command in self.calls if "run" in command)
        self.assertIn('cd /tmp/candidate && printf "Verification cwd: " && pwd -P', invocation[-3])
        command = shlex.split(receipt["command"].split(" && ", 1)[1])
        command[0] = fixtures.sys.executable
        command[-1] = command[-1].replace("/independent-tests", str(directory / "independent-tests"))
        result = subprocess.run(command,cwd=self.row()["candidate"],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn("Independent test cases: 1",result.stdout)
        (directory / "independent-tests" / "test_feature.py").write_text("import unittest\n",encoding="utf-8")
        result = subprocess.run(command,cwd=self.row()["candidate"],capture_output=True,text=True)
        self.assertEqual(result.returncode,1,result.stdout+result.stderr)
        self.assertIn("Independent test cases: 0",result.stdout)

    def test_failed_platform_skips_review_and_requires_new_approval(self):
        self.research()
        self.deliver()
        self.exit_code = 1
        self.assertEqual(self.advance()["state"],"REPAIR_REQUIRED")
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(kb.get_task(conn,self.row()["tasks"]["reviewer"]).status,"triage")
            self.assertEqual(len(kb.list_tasks(conn)),4)
        self.advance()
        self.assertEqual(sum("run" in command for command in self.calls),1)
        previous_research = self.row()["tasks"]["researcher"]
        repaired = self.workflow.repair(self.execution,"test","fix the independently failing assertion")
        self.assertFalse(repaired["approved_write"])
        self.assertEqual(self.advance()["state"],"WAITING_APPROVAL")
        self.assertEqual(self.row()["tasks"]["researcher"],previous_research)
        self.assertIn("Independent feature fixture 0",(Path(self.row()["review"])/"LICENSE").read_text())
        self.workflow.approve(self.execution)
        self.assertEqual(self.advance()["state"],"RUNNING_BUILD_AND_TEST")
        repair = self.workflow.handoff_path(self.execution,1) / "repair"
        self.assertEqual(json.loads((repair / "result.json").read_text())["platform"]["status"],"FAIL")
        self.assertIn("Independent test cases",(repair / "platform-verification.log").read_text())
        self.assertTrue((repair / "independent-tests" / "test_feature.py").is_file())
        self.deliver(1)
        self.exit_code = 0
        self.assertEqual(self.advance()["state"],"RUNNING_REVIEW")
        self.completed("reviewer",{"verdict":"PASS"})
        self.assertEqual(self.advance()["state"],"READY_FOR_ACCEPTANCE")
        self.assertEqual(self.workflow.accept(self.execution)["status"],"ACCEPTED")

    def test_reviewer_fail_has_no_extra_summary_task(self):
        self.research()
        self.deliver()
        self.advance()
        self.completed("reviewer",{"verdict":"FAIL","findings":["actual interface mismatch"]})
        self.assertEqual(self.advance()["state"],"REPAIR_REQUIRED")
        with self.assertRaisesRegex(wc.Rejected,"Reviewer did not return PASS"):
            self.workflow.accept(self.execution)
        self.assertNotIn("orchestrator",self.row()["tasks"])
        self.workflow.repair(self.execution,"implementation","fix actual interface mismatch")
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(len(kb.list_tasks(conn)),7)
        self.workflow.approve(self.execution)
        self.advance()
        repair = self.workflow.handoff_path(self.execution,1) / "repair" / "result.json"
        self.assertEqual(json.loads(repair.read_text())["reviewer"]["findings"],["actual interface mismatch"])

    def test_evidence_repair_retries_only_reviewer_and_preserves_failed_run(self):
        self.research()
        self.deliver()
        self.advance()
        failed = {"verdict":"FAIL","findings":["executed independent test files were missing from handoff"]}
        self.completed("reviewer",failed)
        self.assertEqual(self.advance()["state"],"REPAIR_REQUIRED")
        row = self.row()
        with fixtures.connect_closing(board="default") as conn:
            original = kb.latest_run(conn,row["tasks"]["reviewer"])
            other_runs = {role:len(kb.list_runs(conn,row["tasks"][role])) for role in ("researcher","builder","tester")}
        tests = self.workflow.handoff_path(self.execution,0) / "platform" / "independent-tests"
        shutil.rmtree(tests)  # Reproduce the earlier owner's incomplete handoff.
        result = self.workflow.retry_review(self.execution,"platform evidence path repaired",
                                            expected_run_id=original.id,runner=self.runner)
        self.assertEqual(result["state"],"RUNNING_REVIEW")
        self.assertTrue((tests / "test_feature.py").is_file())
        self.assertEqual(sum("run" in command for command in self.calls),1)
        self.assertEqual(self.workflow.retry_review(self.execution,"same operator retry",
                                                    expected_run_id=original.id,runner=self.runner)["state"],"RUNNING_REVIEW")
        self.completed("reviewer",{"verdict":"PASS","verification":["executed files and receipt inspected"]})
        self.assertEqual(self.advance()["state"],"READY_FOR_ACCEPTANCE")
        with fixtures.connect_closing(board="default") as conn:
            review_runs = kb.list_runs(conn,row["tasks"]["reviewer"])
            self.assertEqual(len(review_runs),2)
            saved_fail = next(run for run in review_runs if run.id == original.id)
            self.assertEqual(saved_fail.metadata,failed)
            self.assertEqual(saved_fail.outcome,"completed")
            for role,count in other_runs.items():
                self.assertEqual(len(kb.list_runs(conn,row["tasks"][role])),count)
            comments = kb.list_comments(conn,row["tasks"]["reviewer"])
            self.assertTrue(any(comment.author == "operator-review-retry" for comment in comments))
        self.assertEqual(len(self.row()["review_retries"]),1)
        self.assertEqual(sum("run" in command for command in self.calls),1)

    def test_restart_after_snapshot_resumes_without_duplicate_tasks_or_tests(self):
        self.research()
        self.deliver()
        self.workflow.prepare_review(self.execution)
        self.workflow.verify(self.execution,"platform",self.runner)
        recovered = wc.Workflow(self.root,self.env)
        with patch.object(recovered,"prepare_review",side_effect=AssertionError("refroze candidate")):
            self.assertEqual(recovered.advance(self.execution,self.runner)["state"],"RUNNING_REVIEW")
        self.assertEqual(sum("run" in command for command in self.calls),1)
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(len(kb.list_tasks(conn)),4)

    def test_waiting_does_not_consume_execution_budget_and_parallel_time_is_union(self):
        manifest = self.workflow.load(self.execution)
        manifest["created_at"] = time.time() - 100000
        self.workflow.save(manifest)
        self.research()
        now = int(time.time())
        with fixtures.connect_closing(board="default") as conn:
            kb.claim_task(conn,self.row()["tasks"]["builder"])
            kb.claim_task(conn,self.row()["tasks"]["tester"])
            for role in ("builder","tester"):
                conn.execute("UPDATE task_runs SET started_at=? WHERE task_id=?",(now-10,self.row()["tasks"][role]))
            conn.commit()
            timing = self.workflow.timing(self.workflow.load(self.execution),conn,at_time=now)
            self.assertGreaterEqual(timing["running_seconds"],10)
            self.assertLess(timing["running_seconds"],12)
            self.assertGreater(timing["waiting_seconds"],99000)

    def test_missing_independent_tests_cannot_release_review(self):
        self.research()
        self.deliver()
        tests = self.workflow.output_path(self.execution,0,"tester") / "tests" / "test_feature.py"
        tests.unlink()
        with self.assertRaisesRegex(wc.Rejected,"Tester must deliver"):
            self.advance()
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(kb.get_task(conn,self.row()["tasks"]["reviewer"]).status,"triage")

    def test_changed_frozen_tests_invalidate_acceptance(self):
        self.ready()
        tests = self.workflow.path(self.execution) / "round-0" / "independent-tests" / "test_feature.py"
        tests.write_text("changed test set",encoding="utf-8")
        with self.assertRaisesRegex(wc.Rejected,"stale"):
            self.workflow.accept(self.execution)

    def test_minor_findings_do_not_fail_review(self):
        self.research()
        self.deliver()
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        self.completed("reviewer", {"verdict": "FAIL", "findings": [
            {"severity": "minor", "summary": "error message could name the file", "file": "LICENSE"}]})
        self.assertEqual(self.advance()["state"], "READY_FOR_ACCEPTANCE")
        handoff = json.loads((self.workflow.handoff_path(self.execution, 0) / "reviewer" / "result.json").read_text())
        self.assertEqual((handoff["verdict"], handoff["reported_verdict"]), ("PASS", "FAIL"))
        self.assertEqual(self.workflow.accept(self.execution)["status"], "ACCEPTED")

    def test_blocker_finding_fails_review_even_if_reported_pass(self):
        self.research()
        self.deliver()
        self.advance()
        self.completed("reviewer", {"verdict": "PASS", "findings": [
            {"severity": "blocker", "summary": "acceptance scenario 2 crashes", "file": "LICENSE"},
            {"severity": "minor", "summary": "naming"}]})
        self.assertEqual(self.advance()["state"], "REPAIR_REQUIRED")
        with self.assertRaisesRegex(wc.Rejected, "Reviewer did not return PASS"):
            self.workflow.accept(self.execution)

    def test_repeated_blocker_is_detected_even_when_minor_notes_change(self):
        blocker = {"severity": "blocker", "summary": "acceptance scenario 2 crashes", "file": "LICENSE"}
        self.research()
        self.deliver()
        self.advance()
        self.completed("reviewer", {"verdict": "FAIL", "findings": [blocker, {"severity": "minor", "summary": "a"}]})
        self.assertEqual(self.advance()["state"], "REPAIR_REQUIRED")
        self.workflow.repair(self.execution, "implementation", "fix scenario 2")
        self.workflow.approve(self.execution)
        self.advance()
        self.deliver(1)
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        self.completed("reviewer", {"verdict": "FAIL", "findings": [blocker, {"severity": "minor", "summary": "b"}]})
        self.assertEqual(self.advance()["state"], "REPAIR_REQUIRED")
        with self.assertRaisesRegex(wc.Rejected, "REPEATED_FAILURE"):
            self.workflow.repair(self.execution, "implementation", "reworded request")

    def test_ungraded_findings_keep_reported_verdict(self):
        self.assertEqual(wc.review_verdict({"verdict": "FAIL", "findings": ["legacy text"]}), "FAIL")
        self.assertEqual(wc.review_verdict({"verdict": "PASS", "findings": []}), "PASS")
        self.assertIsNone(wc.review_verdict({"findings": [{"severity": "nit"}]}))


    def test_full_flow_records_actual_transitions_and_same_state_saves_are_quiet(self):
        self.ready()
        manifest = self.workflow.load(self.execution)
        states = [item["to"] for item in manifest["transitions"]]
        self.assertEqual(states, ["WAITING_APPROVAL", "RUNNING_RESEARCH", "RUNNING_BUILD_AND_TEST",
                                  "VERIFYING", "RUNNING_REVIEW", "VERIFYING", "READY_FOR_ACCEPTANCE"])
        self.workflow.save(manifest)
        self.assertEqual(self.workflow.load(self.execution)["transitions"], manifest["transitions"])


if __name__ == "__main__":
    unittest.main()
