"""Opt-in real Hermes startup smoke; isolated data, no model calls or messaging.

Run with the existing `hermes` on PATH: python3 tests/desktop_native_smoke.py
The forwarding shim changes the UI port and native host-lock directory for
isolation; changing HERMES_HOME alone does not isolate host-wide rendezvous.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_desktop as app


def main():
    binary = shutil.which("hermes")
    if binary is None:
        raise SystemExit("An installed Hermes runtime is required")
    root = Path(tempfile.mkdtemp(prefix="workflow-desktop-native-"))
    home, web = root / "home", root / "web"
    home.mkdir(mode=0o700)
    web.mkdir()
    (home / "config.yaml").write_text("{}\n")
    (home / "plugins/workflow").mkdir(parents=True)
    (home / "plugins/workflow/config.json").write_text("{}\n")
    (web / "index.html").write_text("<!doctype html><title>Desktop startup fixture</title>")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    shim = root / "hermes"
    shim.write_text(
        "#!/usr/bin/python3\nimport os, sys\nargs = sys.argv[1:]\n"
        f"os.environ['HERMES_GATEWAY_LOCK_DIR'] = {str(root / 'host-locks')!r}\n"
        f"if 'dashboard' in args and '--port' in args: args[args.index('--port') + 1] = {str(port)!r}\n"
        f"os.execv({binary!r}, [{binary!r}, *args])\n")
    shim.chmod(0o700)
    settings = app.Settings(home, shim, web)
    services = app.Services(settings, root / "logs")
    app.ORIGIN = f"http://127.0.0.1:{port}"
    cleanup_ok = False
    try:
        started = time.monotonic()
        services.start(lambda message: print(message, flush=True))
        process = services.dashboard_process
        assert process is not None and process.poll() is None
        first_pid = process.pid
        with services.http.open(app.ORIGIN + "/workflow") as response:
            assert b"Desktop startup fixture" in response.read()
        services.start(lambda message: print(message, flush=True))
        assert services.dashboard_process.pid == first_pid
        assert services.dashboard_process.poll() is None
        # Exiting a UI client is independent of the detached server process.
        assert os.getsid(first_pid) == first_pid
        print(json.dumps({"result": "PASS", "cold_start_and_reuse": True,
                          "dashboard_pid": first_pid, "port": port,
                          "elapsed_seconds": round(time.monotonic() - started, 2),
                          "launcher_sha256": hashlib.sha256(Path(app.__file__).read_bytes()).hexdigest(),
                          "evidence_directory": str(root)}, indent=2), flush=True)
    finally:
        if services.dashboard_process is not None and services.dashboard_process.poll() is None:
            services.dashboard_process.terminate()
            services.dashboard_process.wait(timeout=20)
        stopped = subprocess.run([str(shim), "--profile", "default", "gateway", "stop"],
                                 env=settings.environment(), stdin=subprocess.DEVNULL,
                                 capture_output=True, text=True, timeout=30)
        (root / "cleanup.log").write_text(stopped.stdout + stopped.stderr)
        cleanup_ok = stopped.returncode == 0
        print(f"Isolated gateway cleanup: {'PASS' if cleanup_ok else 'FAILED'}; evidence: {root}", flush=True)
        if not cleanup_ok:
            raise RuntimeError(f"Isolated gateway did not stop: {root / 'cleanup.log'}")


if __name__ == "__main__":
    main()
