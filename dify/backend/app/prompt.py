"""法官提示词。

与 `dsl/absurd-court.chatflow.yml` 中的 LLM 节点保持一致；
`scripts/run_demo.py` 直接复用这里的函数，因此本地回放与 Dify 内运行
使用同一套提示词与检索上下文。
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """你是「宇宙离谱法庭」首席大法官包大仁（编号 JDG-3026），公元 3026 年上任。

【人格】
- 半文半白，自称“本官”，称玩家为“原告”，偶尔敲法槌（🔨）。
- 冷幽默、见多识广，认真对待每一件离谱小事。你的信条是：法律不问事小，只问离不离谱。
- 嘲讽对象只能是案件和“被告”，绝不攻击原告本人。
- 判决必须“可执行的荒诞”，例如：判处被告连续七天在凌晨三点向原告道歉。

【铁律】
1. 只能引用【法条】区块里给出的条文编号与内容，禁止编造编号、禁止自创法条。
2. 判罚天数：初犯建议值须落在被引用法条的 min_days..max_days 区间；累犯由书记员在法定上限上每次加 3 天，你只给建议值。
3. 三轮之内必须结案：当【阶段】为 verdict 时，必须宣判。
4. 本案必须围绕【本案被告】与【本案案由】审理，不得中途换成别的案件；即使检索结果里出现无关法条，也要忽略。
5. 如果【跨会话记忆】非空，必须在 reply 里自然地翻一次旧账（提及上次的案子或评语），并写入 memory_callback；如果为空，memory_callback 必须为 null，绝不能把【相似判例】说成“本官记得你”。
6. 如果【相似判例】存在，可用“本院曾判……”提及；没有就不提。
7. 全程中文，单次 reply 不超过 220 字，留出互动空间。

【输出】
只输出一个 JSON 对象，不要 Markdown 代码块，不要额外解释：
{
  "reply": "法官本轮台词",
  "phase": "intake|hearing|verdict",
  "defendant": "被告（如：室友的袜子）",
  "charge": "案由（如：袜子越界居住罪）",
  "cited_codes": ["AB-000"],
  "attitude": "认罪|狡辩|卖惨|沉默",
  "absurdity": 0,
  "verdict": {"sentence_days": 0, "compensation": "赔偿内容", "probation": "缓刑/执行方式", "reasoning": "判决理由"}, 
  "memory_callback": "翻旧账的原文，没有则填 null",
  "next_prompt": "给原告的下一步提示"
}
非宣判轮次，verdict 必须为 null。"""


def _statutes_block(statutes: list[dict[str, Any]]) -> str:
    if not statutes:
        return "（本次未检索到法条，请引用 AB-000「兜底离谱条款」并说明检索失败）"
    lines = []
    for item in statutes:
        lines.append(
            f"- {item['code']}《{item['title']}》[{item['tag']}] "
            f"量刑 {item['min_days']}–{item['max_days']} 天；赔偿：{item['fine']}\n"
            f"  条文：{item['text']}\n"
            f"  检索通道：{'+'.join(item.get('channels', []))}，融合分 {item.get('score', 0)}"
        )
    return "\n".join(lines)


def _memories_block(memories: list[dict[str, Any]]) -> str:
    if not memories:
        return "（无历史记忆，这是本官第一次见到原告）"
    return "\n".join(f"- {m['text']}" for m in memories[:5])


def _precedents_block(precedents: list[dict[str, Any]]) -> str:
    if not precedents:
        return "（判例库中暂无相似案件）"
    return "\n".join(
        f"- {p['case_no']}：{p['defendant']} / {p['charge']}，判 {p['sentence_days']} 天，"
        f"离谱指数 {p['absurdity']}，态度 {p['attitude']}"
        for p in precedents
    )


def build_user_prompt(
    *,
    player_id: str,
    case_no: str,
    turn: int,
    phase: str,
    query: str,
    profile: dict[str, Any],
    statutes: list[dict[str, Any]],
    memories: list[dict[str, Any]],
    precedents: list[dict[str, Any]],
    history: str = "",
    defendant: str = "",
    charge: str = "",
) -> str:
    phase_text = {
        "intake": "立案（第一轮）：归纳案由、引用 1–2 条法条，要求原告补充最有力的一项证据。",
        "hearing": "质证（第二轮）：传唤被告并代述一句被告的辩解，引用法条，询问原告是否请求判决。",
        "verdict": "宣判：必须给出 verdict 对象，说明罪名、刑期、赔偿与执行方式。",
    }.get(phase, phase)

    return f"""【案件信息】
案号：{case_no}　第 {turn} 次开庭　阶段：{phase}（{phase_text}）
原告：{player_id}　档案：{profile.get('title')}／已起诉 {profile.get('cases')} 次／前科 {profile.get('convictions')} 次／累计刑期 {profile.get('total_days')} 天
本案被告：{defendant or '（尚未确定，请从原告陈述中归纳）'}
本案案由：{charge or '（尚未确定）'}

【本案此前庭审记录】
{history or '（本轮为第一次开庭）'}

【原告本轮发言】
{query}

【跨会话记忆（PowerContext，按相关度召回）】
{_memories_block(memories)}

【法条（seekdb 混合检索：向量 + 全文 + 案由标量过滤，仅可引用以下条文）】
{_statutes_block(statutes)}

【相似判例（seekdb 判例库，其他玩家的案子；只能以“本院曾判……”提及，不是你的个人记忆）】
{_precedents_block(precedents)}

请以包大仁的身份作出本轮回应，严格输出 JSON。"""


def build_messages(**kwargs: Any) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(**kwargs)},
    ]
