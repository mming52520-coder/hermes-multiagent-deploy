"""Native lifecycle advancement preserves approval and historical workflows."""
from contextlib import nullcontext
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


FILE = Path(__file__).resolve().parents[1] / "plugins/workflow/__init__.py"


class WorkflowAutomationTest(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("workflow_automation_test", FILE)
        self.plugin = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.plugin)

    def test_owner_tick_only_advances_approved_v2_unaccepted_executions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugins/workflow"
            plugin.mkdir(parents=True)
            (plugin / "config.json").write_text(json.dumps({
                "allow_actions": True, "hermes_home": str(root), "env_file": str(root / "workflow.env"),
            }))
            self.plugin.__file__ = str(plugin / "__init__.py")
            for name, version, approved in (("legacy", 1, True), ("pending", 2, False),
                                            ("accepted", 2, True), ("active", 2, True)):
                directory = root / "workflow/executions" / name
                directory.mkdir(parents=True)
                (directory / "execution.json").write_text(json.dumps({
                    "execution_id": name, "workflow_version": version, "approved_write": approved,
                }))
            (root / "workflow/executions/accepted/acceptance.json").write_text("{}")
            workflow = SimpleNamespace(root=root, board="default", advance=Mock())
            core = SimpleNamespace(load_env_file=lambda _path: {}, Workflow=lambda *_args: workflow,
                                   workflow_runtime=SimpleNamespace(home_scope=lambda _root: nullcontext()))
            with patch.object(self.plugin.importlib, "import_module", return_value=core):
                self.plugin._advance_pending("other-board")
                workflow.advance.assert_not_called()
                self.plugin._advance_pending("default")
                workflow.advance.assert_called_once_with("active")
                workflow.advance.reset_mock()
                (plugin / "config.json").write_text(json.dumps({"allow_actions": False}))
                self.plugin._advance_pending()
                workflow.advance.assert_not_called()

    def test_dispatch_reentry_and_dry_run_do_not_start_another_advance(self):
        with patch.object(self.plugin.threading, "Thread") as thread:
            self.plugin._on_dispatch_tick(dry_run=True)
            self.plugin._active.acquire()
            try:
                self.plugin._on_dispatch_tick()
            finally:
                self.plugin._active.release()
            thread.assert_not_called()

    def test_discovery_only_registers_and_owner_tick_starts_advancement(self):
        ctx = SimpleNamespace(register_hook=Mock())
        with patch.object(self.plugin, "_on_dispatch_tick") as tick:
            self.plugin.register(ctx)
            ctx.register_hook.assert_called_once_with("on_kanban_dispatch_tick", tick)
            tick.assert_not_called()
            ctx.register_hook.call_args.args[1](board="default")
            tick.assert_called_once_with(board="default")

    def test_foreign_home_dispatch_cannot_advance_the_installed_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plugin = root / "plugins/workflow"
            plugin.mkdir(parents=True)
            (plugin / "config.json").write_text(json.dumps({"hermes_home": str(root)}))
            self.plugin.__file__ = str(plugin / "__init__.py")
            with patch("hermes_constants.get_hermes_home", return_value=root / "other-home"), patch.object(self.plugin.threading, "Thread") as thread:
                self.plugin._on_dispatch_tick(board="default")
                thread.assert_not_called()
            with patch("hermes_constants.get_hermes_home", return_value=root), patch.object(self.plugin, "_advance_pending") as advance, patch.object(self.plugin.threading, "Thread", side_effect=lambda **kw: SimpleNamespace(start=kw["target"])):
                self.plugin._on_dispatch_tick(board="default")
                advance.assert_called_once_with("default")


if __name__ == "__main__":
    unittest.main()
