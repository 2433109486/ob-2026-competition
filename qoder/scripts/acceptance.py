"""End-to-end acceptance check against a running ResearchPulse instance."""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "http://127.0.0.1:7860"
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "evidence"
OUT.mkdir(parents=True, exist_ok=True)


def request(method: str, path: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} -> {error.code}: {detail}") from error


def check(condition: bool, label: str, detail: object = "") -> dict:
    if not condition:
        raise AssertionError(f"FAIL {label}: {detail}")
    print(f"[OK] {label}: {detail}")
    return {"label": label, "detail": detail, "ok": True}


def main() -> int:
    result: dict = {"started_at": datetime.now(timezone.utc).isoformat(), "checks": []}

    health = request("GET", "/api/health")
    result["checks"].append(check(health["seekdb"]["ok"], "seekdb 可连接", health["seekdb"]["version"]))
    result["checks"].append(check(health["powercontext"]["ok"], "PowerContext 可连接", health["powercontext"]["url"]))

    boot = request("GET", "/api/bootstrap")
    result["checks"].append(check(boot["counts"]["papers"] >= 10, "资料库已初始化", f"{boot['counts']['papers']} 篇"))
    result["checks"].append(check(boot["memory_available"], "研究记忆可用", f"{boot['memory_count']} 条"))
    result["checks"].append(check(boot["profile"].get("name") == "林然", "研究画像已读取", boot["profile"].get("goal", "")))

    query = "AI 编程助手对初学者学习迁移的影响"
    search = request("POST", "/api/search", {"query": query, "limit": 8})
    result["search"] = {
        "query": query,
        "total": search["total"],
        "latency_ms": search["latency_ms"],
        "top": [{"paper_id": item["paper"]["paper_id"], "score": item["score"]} for item in search["results"][:4]],
        "candidates": search["counts"],
        "memory": search["memory"]["summary"],
    }
    result["checks"].append(check(search["total"] >= 4, "混合检索返回结果", f"{search['total']} 篇 / {search['latency_ms']} ms"))
    result["checks"].append(check(len(search["trace"]) >= 2, "执行向量与全文两条 SQL", [item["label"] for item in search["trace"]]))
    result["checks"].append(check(search["counts"]["vector_candidates"] > 0, "seekdb 向量召回", f"{search['counts']['vector_candidates']} 个片段"))
    result["checks"].append(check(search["counts"]["text_candidates"] > 0, "seekdb 全文召回", f"{search['counts']['text_candidates']} 个片段"))
    result["checks"].append(check(search["memory"]["available"], "记忆参与本次检索排序", search["memory"]["focus_tags"]))

    paper_id = search["results"][0]["paper"]["paper_id"]
    paper = request("GET", f"/api/papers/{paper_id}")
    result["checks"].append(check(len(paper["chunks"]) >= 2, "可打开原文证据片段", f"{paper['title']} / {len(paper['chunks'])} 段"))

    review = request(
        "POST",
        "/api/review/matrix",
        {
            "paper_ids": ["kazemitabaar2023", "bastani2025", "prather2023", "denny2024"],
            "question": "生成式 AI 编程助手如何影响初学者的编程学习与迁移？",
            "remember": True,
            "note": "acceptance.py 自动验收",
        },
    )
    matrix = review["matrix"]
    draft = review["draft"]
    result["matrix"] = {
        "rows": matrix["paper_count"],
        "columns": len(matrix["columns"]),
        "coverage": matrix["coverage"],
        "citations": len(draft["citations"]),
        "memory_saved": bool(review.get("memory", {}).get("saved")),
    }
    result["checks"].append(check(matrix["paper_count"] == 4, "综述矩阵包含 4 篇文献", matrix["question"]))
    result["checks"].append(check(len(matrix["columns"]) == 6, "矩阵包含 6 个维度", [c["label"] for c in matrix["columns"]]))
    result["checks"].append(check(matrix["coverage"] >= 80, "结构化字段覆盖度", f"{matrix['coverage']}%"))
    result["checks"].append(check(len(draft["citations"]) == 4, "草稿带 4 条引用", draft["citations"][0]["cite"][:50]))
    result["checks"].append(check(review["memory"]["saved"], "综述决策写入 PowerContext", review["memory"].get("artifact_id")))

    note_text = "验收记录：主终点坚持用延迟迁移，不用课堂练习成绩替代。"
    note = request("POST", "/api/memory/note", {"text": note_text, "kind": "research_note"})
    result["checks"].append(check(note["saved"]["saved"], "研究判断写入 PowerContext", note["saved"].get("artifact_id")))

    memory = request("GET", "/api/memory")
    kinds = [item["kind"] for item in memory["timeline"]]
    result["checks"].append(check("review_board" in kinds, "记忆时间线包含综述决策", kinds[:5]))
    result["checks"].append(check("research_note" in kinds, "记忆时间线包含研究判断", f"{len(memory['timeline'])} 条"))

    recall = request("GET", "/api/memory/search?q=" + urllib.parse.quote("主终点 延迟迁移"))
    result["recall"] = recall
    result["checks"].append(check(len(recall.get("items", [])) > 0, "PowerContext 可召回刚写入的记忆", recall.get("items", [{}])[0].get("kind")))

    calls = (ROOT / "runtime" / "powercontext_calls.jsonl").read_text(encoding="utf-8").strip().splitlines()
    result["checks"].append(check(len(calls) > 0, "保留 PowerContext 调用证据", f"{len(calls)} 条"))

    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    result["status"] = "pass"
    (OUT / "acceptance.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nPASS: {len(result['checks'])} checks -> {OUT / 'acceptance.json'}")
    return 0


if __name__ == "__main__":
    import urllib.parse

    raise SystemExit(main())
