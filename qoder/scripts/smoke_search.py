from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.retrieval import search  # noqa: E402

queries = [
    "AI 编程助手 对初学者 学习迁移 的影响",
    "怎么避免学生直接抄答案",
    "主动学习 认知参与 框架",
    "非英语母语 编程学习 障碍",
    "开发效率 Copilot",
]
for query in queries:
    result = search(query, limit=4)
    print("\n##", query, "|", result["latency_ms"], "ms")
    for item in result["results"]:
        print(f"  {item['score']:.3f} {item['paper']['paper_id']:<20} {item['paper']['title']}")
        print("        ", item["reasons"])
        print("        ", item["best_chunk"]["snippet"][:100])
    print("  candidates", result["counts"], "memory", result["memory"]["summary"])
