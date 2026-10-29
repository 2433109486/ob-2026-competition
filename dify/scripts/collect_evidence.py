"""抓取运行证据：后端健康、seekdb 落库、PowerContext 记忆。

在跑完 scripts/run_demo.py 之后执行：
    python scripts/collect_evidence.py --out evidence
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

import pymysql
from pymysql.cursors import DictCursor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

API = "http://127.0.0.1:8088"
PC = "http://127.0.0.1:8000"


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def db() -> pymysql.connections.Connection:
    return pymysql.connect(
        host="127.0.0.1",
        port=2881,
        user="root",
        password="",
        database="absurd_court",
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "evidence"))
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    health = get(API + "/api/v1/health")
    (out / "service_health.json").write_text(json.dumps(health, ensure_ascii=False, indent=2), encoding="utf-8")

    records: dict[str, object] = {
        "collected_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "seekdb_version": None,
        "statutes": {},
        "precedents": [],
        "players": {},
        "cases": [],
        "turns": [],
    }
    conn = db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS v")
            records["seekdb_version"] = cur.fetchone()["v"]
            cur.execute("SELECT COUNT(*) AS n FROM statutes")
            records["statutes"]["count"] = cur.fetchone()["n"]
            cur.execute("SELECT code, title, tag, min_days, max_days FROM statutes ORDER BY code LIMIT 12")
            records["statutes"]["sample"] = list(cur.fetchall())
            cur.execute(
                "SELECT id, case_no, player_id, defendant, charge, cited, sentence_days, absurdity, attitude, created_at "
                "FROM precedents ORDER BY created_at"
            )
            records["precedents"] = list(cur.fetchall())
            cur.execute(
                "SELECT player_id, pc_scope_id, cases, convictions, total_days, absurdity_sum FROM players ORDER BY player_id"
            )
            records["players"] = list(cur.fetchall())
            cur.execute(
                "SELECT case_id, case_no, conversation_id, player_id, defendant, charge, status, turn FROM cases ORDER BY created_at"
            )
            records["cases"] = list(cur.fetchall())
            cur.execute("SELECT case_id, turn, role, LEFT(content, 80) AS content FROM turns ORDER BY id")
            records["turns"] = list(cur.fetchall())
    finally:
        conn.close()

    # 选一个具体的混合检索例子写进证据
    try:
        from app.config import settings
        from app.db import Store
        from app.embeddings import Embedder

        embedder = Embedder(settings.embedding_backend, settings.embedding_dim)
        store = Store(settings, embedder)
        rows, tag = store.search_statutes("我的猫每天凌晨三点在我脸上蹦迪，还打翻水杯")
        records["hybrid_search_example"] = {
            "query": "我的猫每天凌晨三点在我脸上蹦迪，还打翻水杯",
            "inferred_tag": tag,
            "sql_logic": "VECTOR INDEX(vidx_statutes) 召回 + MATCH(content) AGAINST(ngram2) 召回 + WHERE tag=%s 标量过滤，RRF 融合",
            "results": [
                {
                    "code": r["code"],
                    "title": r["title"],
                    "score": r["score"],
                    "channels": r["channels"],
                    "min_days": r["min_days"],
                    "max_days": r["max_days"],
                }
                for r in rows
            ],
        }
    except Exception as exc:
        records["hybrid_search_example"] = {"error": str(exc)}

    (out / "seekdb_records.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    # PowerContext 记忆
    pc_records: dict[str, object] = {"scopes": [], "memories_by_scope": {}}
    pc_records["scopes"] = get(PC + "/v1/scopes").get("items", [])
    targets = ["p-1001", "p-2002"]
    for player in targets:
        scope_row = next((p for p in records["players"] if p["player_id"] == player), None)
        if not scope_row or not scope_row.get("pc_scope_id"):
            continue
        scope_id = scope_row["pc_scope_id"]
        hits = post(PC + "/v1/memory/search", {"scope_id": scope_id, "query": "上庭 判决 法官 评语", "limit": 10})
        pc_records["memories_by_scope"][player] = {
            "scope_id": scope_id,
            "hits": [
                {
                    "text": (h.get("memory") or {}).get("text"),
                    "kind": (h.get("memory") or {}).get("kind"),
                    "space": h.get("space"),
                    "score": h.get("score"),
                }
                for h in hits.get("hits", [])
            ],
        }
    (out / "powercontext_records.json").write_text(
        json.dumps(pc_records, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )

    print(f"[ok] evidence written to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
