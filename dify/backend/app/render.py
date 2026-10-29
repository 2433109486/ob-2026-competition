"""把结构化判决渲染成聊天卡片。

`scripts/run_demo.py` 与 Dify 的 Code 节点共用同一套格式，
因此本地回放结果与 Dify 内看到的结果一致。
"""

from __future__ import annotations

from typing import Any


def render_answer(data: dict[str, Any]) -> str:
    reply = str(data.get("reply") or "").strip()
    lines: list[str] = [reply, ""]

    statutes = data.get("statutes") or []
    if statutes:
        lines.append("📜 **本庭援引**")
        for item in statutes:
            lines.append(
                f"- `{item['code']}`《{item['title']}》 · 量刑 {item['min_days']}–{item['max_days']} 天"
            )
        lines.append("")

    verdict = data.get("verdict")
    if verdict:
        tag = "（累犯加刑）" if verdict.get("recidivism") else ""
        lines.append(f"⚖️ **判决** · {data.get('case_no')}")
        lines.append(f"- 被告：{verdict['defendant']}")
        lines.append(f"- 罪名：{verdict['charge']}")
        lines.append(
            f"- 刑期：**{verdict['sentence_days']} 天**"
            f"（法定 {verdict['min_days']}–{verdict['max_days']} 天，上限 {verdict['upper_bound']} 天{tag}）"
        )
        lines.append(f"- 赔偿：{verdict['compensation']}")
        lines.append(f"- 执行：{verdict['probation']}")
        lines.append(f"- 理由：{verdict['reasoning']}")
        lines.append("")

    memory = data.get("memory_callback")
    if memory:
        lines.append(f"🧠 **记忆回响**：{memory}")
        lines.append("")

    player = data.get("player") or {}
    if player:
        lines.append(
            f"📊 **你的档案**：{player.get('title', '法庭新鲜人')} · "
            f"已起诉 {player.get('cases', 0)} 次 · 前科 {player.get('convictions', 0)} 次 · "
            f"累计刑期 {player.get('total_days', 0)} 天"
        )
        lines.append("")

    if data.get("next_prompt"):
        lines.append(f"> {data['next_prompt']}")

    return "\n".join(lines).strip()
