"""Collect the technical evidence referenced by the submission docs."""

from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402
from app.config import settings  # noqa: E402
from app.memory import client  # noqa: E402

OUT = ROOT / "docs" / "evidence"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "http://127.0.0.1:7860"


def get_json(path: str) -> dict:
    with urllib.request.urlopen(BASE + path, timeout=30) as response:
        return json.load(response)


def post_json(path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> int:
    (OUT / "health.json").write_text(json.dumps(get_json("/api/health"), ensure_ascii=False, indent=2), encoding="utf-8")
    boot = get_json("/api/bootstrap")
    (OUT / "bootstrap.json").write_text(json.dumps(boot, ensure_ascii=False, indent=2), encoding="utf-8")

    trace = post_json(
        "/api/search",
        {"query": "AI 编程助手对初学者学习迁移的影响", "limit": 8},
    )
    (OUT / "search_trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")

    # Use the application client so this exercises the same scope file and parsing path.
    entries = client.list_entries()
    (OUT / "powercontext_entries.json").write_text(
        json.dumps({"scope_id": client.ensure_scope(), "entries": entries}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if client.evidence_file.exists():
        shutil.copyfile(client.evidence_file, OUT / "powercontext_calls.jsonl")

    lines = []
    lines.append(f"seekdb: {db.ping()}")
    lines.append("")
    lines.append("tables:")
    for table, count in db.table_counts().items():
        lines.append(f"  {table}: {count}")
    lines.append("")
    conn = db.connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            for table in ["papers", "chunks", "notes", "search_log"]:
                cur.execute(f"SHOW CREATE TABLE `{table}`")
                row = cur.fetchone()
                lines.append(f"--- SHOW CREATE TABLE {table} ---")
                lines.append(next(iter(row.values())))
                lines.append("")
            cur.execute(
                "SELECT chunk_id, paper_id, section, page, LEFT(content, 60) AS preview FROM chunks ORDER BY chunk_id LIMIT 8"
            )
            lines.append("sample chunks:")
            for row in cur.fetchall():
                lines.append(f"  {row['chunk_id']} | {row['paper_id']} | {row['section']} | {row['page']} | {row['preview']}")
            cur.execute(
                "SELECT query, result_count, latency_ms, memory_used, created_at FROM search_log ORDER BY created_at DESC LIMIT 8"
            )
            lines.append("")
            lines.append("recent search_log:")
            for row in cur.fetchall():
                lines.append(f"  {row['created_at']} | {row['result_count']} results | {row['latency_ms']} ms | memory={row['memory_used']} | {row['query']}")
    finally:
        conn.close()
    (OUT / "seekdb_schema.txt").write_text("\n".join(lines), encoding="utf-8")

    (OUT / "README.md").write_text(
        """# 证据索引

| 文件 | 内容 | 生成方式 |
| --- | --- | --- |
| `health.json` | seekdb / PowerContext / embedding 健康状态 | `GET /api/health` |
| `bootstrap.json` | 资料数、画像、统计、推荐 | `GET /api/bootstrap` |
| `search_trace.json` | 一次混合检索的完整结果、候选数、两条 SQL | `POST /api/search` |
| `seekdb_schema.txt` | 建表语句、行数、样例片段、最近检索日志 | `SHOW CREATE TABLE` + `SELECT` |
| `powercontext_entries.json` | 当前 Scope 的 Atomic Memory | `POST /v1/memory/entries/list` |
| `powercontext_calls.jsonl` | 每次 PowerContext HTTP 调用（path/status/kind/scope） | 应用运行时追加 |
| `acceptance.json` | 21 项自动验收结果 | `scripts/acceptance.py` |
| `pytest.txt` | 7 项 pytest 结果 | `pytest -q` |

> 这些文件由本机真实运行生成。UUID、时间戳、耗时每次重跑会变化。
""",
        encoding="utf-8",
    )
    print(f"evidence written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
