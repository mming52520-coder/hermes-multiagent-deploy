#!/usr/bin/env python3
"""Linux desktop entry for the already-installed Hermes workflow."""
from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

APP_ID = "local.hermes.Workflow"
APP_DIR = "hermes-workflow-desktop"
ORIGIN = "http://127.0.0.1:9119"
URL = ORIGIN + "/workflow"


def xdg_path(variable: str, fallback: str) -> Path:
    return Path(os.environ.get(variable) or Path.home() / fallback) / APP_DIR


class StartupError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    hermes_home: Path
    hermes_bin: Path
    web_dist: Path

    @classmethod
    def load(cls) -> Settings:
        data = json.loads((xdg_path("XDG_CONFIG_HOME", ".config") / "config.json").read_text())
        return cls(**{name: Path(data[name]) for name in cls.__dataclass_fields__})

    def validate(self) -> None:
        for path in (self.hermes_bin, self.web_dist / "index.html",
                     self.hermes_home / "plugins/workflow/config.json"):
            if not path.is_file():
                raise StartupError(f"找不到所需文件：{path}\n请恢复文件或重新运行桌面入口安装器。")
        if not os.access(self.hermes_bin, os.X_OK):
            raise StartupError(f"Hermes 启动程序不可执行：{self.hermes_bin}")

    def environment(self) -> dict[str, str]:
        return {**os.environ, "HERMES_HOME": str(self.hermes_home),
                "HERMES_WEB_DIST": str(self.web_dist), "HERMES_DESKTOP": "0"}


class Services:
    """Keep ownership of a pending dashboard start across the UI's retry button."""

    def __init__(self, settings: Settings, state_dir: Path):
        self.settings = settings
        self.state_dir = state_dir
        self.dashboard_process: subprocess.Popen | None = None
        # Loopback service checks must not go through a user's HTTP proxy.
        self.http = build_opener(ProxyHandler({}))

    def _json(self, path: str) -> dict:
        with self.http.open(ORIGIN + path, timeout=3) as response:
            result = json.load(response)
        if not isinstance(result, dict):
            raise ValueError("服务返回的内容不是 JSON 对象")
        return result

    def dashboard_ready(self, commit: str) -> bool:
        try:
            health = self._json("/api/health")
        except HTTPError as exc:
            raise StartupError(f"端口 9119 的服务未通过 Hermes 检查：HTTP {exc.code}。未替换该服务。") from exc
        except URLError as exc:
            if isinstance(exc.reason, OSError) and exc.reason.errno == errno.ECONNREFUSED:
                return False
            raise StartupError(f"无法检查本地服务：{exc}") from exc
        except (ValueError, TimeoutError) as exc:
            raise StartupError(f"端口 9119 已响应，但未返回有效的 Hermes 状态：{exc}") from exc
        if health.get("ok") is not True or health.get("commit") != commit:
            raise StartupError("端口 9119 上的服务与当前 Hermes 版本不匹配。请处理原服务后重试。")
        status = self._json("/api/status")
        identity = (self.settings.hermes_home / "install_id").read_text(encoding="utf-8-sig").strip().lower()
        if not identity or status.get("install_id") != identity:
            raise StartupError("端口 9119 上的服务属于其他 Hermes 数据目录。未连接或替换该服务。")
        return True

    def start(self, report, *, timeout: float = 60) -> None:
        self.settings.validate()
        self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        command = [str(self.settings.hermes_bin), "--profile", "default"]
        environment = self.settings.environment()
        report("正在检查并启动后台网关…")
        try:
            result = subprocess.run(
                command + ["gateway", "ensure", "--json", "--timeout", str(timeout)],
                env=environment, cwd=self.settings.hermes_home, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=timeout + 15,
            )
        except subprocess.TimeoutExpired as exc:
            raise StartupError("后台网关检查超时。请查看 Hermes 网关日志，处理后重试。") from exc
        logging.info("gateway ensure: exit=%s\n%s\n%s", result.returncode, result.stdout, result.stderr)
        try:
            gateway = json.loads(result.stdout)
        except ValueError as exc:
            raise StartupError(f"Hermes 未返回有效的网关结果：\n{result.stderr or result.stdout}") from exc
        # Match the native interactive attach contract: restart_wait still owns
        # active turns, including approvals the user needs to answer in this UI.
        waiting = (result.returncode == 6 and gateway.get("state") == "draining"
                   and gateway.get("reason_code") == "restart_wait")
        ready = result.returncode == 0 and gateway.get("state") == "ready"
        endpoint = gateway.get("endpoint") or {}
        if not (ready or waiting) or not endpoint:
            raise StartupError(f"后台网关未就绪：{gateway.get('state')} / {gateway.get('reason_code')}\n"
                               f"{gateway.get('detail') or result.stderr}")
        commit = gateway.get("client_code_sha")
        if not commit or endpoint.get("code_sha") != commit:
            raise StartupError("后台网关仍在运行旧版本。请在现有任务结束后更新网关，再重试。")
        report("正在检查工作流页面…")
        if self.dashboard_ready(commit):
            logging.info("Reused existing dashboard")
            return
        report("正在启动工作流页面…")
        log_file = self.state_dir / "dashboard.log"
        if self.dashboard_process is None or self.dashboard_process.poll() is not None:
            with log_file.open("a", encoding="utf-8") as output:
                self.dashboard_process = subprocess.Popen(
                    command + ["dashboard", "--host", "127.0.0.1", "--port", "9119", "--skip-build", "--no-open"],
                    env=environment, cwd=self.settings.hermes_home, stdin=subprocess.DEVNULL,
                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True,
                )
            logging.info("Started dashboard pid=%s", self.dashboard_process.pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.dashboard_ready(commit):
                logging.info("Dashboard ready")
                return
            code = self.dashboard_process.poll()
            if code is not None and code != 0:
                raise StartupError(f"工作流服务启动失败（退出码 {code}）。\n{log_file.read_text(errors='replace')[-6000:]}")
            time.sleep(0.3)
        raise StartupError(f"工作流页面尚未就绪。可稍后重试；同一启动进程会被复用。\n日志：{log_file}")


def main() -> int:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2

    GLib.set_application_name("多 Agent 工作流")
    Gdk.set_program_class(APP_ID)

    # Session cookies, browser storage and local diagnostics remain per-user.
    os.umask(0o077)
    state_dir = xdg_path("XDG_STATE_HOME", ".local/state")
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    logging.basicConfig(filename=state_dir / "startup.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    class Application(Gtk.Application):
        def __init__(self):
            super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
            self.window = None
            self.services = None
            self.busy = False
            self.webview = None

        def do_activate(self):
            if self.window is not None:
                self.window.present()
                return
            self.window = Gtk.ApplicationWindow(application=self, title="多 Agent 工作流")
            self.window.set_default_size(1320, 880)
            self.window.set_icon_from_file(str(Path(__file__).with_name("workflow-desktop.svg")))
            header = Gtk.HeaderBar(title="多 Agent 工作流", show_close_button=True)
            reconnect = Gtk.Button(label="重新连接")
            reconnect.connect("clicked", lambda *_: self.start())
            header.pack_start(reconnect)
            browser = Gtk.Button(label="在浏览器中打开")
            browser.connect("clicked", lambda *_: Gtk.show_uri_on_window(self.window, URL, Gtk.get_current_event_time()))
            header.pack_end(browser)
            self.window.set_titlebar(header)
            self.stack = Gtk.Stack()
            self.window.add(self.stack)
            panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20,
                            halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER, margin=30)
            self.spinner = Gtk.Spinner()
            panel.pack_start(self.spinner, False, False, 0)
            self.message = Gtk.Label(label="正在准备工作流…", wrap=True, selectable=True, max_width_chars=90)
            panel.pack_start(self.message, False, False, 0)
            self.retry = Gtk.Button(label="重试")
            self.retry.connect("clicked", lambda *_: self.start())
            panel.pack_start(self.retry, False, False, 0)
            logs = Gtk.Button(label="查看启动日志")
            logs.connect("clicked", lambda *_: Gtk.show_uri_on_window(
                self.window, (state_dir / "startup.log").as_uri(), Gtk.get_current_event_time()))
            panel.pack_start(logs, False, False, 0)
            self.stack.add_named(panel, "status")
            self.window.show_all()
            self.start()

        def start(self):
            if self.busy:
                return
            self.busy = True
            self.retry.set_sensitive(False)
            self.stack.set_visible_child_name("status")
            self.spinner.start()
            self.message.set_text("正在准备工作流…")
            threading.Thread(target=self.worker, daemon=True).start()

        def worker(self):
            try:
                settings = Settings.load()
                if self.services is None or self.services.settings != settings:
                    self.services = Services(settings, state_dir)
                self.services.start(lambda message: GLib.idle_add(self.message.set_text, message))
            except Exception as exc:
                logging.exception("Startup failed")
                GLib.idle_add(self.failed, str(exc))
            else:
                GLib.idle_add(self.open_workflow)

        def failed(self, message):
            self.busy = False
            self.spinner.stop()
            self.retry.set_sensitive(True)
            self.stack.set_visible_child_name("status")
            self.message.set_text("工作流尚未打开\n\n" + message)

        def open_workflow(self):
            if self.webview is None:
                data_dir = xdg_path("XDG_DATA_HOME", ".local/share") / "browser"
                cache_dir = xdg_path("XDG_CACHE_HOME", ".cache")
                data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
                manager = WebKit2.WebsiteDataManager(base_data_directory=str(data_dir), base_cache_directory=str(cache_dir))
                context = WebKit2.WebContext.new_with_website_data_manager(manager)
                context.get_cookie_manager().set_persistent_storage(
                    str(data_dir / "cookies.sqlite"), WebKit2.CookiePersistentStorage.SQLITE)
                context.connect("download-started", self.download_started)
                self.webview = WebKit2.WebView(web_context=context)
                self.webview.connect("load-failed", self.load_failed)
                self.webview.connect("create", self.open_link)
                self.stack.add_named(self.webview, "workflow")
            self.busy = False
            self.spinner.stop()
            self.retry.set_sensitive(True)
            self.webview.load_uri(URL)
            self.webview.show()
            self.stack.set_visible_child_name("workflow")

        def load_failed(self, _view, _event, _uri, error):
            # A user-triggered reload cancels the previous navigation normally.
            if error.matches(WebKit2.network_error_quark(), WebKit2.NetworkError.CANCELLED):
                return False
            logging.error("Page load failed: %s", error.message)
            self.failed(error.message)
            return True

        def open_link(self, _view, action):
            Gtk.show_uri_on_window(self.window, action.get_request().get_uri(), Gtk.get_current_event_time())
            return None

        def download_started(self, _context, download):
            download.connect("decide-destination", self.download_destination)

        def download_destination(self, download, suggested_name):
            dialog = Gtk.FileChooserDialog(title="保存文件", transient_for=self.window,
                                           action=Gtk.FileChooserAction.SAVE)
            dialog.add_buttons("取消", Gtk.ResponseType.CANCEL, "保存", Gtk.ResponseType.ACCEPT)
            dialog.set_do_overwrite_confirmation(True)
            dialog.set_current_name(suggested_name)
            if dialog.run() == Gtk.ResponseType.ACCEPT:
                download.set_allow_overwrite(True)
                download.set_destination(dialog.get_uri())
            else:
                download.cancel()
            dialog.destroy()
            return True

    return Application().run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
