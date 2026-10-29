"""Start, stop, and inspect a local PowerContext Server.

Usage:
    python scripts/powercontext_service.py start
    python scripts/powercontext_service.py status
    python scripts/powercontext_service.py stop

Set ``POWERCONTEXT_EXE`` when ``powercontext`` is not on PATH.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env.powercontext"
PID_FILE = ROOT / "demo" / "runtime" / "powercontext.pid"
LOG_FILE = ROOT / "demo" / "runtime" / "powercontext.log"


def _env_value(name: str, default: str = "") -> str:
    if not ENV_FILE.exists():
        return default
    for line in ENV_FILE.read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() == name:
                return value.strip()
    return default


def _exe() -> Path:
    candidates = [
        os.environ.get("POWERCONTEXT_EXE"),
        shutil.which("powercontext"),
        str(ROOT / ".venv" / "Scripts" / "powercontext.exe"),
        str(ROOT / ".venv" / "bin" / "powercontext"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise SystemExit("powercontext CLI not found; install it and/or set POWERCONTEXT_EXE")


def _port() -> int:
    return int(_env_value("POWERCONTEXT_SERVER_HTTP_PORT", "8765"))


def _url() -> str:
    return f"http://127.0.0.1:{_port()}"


def health() -> bool:
    try:
        with urllib.request.urlopen(f"{_url()}/health/live", timeout=3) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def _pid() -> int | None:
    if not PID_FILE.exists():
        return None
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def start() -> int:
    if health():
        print(f"already healthy at {_url()}")
        return 0
    if not ENV_FILE.exists():
        raise SystemExit(f"missing {ENV_FILE}; copy .env.powercontext.example and edit the absolute paths")
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["TMP"] = os.environ.get("POWERCONTEXT_TMP", str(ROOT / "demo" / "runtime" / "work"))
    env["TEMP"] = env["TMP"]
    Path(env["TMP"]).mkdir(parents=True, exist_ok=True)
    log = LOG_FILE.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [str(_exe()), "server", "run", "--env-file", str(ENV_FILE)],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        env=env,
    )
    PID_FILE.write_text(str(process.pid), encoding="utf-8")
    for _ in range(120):
        if health():
            print(f"PowerContext healthy at {_url()} (pid {process.pid})")
            return 0
        if process.poll() is not None:
            print(f"PowerContext exited with {process.returncode}; see {LOG_FILE}", file=sys.stderr)
            return 1
        time.sleep(0.5)
    print("PowerContext did not become healthy in time", file=sys.stderr)
    return 1


def stop() -> int:
    pid = _pid()
    if pid is None:
        print("no pid file; nothing to stop")
        return 0
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        pass
    for _ in range(30):
        if not health():
            PID_FILE.unlink(missing_ok=True)
            print("stopped")
            return 0
        time.sleep(0.5)
    print("process still healthy; stop it manually", file=sys.stderr)
    return 1


def status() -> int:
    print(f"url: {_url()}")
    print(f"healthy: {health()}")
    print(f"pid: {_pid()}")
    return 0 if health() else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    args = parser.parse_args()
    return {"start": start, "stop": stop, "status": status}[args.action]()


if __name__ == "__main__":
    raise SystemExit(main())
