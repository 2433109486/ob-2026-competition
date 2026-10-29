"""Reproduce the baseline failure without touching the final working tree.

Copies ``artifacts/before`` and ``tests`` into a throw-away directory, runs
pytest there, and writes the log under ``artifacts/test_logs``. The expected
result is 11 failed, 9 passed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "demo" / "runtime" / "before_repro"
LOG = ROOT / "artifacts" / "test_logs" / "00_before_repro.log"


def main() -> int:
    shutil.rmtree(WORK, ignore_errors=True)
    (WORK / "booknest").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        ROOT / "booknest",
        WORK / "booknest",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    for source in (ROOT / "artifacts" / "before" / "booknest").glob("*.py"):
        shutil.copy2(source, WORK / "booknest" / source.name)
    shutil.copytree(ROOT / "tests", WORK / "tests", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "pyproject.toml", WORK / "pyproject.toml")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(WORK)
    env["PYTHONIOENCODING"] = "utf-8"
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=WORK,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=180,
    )
    summary = ""
    for line in (result.stdout + "\n" + result.stderr).splitlines():
        if " passed" in line or " failed" in line:
            summary = line.strip()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(
        f"command: {sys.executable} -m pytest -q\n"
        f"cwd: {WORK}\n"
        f"phase: before (artifacts/before snapshot)\n"
        f"exit_code: {result.returncode}\n"
        f"pytest_summary: {summary}\n"
        "---- output ----\n" + result.stdout + ("\n[stderr]\n" + result.stderr if result.stderr else ""),
        encoding="utf-8",
    )
    print(json.dumps({"exit_code": result.returncode, "summary": summary, "log": str(LOG.relative_to(ROOT))}, ensure_ascii=False, indent=2))
    shutil.rmtree(WORK, ignore_errors=True)
    return 0 if result.returncode != 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
