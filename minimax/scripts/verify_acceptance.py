"""Check the acceptance evidence that is committed with the submission."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sdd_context.config import Settings  # noqa: E402
from sdd_context.db import connect  # noqa: E402
from sdd_context.powercontext import PowerContextStateStore  # noqa: E402


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    checks: list[bool] = []
    checks.append(check("demo summary exists", (ROOT / "demo/summary.json").exists()))
    checks.append(check("before log exists", (ROOT / "artifacts/test_logs/01_tests_before.log").exists()))
    checks.append(check("after log exists", (ROOT / "artifacts/test_logs/02_tests_after.log").exists()))
    checks.append(check("code diff exists", (ROOT / "artifacts/changes.diff").exists()))
    checks.append(check("minimax request record", (ROOT / "demo/minimax_records/call-01-request.json").exists()))
    checks.append(check("minimax response record", (ROOT / "demo/minimax_records/call-01-response.json").exists()))

    if (ROOT / "demo/summary.json").exists():
        summary = json.loads((ROOT / "demo/summary.json").read_text(encoding="utf-8"))
        before = summary.get("before_tests") or {}
        after = summary.get("after_tests") or {}
        checks.append(check("before failed", before.get("exit_code") == 1 and before.get("failed", 0) > 0, str(before.get("summary"))))
        checks.append(check("after passed", after.get("exit_code") == 0 and after.get("failed") == 0, str(after.get("summary"))))
        checks.append(check("state seq 3 after restart", summary.get("state_after_restart", {}).get("seq") == 3))
        checks.append(check("minimax participated", bool(summary.get("minimax_attempts"))))

    settings = Settings.load()
    conn = connect(settings, database=settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT version, status FROM documents WHERE doc_key='spec:BOOK-SPEC-001'")
            row = cur.fetchone()
            checks.append(check("spec 001 head is v2", row is not None and int(row[0]) == 2, str(row)))
            cur.execute("SELECT COUNT(*) FROM query_log")
            queries = int(cur.fetchone()[0])
            checks.append(check("seekdb query log populated", queries > 0, str(queries)))
            cur.execute("SELECT COUNT(*) FROM documents WHERE status='active'")
            docs = int(cur.fetchone()[0])
            checks.append(check("seekdb active documents", docs == 31, str(docs)))
    finally:
        conn.close()

    store = PowerContextStateStore(settings)
    if store.health():
        state = store.load_latest("BOOK-001")
        checks.append(check("PowerContext state readable", bool(state and state.get("seq") == 3), str((state or {}).get("seq"))))
    else:
        checks.append(check("PowerContext reachable", False, "start it with scripts/powercontext_service.py"))

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    checks.append(check("current pytest passes", result.returncode == 0, result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""))
    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
