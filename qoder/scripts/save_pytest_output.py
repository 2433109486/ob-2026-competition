"""Run pytest and save a UTF-8 text report (avoids PowerShell UTF-16 output)."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = Path(r"D:\agent\sandbox\pc-venv\Scripts\python.exe")
if not PYTHON.exists():
    PYTHON = Path("python")

result = subprocess.run(
    [str(PYTHON), "-m", "pytest", "-q"],
    cwd=ROOT,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
report = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
(ROOT / "docs" / "evidence" / "pytest.txt").write_text(
    "$ pytest -q\n" + report.strip() + f"\n\nexit_code={result.returncode}\n",
    encoding="utf-8",
)
print(report.strip())
raise SystemExit(result.returncode)
