"""Focused native v0.22.5 model setup contracts; no inference or provider requests."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import check_workflow_writes_v0225 as fixtures
from configure_profiles import read_yaml
import workflow_models as models
from hermes_cli.config import load_env
import workflow_runtime

REPO = fixtures.REPO

PROVIDERS = [
    {"id": "openrouter", "label": "OpenRouter", "key_env": "OPENROUTER_API_KEY", "default_model": "synthetic/shared", "models": ["synthetic/shared"], "base_url": "https://openrouter.ai/api/v1", "protocol": "chat_completions", "signup_url": ""},
    {"id": "openai-api", "label": "OpenAI API", "key_env": "OPENAI_API_KEY", "default_model": "synthetic-code", "models": ["synthetic-code"], "base_url": "https://api.openai.com/v1", "protocol": "native", "signup_url": ""},
    {"id": "anthropic", "label": "Anthropic", "key_env": "ANTHROPIC_API_KEY", "default_model": "synthetic-review", "models": ["synthetic-review"], "base_url": "https://api.anthropic.com", "protocol": "anthropic_messages", "signup_url": ""},
    {"id": "custom", "label": "Custom", "key_env": "HERMES_WORKFLOW_API_KEY", "default_model": "", "models": [], "base_url": "", "protocol": "chat_completions", "signup_url": ""},
]


class ModelConnectionsTest(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowWrites()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.home = self.fixture.home
        self.catalog = patch.object(models, "catalog", return_value=PROVIDERS)
        self.catalog_mock = self.catalog.start(); self.addCleanup(self.catalog.stop)

    def test_first_connection_creates_the_four_native_profiles(self):
        import shutil
        for role in models.ROLES:
            shutil.rmtree(self.home / "profiles" / role)
        models.ensure_profiles(self.fixture.workflow, list(models.ROLES))
        models.save(self.home, list(models.ROLES), provider="openrouter", api_key="synthetic-first-key")
        for role in models.ROLES:
            directory = self.home / "profiles" / role
            config = read_yaml(directory / "config.yaml")
            self.assertEqual(config["model"]["provider"], "openrouter")
            self.assertEqual(config["terminal"]["backend"], "docker")
            self.assertTrue((directory / "SOUL.md").is_file())

    def test_shared_key_and_independent_provider_model_endpoint_overrides(self):
        result = models.save(self.home, list(models.ROLES), provider="openrouter", api_key="synthetic-shared-key")
        self.assertTrue(all(row["has_key"] for row in result))
        models.save(self.home, ["builder"], provider="openai-api", model="code-model", api_key="synthetic-code-key")
        models.save(self.home, ["reviewer"], provider="anthropic", api_key="synthetic-review-key")
        models.save(self.home, ["researcher"], provider="custom", model="local-model", api_key="synthetic-local-key",
                    base_url="http://127.0.0.1:11434/v1", protocol="chat_completions")
        self.assertEqual(models.profile_settings(self.home, "orchestrator")["provider"], "openrouter")
        self.assertEqual(models.profile_settings(self.home, "builder")["model"], "code-model")
        self.assertEqual(models.profile_settings(self.home, "reviewer")["provider"], "anthropic")
        research = models.profile_settings(self.home, "researcher")
        self.assertEqual(research["base_url"], "http://127.0.0.1:11434/v1")
        self.assertEqual(research["protocol"], "chat_completions")
        for role in models.ROLES:
            config = self.home / "profiles" / role / "config.yaml"
            self.assertNotIn("synthetic-shared-key", config.read_text())
            self.assertEqual(read_yaml(config)["terminal"]["backend"], "docker")
            self.assertEqual((config.parent / ".env").stat().st_mode & 0o777, 0o600)
        public = json.dumps([models.profile_settings(self.home, role) for role in models.ROLES])
        self.assertNotIn("synthetic-code-key", public)
        self.assertNotIn("api_key", public)

    def test_empty_key_reuses_only_the_selected_profiles_existing_credential(self):
        models.save(self.home, ["builder"], provider="openai-api", api_key="synthetic-existing-key")
        models.save(self.home, ["builder"], provider="openai-api", model="updated-model")
        with workflow_runtime.home_scope(self.home / "profiles" / "builder"):
            self.assertEqual(load_env()["OPENAI_API_KEY"], "synthetic-existing-key")
        with self.assertRaisesRegex(ValueError, "API Key"):
            models.save(self.home, ["researcher"], provider="openai-api")

    def test_import_fetches_live_models_with_each_roles_own_key_without_assigning(self):
        seen = []
        accounts = {"Bearer synthetic-builder-key": "builder-model", "Bearer synthetic-research-key": "research-model"}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                auth = self.headers["Authorization"]
                seen.append(auth)
                payload = json.dumps({"data": [{"id": accounts[auth]}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        endpoint = f"http://127.0.0.1:{server.server_port}/v1"
        builder = models.discover("builder", provider="openai-api", api_key="synthetic-builder-key", base_url=endpoint)
        research = models.discover("researcher", provider="openai-api", api_key="synthetic-research-key", base_url=endpoint)
        reused = models.discover("builder", provider="openai-api", base_url=endpoint)
        self.assertEqual(builder["models"], ["builder-model"])
        self.assertEqual(research["models"], ["research-model"])
        self.assertEqual(reused["models"], ["builder-model"])
        self.assertEqual(seen, ["Bearer synthetic-builder-key", "Bearer synthetic-research-key", "Bearer synthetic-builder-key"])
        for role in ("builder", "researcher"):
            self.assertEqual(models.profile_settings(self.home, role)["provider"], "test-provider")
        self.assertNotIn("synthetic-builder-key", json.dumps(builder))

    def test_gemini_catalog_uses_key_header_and_lists_generation_models_across_pages(self):
        self.catalog_mock.return_value = [*PROVIDERS, {"id": "gemini", "key_env": "GOOGLE_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta", "models": []}]
        pages = [
            {"models": [{"name": "models/gemini-first", "supportedGenerationMethods": ["generateContent"]},
                         {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]}], "nextPageToken": "next page"},
            {"models": [{"name": "models/gemini-second", "supportedGenerationMethods": ["generateContent"]}]},
        ]
        with patch("hermes_cli.models._get_json", side_effect=pages) as fetch:
            result = models.discover("reviewer", provider="gemini", api_key="synthetic-google-key")
        self.assertEqual(result["models"], ["gemini-first", "gemini-second"])
        self.assertEqual(fetch.call_args_list[0].kwargs["headers"], {"x-goog-api-key": "synthetic-google-key"})
        self.assertIn("pageToken=next+page", fetch.call_args_list[1].args[0])

    def test_http_save_updates_one_pending_role_and_requires_new_approval(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from hermes_cli import web_server

        def load(name, file):
            spec = importlib.util.spec_from_file_location(name, file)
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            return module

        installer = load("model_connections_installer", REPO / "scripts/install-workflow-app.py")
        binding = self.fixture.directory / "workflow.env"
        binding.write_text("\n".join(f"{key}={value}" for key, value in self.fixture.env.items()))
        plugin = installer.install(self.home, binding)
        settings_file = plugin / "config.json"
        settings = json.loads(settings_file.read_text()); settings["allow_actions"] = True
        settings_file.write_text(json.dumps(settings))
        api = load("model_connections_api_" + self.fixture.execution, plugin / "dashboard/plugin_api.py")
        core = api.core_module()
        service = api.models_module()
        app = FastAPI(); app.include_router(api.router, prefix="/api/plugins/workflow")
        client = TestClient(app)
        client.headers.update({"X-Hermes-Session-Token": "synthetic-session", "X-Hermes-Workflow-Action": "1"})
        payload = {"role": "builder", "provider": "openai-api", "api_key": "synthetic-browser-key", "execution": self.fixture.execution}
        self.fixture.workflow.approve(self.fixture.execution)
        with patch.object(web_server, "_SESSION_TOKEN", "synthetic-session"), patch.object(core, "verify_source", return_value={}), \
                patch.object(service, "catalog", return_value=PROVIDERS):
            url = "/api/plugins/workflow/model-connection"
            self.assertEqual(TestClient(app).get(url).status_code, 401)
            response = client.put(url, json=payload)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn("synthetic-browser-key", response.text)
            self.assertFalse(self.fixture.workflow.load(self.fixture.execution)["approved_write"])
            settings = client.get(url + "?execution=" + self.fixture.execution).json()
            self.assertEqual(settings["roles"]["builder"]["provider"], "openai-api")
            self.assertEqual(settings["roles"]["researcher"]["provider"], "test-provider")
            self.assertEqual(set(self.fixture.statuses().values()), {"triage"})
            # Unified import only stores each base role's key; selection is saved separately.
            before = models.profile_settings(self.home, "builder")["model"]
            with patch("providers.get_provider_profile", return_value=None), patch("hermes_cli.models.fetch_api_models", return_value=["synthetic-listed"]):
                discovered = client.post("/api/plugins/workflow/model-connections/models", json={"connections": {
                    "builder": {"provider": "openai-api", "api_key": "synthetic-new-builder-key"},
                    "reviewer": {"provider": "anthropic", "api_key": "synthetic-new-review-key"},
                }})
            self.assertEqual(discovered.status_code, 200, discovered.text)
            self.assertEqual(discovered.json()["roles"]["builder"]["models"], ["synthetic-listed"])
            self.assertNotIn("synthetic-new-builder-key", discovered.text)
            self.assertEqual(models.profile_settings(self.home, "builder")["model"], before)
            self.fixture.workflow.approve(self.fixture.execution)
            selected = client.put("/api/plugins/workflow/model-connections", json={"execution": self.fixture.execution, "connections": {
                "builder": {"provider": "openai-api", "model": "builder-chosen"},
                "reviewer": {"provider": "anthropic", "model": "reviewer-chosen"},
            }})
            self.assertEqual(selected.status_code, 200, selected.text)
            self.assertFalse(self.fixture.workflow.load(self.fixture.execution)["approved_write"])
            scoped = client.get(url + "?execution=" + self.fixture.execution).json()["roles"]
            self.assertEqual(scoped["builder"]["model"], "builder-chosen")
            self.assertEqual(scoped["reviewer"]["model"], "reviewer-chosen")
            self.assertEqual(scoped["researcher"]["provider"], "test-provider")
            self.assertNotIn("synthetic-new-builder-key", selected.text)
            self.fixture.workflow.start(self.fixture.execution, True)
            self.assertEqual(client.put(url, json=payload).status_code, 409)
            self.assertEqual(client.put("/api/plugins/workflow/model-connections", json={"execution": self.fixture.execution,
                "connections": {"builder": {"provider": "openai-api", "model": "after-launch"}}}).status_code, 409)


if __name__ == "__main__":
    unittest.main(verbosity=2)
