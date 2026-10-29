"""Create a clean PowerContext scope for the demo and seed its memories.

The old scope is retained in the server; this script only changes the scope file
used by the application. Useful before recording a demo or capturing screenshots.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import client  # noqa: E402


def main() -> int:
    scope_key = "yanmai-demo-" + datetime.now().strftime("%Y%m%d%H%M%S")
    response = client._request(  # noqa: SLF001 - explicit maintenance script
        "POST",
        "/v1/scopes",
        {
            "title": "研脉 · 研究上下文",
            "summary": "Research profile, reading progress and review decisions for ResearchPulse",
            "idempotency_key": scope_key,
        },
    )
    scope = response.get("scope_id") or response.get("id")
    if not scope:
        raise SystemExit(f"scope creation failed: {response}")
    settings.ensure_runtime_dirs()
    client.scope_file.write_text(str(scope), encoding="utf-8")
    client.evidence_file.write_text("", encoding="utf-8")
    papers = db.fetch_papers(limit=100)
    result = client.seed_demo_memories(papers)
    print(json.dumps({"scope_id": scope, "seed": result}, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
