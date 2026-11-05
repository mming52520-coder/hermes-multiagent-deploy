"""Native discovery/preload and installed-controller wiring; no model calls."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import test_workflow as fixtures
import test_workflow_v2 as v2
from test_workflow_app import installer, import_file
import workflow_skills


class RoleSkillTest(unittest.TestCase):
    def setUp(self):
        self.f = v2.WorkflowV2Test()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)

    def task(self, role):
        with fixtures.connect_closing(board="default") as conn:
            return fixtures.kb.get_task(conn, self.f.row()["tasks"][role])

    def test_native_catalog_and_worker_preload_use_scoped_skill_without_new_tools(self):
        from tools.skills_tool import skills_list
        from gateway.session_kanban import _run_task_turns
        for role, name in workflow_skills.ROLE_SKILLS.items():
            if role == "architect":
                continue
            task = self.task(role)
            profile = self.f.root / "profiles" / task.assignee
            self.assertEqual(task.skills, [name])
            copied = profile / "skills" / name / "SKILL.md"
            self.assertEqual(copied.read_bytes(), workflow_skills.skill_path(role).read_bytes())
            config = fixtures.configs.read_yaml(profile / "config.yaml")
            self.assertEqual(config["platform_toolsets"]["cli"], ["terminal", "file"])
            self.assertFalse(config["terminal"]["docker_network"])
            calls = []

            class Agent:
                session_id = "offline-skill-probe"

                def run_conversation(self, prompt, **kwargs):
                    calls.append(prompt)
                    return {"final_response": "fixture", "messages": []}

            with fixtures.wc.workflow_runtime.home_scope(profile), \
                    patch("agent.kanban_turn_recovery.recover_failed_kanban_turns"):
                catalog = json.loads(skills_list())
                self.assertTrue(any(item["name"] == name for item in catalog["skills"]))
                _run_task_turns(Agent(), {"text": "fixture request"}, [], {
                    "skills": task.skills, "context": "fixture task context", "goal_mode": False,
                    "task_id": task.id,
                })
            self.assertEqual(len(calls), 1)
            self.assertIn(copied.read_text().split("---", 2)[2].strip(), calls[0])
            self.assertIn("fixture task context", calls[0])
        for role in ("tester", "reviewer"):
            self.assertFalse(self.task(role).skills)

    def test_missing_skill_stops_native_turn_before_model_call(self):
        from gateway.session_kanban import _run_task_turns
        from unittest.mock import Mock
        task = self.task("builder")
        profile = self.f.root / "profiles" / task.assignee
        (profile / "skills" / task.skills[0] / "SKILL.md").unlink()
        agent = Mock(session_id="missing-skill-probe")
        with fixtures.wc.workflow_runtime.home_scope(profile):
            with self.assertRaisesRegex(ValueError, "kanban_skills_unavailable"):
                _run_task_turns(agent, {"text": "request"}, [], {
                    "skills": task.skills, "context": "context", "goal_mode": False,
                })
        agent.run_conversation.assert_not_called()

    def test_approval_does_not_replace_task_guidance_or_touch_base_profile(self):
        task = self.task("builder")
        profile = self.f.root / "profiles" / task.assignee
        path = profile / "skills" / task.skills[0] / "SKILL.md"
        before = hashlib.sha256(path.read_bytes()).hexdigest()
        with patch.object(workflow_skills, "install_worker_skill", side_effect=AssertionError("rewrote pinned skill")):
            self.f.workflow.approve(self.f.execution)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), before)
        self.assertFalse((self.f.root / "profiles" / "builder" / "skills" / task.skills[0]).exists())
        self.assertFalse((self.f.root / "skills" / task.skills[0]).exists())

    def test_interrupted_profile_initialization_can_resume_before_task_binding(self):
        with patch.object(workflow_skills, "install_worker_skill", side_effect=OSError("interrupted copy")):
            with self.assertRaisesRegex(OSError, "interrupted copy"):
                self.f.workflow.submit("Resume role initialization", notify=False)
        manifest = self.f.workflow.submit("Resume role initialization", notify=False)
        with fixtures.connect_closing(board="default") as conn:
            task = fixtures.kb.get_task(conn, manifest["rounds"][0]["tasks"]["researcher"])
        path = self.f.root / "profiles" / task.assignee / "skills" / task.skills[0] / "SKILL.md"
        self.assertEqual(path.read_bytes(), workflow_skills.skill_path("researcher").read_bytes())

    def test_installed_controller_reads_installed_asset_without_tools(self):
        from types import SimpleNamespace
        env = self.f.directory / "binding.env"
        env.write_text("PROJECT_DIR=" + str(self.f.project) + "\n")
        target = installer.install(self.f.root, env)
        managed = json.loads((target / ".managed-files.json").read_text())
        for role, name in workflow_skills.ROLE_SKILLS.items():
            key = f"operator/skills/{name}/SKILL.md"
            self.assertEqual(managed[key], hashlib.sha256(workflow_skills.skill_path(role).read_bytes()).hexdigest())
        installed = import_file("installed_role_skill_probe", target / "operator/workflow_skills.py")
        self.assertEqual(installed.architect_guidance(), workflow_skills.architect_guidance())
        # Exercise the real no-tools Agent constructor seam, not a model reply.
        import workflow_conversation as conversation
        with patch("run_agent.AIAgent") as construct, \
                patch("hermes_cli.config.load_config", return_value={"model": {"default": "fixture-model"}}), \
                patch("hermes_cli.runtime_provider.resolve_runtime_provider", return_value={}):
            conversation.make_agent(SimpleNamespace(project=self.f.project), {"session_id": "fixture"}, None)
        self.assertEqual(construct.call_args.kwargs["enabled_toolsets"], [])
        self.assertTrue(construct.call_args.kwargs["skip_context_files"])


if __name__ == "__main__":
    unittest.main()
