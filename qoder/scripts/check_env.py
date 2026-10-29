"""Print a short, actionable environment check."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import client  # noqa: E402


def main() -> int:
    ok = True
    print(f"project: {settings.project_root}")
    print(f"seekdb:  {settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}")
    try:
        info = db.ping()
        print(f"  [OK] {info['version']}  ({info['latency_ms']} ms)")
        print(f"  [OK] papers={db.table_counts().get('papers', 0)}")
    except Exception as error:  # noqa: BLE001
        ok = False
        print(f"  [FAIL] {error}")
        print("  hint: start seekdb and verify port 2881; then run scripts/init_db.py")

    health = client.health()
    print(f"powercontext: {settings.powercontext_url}")
    if health.get("ok"):
        print(f"  [OK] scope={health.get('scope_id')}  ({health.get('latency_ms')} ms)")
    else:
        ok = False
        print(f"  [FAIL] {health.get('error')}")
        print("  hint: start PowerContext on 8765 or set POWERCONTEXT_ENABLED=false for degraded mode")

    print("result:", "ready" if ok else "needs attention")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
