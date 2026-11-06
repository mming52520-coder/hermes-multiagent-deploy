"""Desktop lifecycle tests; no real service or user configuration is stopped."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import workflow_desktop as app

spec = importlib.util.spec_from_file_location("desktop_installer", SCRIPTS / "install-workflow-desktop.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class DesktopTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="工作流 desktop ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = app.Settings(self.root / "home", self.root / "hermes", self.root / "web")
        self.settings.web_dist.mkdir()
        (self.settings.web_dist / "index.html").write_text("<html>workflow</html>")
        plugin = self.settings.hermes_home / "plugins/workflow"
        plugin.mkdir(parents=True)
        (plugin / "config.json").write_text('{"allow_actions":true}')
        (self.settings.hermes_home / "install_id").write_text("same-install\n")
        self.settings.hermes_bin.write_text("#!/bin/sh\nexit 0\n")
        self.settings.hermes_bin.chmod(0o755)
        self.services = app.Services(self.settings, self.root / "state")
        self.gateway = {"state": "ready", "client_code_sha": "current",
                        "endpoint": {"code_sha": "current"}, "reason_code": None}

    def ensure_result(self, code=0):
        return subprocess.CompletedProcess([], code, json.dumps(self.gateway), "")

    def test_reuse_running_services_without_spawning_or_restarting(self):
        with patch.object(app.subprocess, "run", return_value=self.ensure_result()) as run, \
                patch.object(self.services, "dashboard_ready", return_value=True), \
                patch.object(app.subprocess, "Popen") as spawn:
            self.services.start(Mock())
            self.services.start(Mock())
        spawn.assert_not_called()
        self.assertEqual(run.call_args.args[0][3:7], ["gateway", "ensure", "--json", "--timeout"])
        environment = run.call_args.kwargs["env"]
        self.assertEqual(environment["HERMES_HOME"], str(self.settings.hermes_home))
        self.assertEqual(environment["HERMES_DESKTOP"], "0")

    def test_cold_dashboard_start_waits_for_readiness(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        with patch.object(app.subprocess, "run", return_value=self.ensure_result()), \
                patch.object(self.services, "dashboard_ready", side_effect=[False, False, True]), \
                patch.object(app.subprocess, "Popen", return_value=process) as spawn, \
                patch.object(app.time, "sleep"):
            self.services.start(Mock())
        self.assertEqual(spawn.call_count, 1)
        self.assertIn("--no-open", spawn.call_args.args[0])
        self.assertTrue(spawn.call_args.kwargs["start_new_session"])
        process.terminate.assert_not_called()

    def test_gateway_failure_and_pending_start_do_not_open_dashboard(self):
        for state, code in (("starting", 0), ("conflict", 7), ("incompatible", 3), ("draining", 6)):
            with self.subTest(state=state):
                self.gateway["state"] = state
                with patch.object(app.subprocess, "run", return_value=self.ensure_result(code)), \
                        patch.object(app.subprocess, "Popen") as spawn:
                    with self.assertRaises(app.StartupError):
                        self.services.start(Mock())
                    spawn.assert_not_called()

    def test_native_restart_wait_keeps_existing_approvals_accessible(self):
        self.gateway.update(state="draining", reason_code="restart_wait")
        with patch.object(app.subprocess, "run", return_value=self.ensure_result(6)), \
                patch.object(self.services, "dashboard_ready", return_value=True):
            self.services.start(Mock())

    def test_old_gateway_is_not_silently_reused(self):
        self.gateway["endpoint"]["code_sha"] = "old"
        with patch.object(app.subprocess, "run", return_value=self.ensure_result()):
            with self.assertRaisesRegex(app.StartupError, "旧版本"):
                self.services.start(Mock())

    def test_dashboard_failure_surfaces_original_diagnostic(self):
        process = Mock(pid=123)
        process.poll.return_value = 1
        self.services.state_dir.mkdir()
        (self.services.state_dir / "dashboard.log").write_text("bind failed: address already in use")
        with patch.object(app.subprocess, "run", return_value=self.ensure_result()), \
                patch.object(self.services, "dashboard_ready", return_value=False), \
                patch.object(app.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(app.StartupError, "address already in use"):
                self.services.start(Mock())

    def test_retry_preserves_pending_child(self):
        process = Mock(pid=123)
        process.poll.return_value = None
        self.services.dashboard_process = process
        with patch.object(app.subprocess, "run", return_value=self.ensure_result()), \
                patch.object(self.services, "dashboard_ready", return_value=False) as ready, \
                patch.object(app.subprocess, "Popen") as spawn:
            with self.assertRaisesRegex(app.StartupError, "尚未就绪"):
                self.services.start(Mock(), timeout=0)
            ready.side_effect = [False, True]
            self.services.start(Mock())
            spawn.assert_not_called()

    def test_dashboard_identity_and_version_must_match(self):
        for health, status in (({"ok": True, "commit": "old"}, {}),
                               ({"ok": True, "commit": "current"}, {"install_id": "another-install"})):
            with self.subTest(health=health, status=status), \
                    patch.object(self.services, "_json", side_effect=[health, status]):
                with self.assertRaises(app.StartupError):
                    self.services.dashboard_ready("current")
        with patch.object(self.services, "_json", side_effect=[
                {"ok": True, "commit": "current", "auth_required": True}, {"install_id": "same-install"}]):
            self.assertTrue(self.services.dashboard_ready("current"))

    def test_only_connection_refused_means_service_absent(self):
        with patch.object(self.services, "_json", side_effect=URLError(ConnectionRefusedError(111, "refused"))):
            self.assertFalse(self.services.dashboard_ready("current"))
        for failure in (HTTPError(app.ORIGIN, 404, "not Hermes", None, None),
                        ValueError("not JSON"), URLError(TimeoutError("slow"))):
            with self.subTest(failure=failure), patch.object(self.services, "_json", side_effect=failure):
                with self.assertRaises(app.StartupError):
                    self.services.dashboard_ready("current")

    def test_install_preserves_workflow_and_quotes_paths(self):
        environment = {"XDG_DATA_HOME": str(self.root / "data with 中文 spaces"),
                       "XDG_CONFIG_HOME": str(self.root / "config")}
        before = (self.settings.hermes_home / "plugins/workflow/config.json").read_bytes()
        with patch.dict(os.environ, environment), patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)):
            entry = installer.install(self.settings, self.root / "desktop")
            self.assertEqual(app.Settings.load(), self.settings)
        self.assertEqual((self.settings.hermes_home / "plugins/workflow/config.json").read_bytes(), before)
        text = entry.read_text()
        self.assertIn('Exec=/usr/bin/python3 "', text)
        self.assertNotIn("sh -c", text)
        self.assertTrue((self.root / "desktop/多 Agent 工作流.desktop").stat().st_mode & 0o100)
        if validator := shutil.which("desktop-file-validate"):
            subprocess.run([validator, str(entry)], check=True, capture_output=True)


if __name__ == "__main__":
    unittest.main()
