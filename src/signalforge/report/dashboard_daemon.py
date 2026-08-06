"""Background dashboard process management (survives terminal close)."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from signalforge.bootstrap import warmup_native_libs
from signalforge.config import data_dir


def _root() -> Path:
    return Path(__file__).resolve().parents[3]


def _state_dir() -> Path:
    d = data_dir() / ".dashboard"
    d.mkdir(parents=True, exist_ok=True)
    return d


def pid_path() -> Path:
    return _state_dir() / "dashboard.pid"


def meta_path() -> Path:
    return _state_dir() / "dashboard.json"


def log_path() -> Path:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "dashboard.log"


def _read_meta() -> dict[str, Any]:
    if not meta_path().exists():
        return {}
    try:
        return json.loads(meta_path().read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _write_meta(meta: dict[str, Any]) -> None:
    meta_path().write_text(json.dumps(meta, indent=2), encoding="utf-8")


def _clear_state() -> None:
    pid_path().unlink(missing_ok=True)
    meta_path().unlink(missing_ok=True)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def pick_port(preferred: int = 8501) -> int:
    if port_free(preferred):
        return preferred
    for p in range(preferred + 1, preferred + 20):
        if port_free(p):
            return p
    raise RuntimeError(f"ポート {preferred}〜{preferred + 19} はすべて使用中です。")


def health_ok(port: int, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=timeout) as resp:
            return resp.read().decode().strip() == "ok"
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def status() -> dict[str, Any]:
    meta = _read_meta()
    pid = meta.get("pid")
    port = meta.get("port", 8501)
    url = meta.get("url", f"http://127.0.0.1:{port}")

    if pid and _pid_alive(int(pid)):
        running = health_ok(int(port))
        return {
            "running": running,
            "pid": int(pid),
            "port": int(port),
            "url": url,
            "log": str(log_path()),
        }

    if pid_path().exists():
        try:
            stale = int(pid_path().read_text(encoding="utf-8").strip())
        except ValueError:
            stale = None
        if stale and not _pid_alive(stale):
            _clear_state()

    if health_ok(port):
        return {"running": True, "pid": None, "port": port, "url": url, "log": str(log_path())}

    return {"running": False, "pid": None, "port": port, "url": url, "log": str(log_path())}


def stop() -> bool:
    meta = _read_meta()
    pid = meta.get("pid")
    stopped = False

    if pid and _pid_alive(int(pid)):
        os.kill(int(pid), signal.SIGTERM)
        stopped = True
        for _ in range(30):
            if not _pid_alive(int(pid)):
                break
            time.sleep(0.2)
        if _pid_alive(int(pid)):
            os.kill(int(pid), signal.SIGKILL)

    _clear_state()
    return stopped


def _streamlit_args(port: int) -> list[str]:
    dash = Path(__file__).resolve().parent / "dashboard.py"
    return [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dash),
        "--server.port",
        str(port),
        "--server.address",
        "127.0.0.1",
        "--server.headless",
        "true",
        "--browser.serverAddress",
        "127.0.0.1",
        "--browser.serverPort",
        str(port),
    ]


def _wait_for_server(port: int, proc: subprocess.Popen[Any], timeout_sec: float = 45.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        if health_ok(port):
            return True
        time.sleep(0.3)
    return health_ok(port)


def start(port: int = 8501, *, open_browser: bool = True, force: bool = False) -> dict[str, Any]:
    """Start dashboard in background; returns {url, port, pid, log}."""
    current = status()
    if current["running"] and not force:
        return {
            "already_running": True,
            "url": current["url"],
            "port": current["port"],
            "pid": current.get("pid"),
            "log": current["log"],
        }

    if force:
        stop()
        time.sleep(0.5)

    warmup_native_libs()
    port = pick_port(port)
    url = f"http://127.0.0.1:{port}"
    root = _root()
    env = os.environ.copy()
    env.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

    log = log_path()
    with open(log, "a", encoding="utf-8") as log_fp:
        log_fp.write(f"\n--- dashboard start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
        log_fp.flush()
        proc = subprocess.Popen(
            _streamlit_args(port),
            cwd=str(root),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log_fp,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    if not _wait_for_server(port, proc):
        if proc.poll() is None:
            proc.terminate()
        raise RuntimeError(f"ダッシュボードの起動に失敗しました。ログ: {log}")

    pid_path().write_text(str(proc.pid), encoding="utf-8")
    _write_meta({"pid": proc.pid, "port": port, "url": url, "started_at": time.time()})

    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url, new=2)
        except Exception:
            if sys.platform == "darwin":
                subprocess.run(["open", url], check=False)

    return {"already_running": False, "url": url, "port": port, "pid": proc.pid, "log": str(log)}


def run_foreground(port: int = 8501, *, no_browser: bool = False) -> None:
    """Blocking foreground run (stops when terminal closes)."""
    warmup_native_libs()
    port = pick_port(port)
    url = f"http://127.0.0.1:{port}"
    root = _root()
    env = os.environ.copy()
    env.setdefault("ARROW_DEFAULT_MEMORY_POOL", "system")

    dash = Path(__file__).resolve().parent / "dashboard.py"
    args = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(dash),
        "--server.port",
        str(port),
        "--server.address",
        "127.0.0.1",
        "--browser.serverAddress",
        "127.0.0.1",
        "--browser.serverPort",
        str(port),
    ]
    if no_browser:
        args.extend(["--server.headless", "true"])

    proc = subprocess.Popen(args, cwd=str(root), env=env)
    if _wait_for_server(port, proc) and not no_browser:
        try:
            import webbrowser

            webbrowser.open(url, new=2)
        except Exception:
            if sys.platform == "darwin":
                subprocess.run(["open", url], check=False)

    try:
        raise SystemExit(proc.wait())
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait(timeout=5)
