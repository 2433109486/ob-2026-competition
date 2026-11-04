"""通过 Dify 官方应用 API 跑 A/B/C 三幕，生成提交用证据。

与 `run_demo.py` 的区别：本脚本的每一步都经过 Dify 工作流
（POST /v1/chat-messages → 11 个节点），而 `run_demo.py` 只是后端回放。

用法：
    export DIFY_BASE_URL=http://localhost
    export DIFY_APP_TOKEN=app-xxxxxxxx
    python scripts/run_dify_demo.py --out evidence/dify_run
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

SCENARIOS = [
    {
        "id": "A",
        "title": "第一案：起诉一只凌晨蹦迪的猫",
        "player_id": "p-dify-1001",
        "messages": [
            "我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻了我的水杯。",
            "证据？它踩我脸的时候留下了脚印，而且水杯现在还在滴水。",
            "请判决。",
        ],
    },
    {
        "id": "B",
        "title": "第二案：同一玩家，新会话，起诉周一",
        "player_id": "p-dify-1001",
        "messages": [
            "又是我。这次我要告周一，它每周都恶意到访，还带来早高峰。",
            "证据是今早我的闹钟响了五次，我仍然迟到了。",
            "直接判吧。",
        ],
    },
    {
        "id": "C",
        "title": "对照组：全新玩家，与第一案相同的猫",
        "player_id": "p-dify-2002",
        "messages": [
            "我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻了我的水杯。",
            "证据？它踩我脸的时候留下了脚印，而且水杯现在还在滴水。",
            "请判决。",
        ],
    },
]


def chat(base: str, token: str, payload: dict) -> dict:
    request = urllib.request.Request(
        base.rstrip("/") + "/v1/chat-messages",
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=300) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="evidence/dify_run")
    args = parser.parse_args()

    base = os.environ.get("DIFY_BASE_URL", "http://localhost")
    token = os.environ.get("DIFY_APP_TOKEN", "")
    if not token:
        raise SystemExit("请设置 DIFY_APP_TOKEN（Dify 应用 → API 访问 → API Key）")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    evidence = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "dify_base_url": base,
        "scenarios": [],
    }

    for scenario in SCENARIOS:
        conversation_id = ""
        item = {
            "id": scenario["id"],
            "title": scenario["title"],
            "player_id": scenario["player_id"],
            "turns": [],
        }
        print(f"[scenario {scenario['id']}] {scenario['title']}")
        for index, message in enumerate(scenario["messages"], start=1):
            started = time.time()
            response = chat(
                base,
                token,
                {
                    "inputs": {"player_id": scenario["player_id"]},
                    "query": message,
                    "response_mode": "blocking",
                    "conversation_id": conversation_id,
                    "user": scenario["player_id"],
                },
            )
            conversation_id = response.get("conversation_id") or conversation_id
            turn = {
                "turn": index,
                "message": message,
                "conversation_id": conversation_id,
                "message_id": response.get("message_id"),
                "answer": response.get("answer"),
                "metadata": response.get("metadata"),
                "latency_seconds": round(time.time() - started, 2),
            }
            item["turns"].append(turn)
            (out / f"{scenario['id']}-turn-{index}.json").write_text(
                json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(f"  turn {index}: {turn['latency_seconds']}s")
        evidence["scenarios"].append(item)

    (out / "dify_transcript.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    lines = [
        "# Dify 实际运行记录（service API）",
        "",
        f"- 时间：{evidence['generated_at']}",
        f"- Dify：`{base}`",
        "",
    ]
    for scenario in evidence["scenarios"]:
        lines.append(f"## 场景 {scenario['id']}：{scenario['title']}")
        lines.append("")
        lines.append(f"- 玩家：`{scenario['player_id']}`")
        for turn in scenario["turns"]:
            lines.append(f"### 第 {turn['turn']} 轮（{turn['latency_seconds']}s）")
            lines.append("")
            lines.append(f"**原告**：{turn['message']}")
            lines.append("")
            lines.append(turn["answer"] or "")
            lines.append("")
            lines.append(f"<sub>conversation: `{turn['conversation_id']}`</sub>")
            lines.append("")
    (out / "dify_transcript.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
