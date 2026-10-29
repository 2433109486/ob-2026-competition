"""本地回放：按 Dify Chatflow 的节点顺序调用后端与模型，产出可提交的运行证据。

流程与 DSL 完全一致：
    intake HTTP  →  组装提示词  →  LLM  →  解析 JSON  →  commit HTTP  →  渲染

用法（在 repository 的 dify/ 目录下）：
    python scripts/run_demo.py --reset
    python scripts/run_demo.py --out evidence

模型默认走 MiniMax 的 OpenAI 兼容接口；也可用 --provider openai 指向任意兼容服务。
API Key 只从环境变量读取，不写入任何文件。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.prompt import build_messages  # noqa: E402
from app.render import render_answer  # noqa: E402

API_BASE = os.environ.get("COURT_API_BASE", "http://127.0.0.1:8088")

SCENARIOS = [
    {
        "id": "A",
        "title": "第一案：起诉一只凌晨蹦迪的猫",
        "player_id": "p-1001",
        "conversation_id": "demo-conv-a",
        "messages": [
            "我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻我的水杯。",
            "证据？它踩我脸的时候留下了脚印，而且水杯现在还在滴水。",
            "请判决。",
        ],
    },
    {
        "id": "B",
        "title": "第二案：同一玩家，新会话，起诉周一",
        "player_id": "p-1001",
        "conversation_id": "demo-conv-b",
        "messages": [
            "又是我。这次我要告周一，它每周都恶意到访，还带来早高峰。",
            "证据是今早我的闹钟响了五次，我仍然迟到了。",
            "直接判吧。",
        ],
    },
    {
        "id": "C",
        "title": "对照组：全新玩家，与第一案相同的猫",
        "player_id": "p-2002",
        "conversation_id": "demo-conv-c",
        "messages": [
            "我要起诉我的猫。它每天凌晨三点在我脸上蹦迪，还打翻我的水杯。",
            "证据？它踩我脸的时候留下了脚印，而且水杯现在还在滴水。",
            "请判决。",
        ],
    },
]


def http_json(method: str, url: str, payload: dict | None = None, timeout: int = 60) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{exc.code} {url} -> {detail}") from exc


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start : end + 1])
    raise ValueError(f"模型未返回 JSON：{text[:200]}")


class LLM:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        if provider == "minimax":
            self.url = os.environ.get("LLM_BASE_URL", "https://api.minimax.chat/v1/text/chatcompletion_v2")
            self.model = os.environ.get("LLM_MODEL", "MiniMax-Text-01")
        else:
            self.url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1/chat/completions")
            self.model = os.environ.get("LLM_MODEL", "gpt-4o-mini")
        self.key = os.environ.get("LLM_API_KEY", "")
        if not self.key:
            raise SystemExit("请先设置 LLM_API_KEY（或 --api-key-file 指向密钥文件）")

    def chat(self, messages: list[dict[str, str]]) -> tuple[str, dict]:
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.9,
            "max_tokens": 1200,
        }
        request = urllib.request.Request(
            self.url,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        return content, data.get("usage") or {}


def run_turn(llm: LLM, scenario: dict, index: int, message: str, evidence: dict) -> dict:
    intake = http_json(
        "POST",
        API_BASE + "/api/v1/court/intake",
        {
            "player_id": scenario["player_id"],
            "conversation_id": scenario["conversation_id"],
            "message": message,
        },
    )
    prompt_messages = build_messages(
        player_id=scenario["player_id"],
        case_no=intake["case_no"],
        turn=intake["turn"],
        phase=intake["phase"],
        query=message,
        profile=intake["player"],
        statutes=intake["statutes"],
        memories=intake["memories"],
        precedents=intake["precedents"],
        history=intake.get("history", ""),
        defendant=intake.get("defendant", ""),
        charge=intake.get("charge", ""),
    )

    last_error: Exception | None = None
    raw = ""
    judge: dict = {}
    usage: dict = {}
    for attempt in range(3):
        try:
            raw, usage = llm.chat(prompt_messages)
            judge = extract_json(raw)
            if "reply" not in judge:
                raise ValueError("judge JSON missing reply")
            break
        except Exception as exc:  # 模型偶发不按格式输出，重试
            last_error = exc
            time.sleep(1.5)
    else:
        raise SystemExit(f"LLM 调用失败：{last_error}")

    commit = http_json(
        "POST",
        API_BASE + "/api/v1/court/commit",
        {
            "player_id": scenario["player_id"],
            "conversation_id": scenario["conversation_id"],
            "case_id": intake["case_id"],
            "message": message,
            "judge": judge,
            "fallback_statutes": intake["statutes"],
        },
    )
    answer = commit.get("answer_md") or render_answer(commit)

    turn_record = {
        "turn": intake["turn"],
        "phase_intake": intake["phase"],
        "phase_final": commit["phase"],
        "message": message,
        "statutes_recalled": [
            {"code": s["code"], "title": s["title"], "score": s["score"], "channels": s["channels"]}
            for s in intake["statutes"]
        ],
        "memories_recalled": intake["memories"],
        "precedents_recalled": [
            {"case_no": p["case_no"], "defendant": p["defendant"], "sentence_days": p["sentence_days"]}
            for p in intake["precedents"]
        ],
        "powercontext_intake": intake["powercontext"],
        "llm_raw": raw,
        "judge": judge,
        "commit": commit,
        "answer": answer,
        "usage": usage,
    }
    evidence["turns"].append(turn_record)
    return commit


def render_markdown(evidence: dict) -> str:
    lines = [
        "# 《宇宙离谱法庭》验证样例 · 实际运行记录",
        "",
        f"- 运行时间：{evidence['generated_at']}",
        f"- 后端：`{evidence['api_base']}`",
        f"- 模型：`{evidence['model']}`",
        f"- 说明：本记录由 `scripts/run_demo.py` 按 Dify Chatflow 的节点顺序真实调用后端与模型生成；"
        "每轮的 intake / commit 均对应 DSL 中的 HTTP 节点。",
        "",
    ]
    for scenario in evidence["scenarios"]:
        lines.append(f"## 场景 {scenario['id']}：{scenario['title']}")
        lines.append("")
        lines.append(f"- 玩家：`{scenario['player_id']}`　会话：`{scenario['conversation_id']}`")
        lines.append("")
        for turn in scenario["turns"]:
            lines.append(f"### 第 {turn['turn']} 轮")
            lines.append("")
            lines.append(f"**原告**：{turn['message']}")
            lines.append("")
            lines.append(turn["answer"])
            cited = "、".join(f"`{s['code']}`" for s in turn["statutes_recalled"])
            channels = "、".join(turn["statutes_recalled"][0]["channels"]) if turn["statutes_recalled"] else "-"
            lines.append("")
            lines.append(
                f"<sub>seekdb 召回：{cited}（通道：{channels}）　"
                f"PowerContext 召回：{len(turn['memories_recalled'])} 条　"
                f"阶段：{turn['phase_intake']} → {turn['phase_final']}</sub>"
            )
            lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 数据落库核对")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(evidence["db_snapshot"], ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")
    lines.append("## PowerContext 记忆核对")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(evidence["powercontext_snapshot"], ensure_ascii=False, indent=2))
    lines.append("```")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "evidence"))
    parser.add_argument("--provider", default=os.environ.get("LLM_PROVIDER", "minimax"))
    parser.add_argument("--api-key-file", default="")
    parser.add_argument("--reset", action="store_true", help="重置 seekdb（清空判例与档案）")
    parser.add_argument("--scenario", default="", help="只跑某个场景 id（A/B/C）")
    args = parser.parse_args()

    if args.api_key_file:
        os.environ["LLM_API_KEY"] = Path(args.api_key_file).read_text(encoding="utf-8").strip()

    if args.reset:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.cli import main as cli_main

        cli_main(["init", "--recreate"])

    llm = LLM(args.provider)
    evidence: dict = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_base": API_BASE,
        "provider": args.provider,
        "model": llm.model,
        "scenarios": [],
        "db_snapshot": {},
        "powercontext_snapshot": {},
    }

    for scenario in SCENARIOS:
        if args.scenario and scenario["id"] != args.scenario:
            continue
        item = {
            "id": scenario["id"],
            "title": scenario["title"],
            "player_id": scenario["player_id"],
            "conversation_id": scenario["conversation_id"],
            "turns": [],
        }
        print(f"[scenario {scenario['id']}] {scenario['title']}")
        for index, message in enumerate(scenario["messages"], start=1):
            commit = run_turn(llm, scenario, index, message, item)
            print(f"  turn {index}: phase={commit['phase']} case={commit['case_no']}")
        evidence["scenarios"].append(item)

    # 抓取落库结果，作为可核对的证据
    evidence["db_snapshot"] = http_json("GET", API_BASE + "/api/v1/court/stats")
    for pid in ("p-1001", "p-2002"):
        evidence.setdefault("dossiers", {})[pid] = http_json("GET", API_BASE + f"/api/v1/court/dossier/{pid}")
    try:
        evidence["powercontext_snapshot"] = http_json("GET", "http://127.0.0.1:8000/v1/scopes")
    except Exception as exc:
        evidence["powercontext_snapshot"] = {"error": str(exc)}

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "demo_run.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "transcript.md").write_text(render_markdown(evidence), encoding="utf-8")
    print(f"[ok] {out_dir / 'demo_run.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
