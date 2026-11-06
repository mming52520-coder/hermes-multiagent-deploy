"""Document delivery uses the same native evidence/review gate as code."""
from pathlib import Path
import subprocess
import unittest

import test_workflow_v2 as v2

wc, kb, fixtures = v2.wc, v2.kb, v2.fixtures


class DocumentDeliveryTest(unittest.TestCase):
    workflow_version = 2
    setUp = v2.WorkflowV2Test.setUp
    row = v2.WorkflowV2Test.row
    completed = v2.WorkflowV2Test.completed
    runner = v2.WorkflowV2Test.runner
    advance = v2.WorkflowV2Test.advance
    research = v2.WorkflowV2Test.research

    def document(self):
        self.manifest = self.workflow.submit("Write a document with the required decision evidence.",
                                             deliverable_type="document", notify=False)
        self.execution = self.manifest["execution_id"]

    def deliver(self, report=True):
        candidate = Path(self.row()["candidate"])
        if report:
            (candidate / "deliverables").mkdir()
            (candidate / "deliverables/DESIGN.md").write_text("Decision evidence: option A.\n")
        # The former output-only delivery must not satisfy the final gate.
        (self.workflow.output_path(self.execution, 0, "builder") / "DESIGN.md").write_text("Decision evidence: option A.\n")
        tests = self.workflow.output_path(self.execution, 0, "tester") / "tests"
        tests.mkdir()
        (tests / "test_report.py").write_text(
            "import unittest\nfrom pathlib import Path\n"
            "class ReportTest(unittest.TestCase):\n"
            " def test_decision(self):\n"
            "  self.assertIn('Decision evidence:', (Path.cwd()/'deliverables/DESIGN.md').read_text())\n")
        self.completed("builder", {"round_changed_files": ["deliverables/DESIGN.md"] if report else []})
        self.completed("tester", {"status": "TESTS_READY"})

    def test_document_contract_reaches_workers_and_retains_review_gate(self):
        self.document()
        self.assertEqual(self.manifest["test_command"], wc.DOCUMENT_TEST_COMMAND)
        self.workflow.env["WORKFLOW_TEST_COMMAND"] = "unrelated-demo-command"
        with fixtures.connect_closing(board="default") as conn:
            for task in self.row()["tasks"].values():
                context = kb.build_worker_context(conn, task)
                self.assertIn("/candidate/deliverables/DESIGN.md", context)
                self.assertIn("structural tests alone do not establish", context)
                self.assertNotIn("unrelated-demo-command", context)
        self.research()
        self.deliver()
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        command = next(c[-1] for c in self.calls if "run" in c)
        self.assertIn(wc.DOCUMENT_TEST_COMMAND, command)
        self.assertIn("/independent-tests", command)
        self.assertNotIn("unrelated-demo-command", command)
        self.assertFalse((self.workflow.path(self.execution) / "acceptance.json").exists())
        self.completed("reviewer", {"verdict": "PASS", "findings": [], "verification": ["report checked"]})
        self.assertEqual(self.advance()["state"], "READY_FOR_ACCEPTANCE")
        self.assertIn("deliverables/DESIGN.md", self.workflow.status(self.execution)["acceptance"]["changed_files"])

    def test_output_only_or_missing_document_fails_real_check(self):
        self.document()
        self.research()
        self.deliver(report=False)
        candidate = Path(self.row()["candidate"])
        result = subprocess.run(self.manifest["test_command"], shell=True, cwd=candidate, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing document delivery", result.stderr)
        self.exit_code = result.returncode
        self.assertEqual(self.advance()["state"], "REPAIR_REQUIRED")
        with fixtures.connect_closing(board="default") as conn:
            self.assertEqual(kb.get_task(conn, self.row()["tasks"]["reviewer"]).status, "triage")

    def test_document_review_can_reject_a_structurally_valid_report(self):
        self.document()
        self.research()
        self.deliver()
        self.assertEqual(self.advance()["state"], "RUNNING_REVIEW")
        self.completed("reviewer", {"verdict": "FAIL", "verification": ["source comparison"],
                                    "findings": [{"severity": "blocker", "summary": "Decision contradicts source evidence"}]})
        self.assertEqual(self.advance()["state"], "REPAIR_REQUIRED")
        self.assertFalse((self.workflow.path(self.execution) / "acceptance.json").exists())

    def test_document_repeat_and_code_contract_are_separate_and_frozen(self):
        objective = "Draft a design and implement its code."
        code = self.workflow.submit(objective, notify=False)
        document = self.workflow.submit(objective, notify=False, deliverable_type="document")
        self.assertNotEqual(code["execution_id"], document["execution_id"])
        self.assertEqual(code["test_command"], self.env["WORKFLOW_TEST_COMMAND"])
        self.workflow.env["WORKFLOW_TEST_COMMAND"] = "changed-command"
        repeated = self.workflow.submit(objective, notify=False)
        self.assertEqual(repeated["test_command"], code["test_command"])
        self.assertEqual(self.workflow.submit(objective, notify=False, deliverable_type="document")["execution_id"],
                         document["execution_id"])
        before = set(self.workflow.store.iterdir())
        with self.assertRaisesRegex(wc.Rejected, "unsupported deliverable"):
            self.workflow.submit("invalid type", deliverable_type="skip-tests", notify=False)
        self.assertEqual(set(self.workflow.store.iterdir()), before)
