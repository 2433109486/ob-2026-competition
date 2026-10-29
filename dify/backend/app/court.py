"""庭审核心逻辑：立案 → 质证 → 判决。

设计原则：**模型负责叙事，后端负责事实**。
- 法条只能来自 seekdb 检索结果；
- 刑期由后端按“法定区间 × 离谱指数 × 态度 × 累犯”计算并落库；
- 法官的跨会话记忆由 PowerContext 保存与召回。
"""

from __future__ import annotations

import re
from typing import Any

from .config import Settings
from .db import Store
from .powercontext import PowerContextClient
from .statutes import STATUTE_BY_CODE

VERDICT_PATTERN = re.compile(r"判决|宣判|判吧|判了|结案|别废话|快点判|可以判|直接判")
ATTITUDE_FACTOR = {"认罪": 0.8, "卖惨": 0.9, "沉默": 1.0, "狡辩": 1.2}


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def compute_sentence(
    *,
    min_days: int,
    max_days: int,
    absurdity: int,
    attitude: str,
    prior_convictions: int,
) -> tuple[int, int]:
    """返回 (刑期, 累犯上限)。累犯每次最多把上限抬高 3 天。"""

    upper = max_days + 3 * min(prior_convictions, 4)
    base = (min_days + max_days) / 2
    factor = 0.6 + _clamp(absurdity, 0, 100) / 100
    raw = base * factor * ATTITUDE_FACTOR.get(attitude, 1.0)
    return _clamp(round(raw), min_days, upper), upper


def _pick_statutes(store: Store, cited_codes: list[str], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只接受真实存在的法条；模型编造的编号会被丢弃。"""

    picked = []
    seen = set()
    for code in cited_codes:
        statute = STATUTE_BY_CODE.get(str(code).strip().upper())
        if statute and statute.code not in seen:
            seen.add(statute.code)
            picked.append(
                {
                    "code": statute.code,
                    "title": statute.title,
                    "text": statute.text,
                    "min_days": statute.min_days,
                    "max_days": statute.max_days,
                    "fine": statute.fine,
                    "tag": statute.tag,
                }
            )
    if not picked:
        for item in fallback[:2]:
            picked.append(
                {
                    "code": item["code"],
                    "title": item["title"],
                    "text": item["text"],
                    "min_days": item["min_days"],
                    "max_days": item["max_days"],
                    "fine": item["fine"],
                    "tag": item["tag"],
                }
            )
    return picked


def intake(
    store: Store,
    pc: PowerContextClient,
    settings: Settings,
    *,
    player_id: str,
    conversation_id: str,
    message: str,
) -> dict[str, Any]:
    player = store.get_or_create_player(player_id)
    scope_id = pc.ensure_scope(player_id, player)
    case = store.get_or_create_case(player_id, conversation_id)
    turn = int(case["turn"]) + 1

    # 检索不能只看本轮这句话：第三轮往往只有“请判决”四个字。
    # 把被告、案由与前几轮原告陈述拼成检索上下文，避免召回跑到别的案子。
    history = store.transcript(case["case_id"])
    plaintiff_lines = [t["content"] for t in history if t["role"] == "plaintiff"][-3:]
    context = " ".join(
        part for part in [case.get("defendant") or "", case.get("charge") or "", *plaintiff_lines, message] if part
    )
    statutes, tag = store.search_statutes(context)
    precedents = store.search_precedents(context)
    memories = pc.recall(scope_id, "上庭 判决 法官 评语 " + context)
    if not memories:
        # PowerContext 的文本召回是 AND 语义：带上具体案由可能一条都命中不了。
        # 退回到只按“庭审记录”召回，保证跨会话连续性。
        memories = pc.recall(scope_id, "上庭 判决 法官 评语")
    force = turn >= settings.max_turns or bool(VERDICT_PATTERN.search(message))
    phase = "verdict" if force else ("intake" if turn == 1 else "hearing")

    store.update_case(case["case_id"], turn=turn)
    store.add_turn(case["case_id"], turn, "plaintiff", message)
    profile = store.profile(player_id)

    history_text = "\n".join(
        f"{'原告' if t['role'] == 'plaintiff' else '法官'}：{t['content'][:120]}" for t in history[-6:]
    )

    return {
        "ok": True,
        "case_id": case["case_id"],
        "case_no": case["case_no"],
        "turn": turn,
        "phase": phase,
        "max_turns": settings.max_turns,
        "player": profile,
        "tag": tag,
        "defendant": case.get("defendant") or "",
        "charge": case.get("charge") or "",
        "history": history_text,
        "statutes": statutes,
        "precedents": precedents,
        "memories": memories,
        "powercontext": {
            "status": "ok" if memories or scope_id else ("empty" if scope_id else "degraded"),
            "scope_id": scope_id,
            "recalled": len(memories),
        },
    }


def commit(
    store: Store,
    pc: PowerContextClient,
    settings: Settings,
    *,
    player_id: str,
    conversation_id: str,
    case_id: str,
    message: str,
    judge: dict[str, Any],
    fallback_statutes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    with store.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM cases WHERE case_id = %s", (case_id,))
            case = cur.fetchone()
    if not case:
        raise ValueError(f"unknown case_id: {case_id}")

    turn = int(case["turn"])
    judge = judge if isinstance(judge, dict) else {}
    reply = str(judge.get("reply") or "（法官敲了敲法槌，示意原告继续。）").strip()
    defendant = str(judge.get("defendant") or case.get("defendant") or "身份不明的被告").strip()[:60]
    charge = str(judge.get("charge") or case.get("charge") or "离谱纠纷").strip()[:60]
    attitude = str(judge.get("attitude") or "沉默")
    if attitude not in ATTITUDE_FACTOR:
        attitude = "沉默"
    absurdity = _clamp(int(judge.get("absurdity") or 50), 0, 100)

    forced = turn >= settings.max_turns or bool(VERDICT_PATTERN.search(message))
    wants_verdict = str(judge.get("phase") or "") == "verdict" and isinstance(judge.get("verdict"), dict)
    phase = "verdict" if (wants_verdict or forced) else ("intake" if turn == 1 else "hearing")

    store.update_case(case_id, defendant=defendant, charge=charge)
    store.add_turn(case_id, turn, "judge", reply)

    scope_id = None
    with store.connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT pc_scope_id FROM players WHERE player_id = %s", (player_id,))
            row = cur.fetchone()
            scope_id = row.get("pc_scope_id") if row else None

    memory_callback = judge.get("memory_callback")
    if not isinstance(memory_callback, str):
        memory_callback = None
    # 记忆回响必须真的有记忆支撑；否则模型会把“相似判例”说成“本官记得你”。
    if memory_callback and scope_id:
        if not (pc.recall(scope_id, "上庭 判决 法官 评语 " + message, 1) or pc.recall(scope_id, "上庭 判决 法官 评语", 1)):
            memory_callback = None
    next_prompt = str(judge.get("next_prompt") or "原告可以继续陈述，或说「请判决」。")

    result: dict[str, Any] = {
        "ok": True,
        "case_id": case_id,
        "case_no": case["case_no"],
        "turn": turn,
        "phase": phase,
        "reply": reply,
        "defendant": defendant,
        "charge": charge,
        "memory_callback": memory_callback,
        "next_prompt": next_prompt,
        "statutes": [],
        "verdict": None,
        "memory_saved": None,
        "precedent_id": None,
    }

    cited_codes = judge.get("cited_codes") if isinstance(judge.get("cited_codes"), list) else []
    picked = _pick_statutes(store, [str(c) for c in cited_codes], fallback_statutes or [])
    result["statutes"] = picked

    if phase == "verdict":
        proposal = judge.get("verdict") or {}
        primary = picked[0] if picked else None
        if primary is None:
            raise ValueError("no statute available for verdict")
        profile = store.profile(player_id)
        prior = int(profile.get("convictions") or 0)
        sentence, upper = compute_sentence(
            min_days=int(primary["min_days"]),
            max_days=int(primary["max_days"]),
            absurdity=absurdity,
            attitude=attitude,
            prior_convictions=prior,
        )
        proposed = proposal.get("sentence_days")
        try:
            proposed_int = int(proposed)
        except (TypeError, ValueError):
            proposed_int = sentence
        # 模型只能给建议值：夹在法定区间（含累犯上限）内，避免“判 999 天”
        sentence = _clamp(proposed_int, int(primary["min_days"]), upper)

        compensation = str(proposal.get("compensation") or primary["fine"])[:80]
        probation = str(proposal.get("probation") or "缓刑 7 天，期间不得再次实施同类行为")[:80]
        reasoning = str(proposal.get("reasoning") or reply)[:300]

        summary = (
            f"原告 {player_id} 起诉「{defendant}」，案由{charge}，"
            f"引 {','.join(s['code'] for s in picked)}，判 {sentence} 天，赔偿：{compensation}。"
        )
        precedent_id = store.record_verdict(
            case_id=case_id,
            case_no=case["case_no"],
            player_id=player_id,
            defendant=defendant,
            charge=charge,
            summary=summary,
            cited=[s["code"] for s in picked],
            sentence_days=sentence,
            absurdity=absurdity,
            attitude=attitude,
        )
        store.update_case(case_id, status="verdict")

        result["verdict"] = {
            "defendant": defendant,
            "charge": charge,
            "sentence_days": sentence,
            "upper_bound": upper,
            "min_days": int(primary["min_days"]),
            "max_days": int(primary["max_days"]),
            "compensation": compensation,
            "probation": probation,
            "reasoning": reasoning,
            "absurdity": absurdity,
            "attitude": attitude,
            "recidivism": prior,
            "cited": picked,
        }
        result["precedent_id"] = precedent_id

        convictions = prior + 1
        memory_text = (
            f"第{convictions}次上庭：原告起诉「{defendant}」——{charge}，"
            f"援引 {'/'.join(s['code'] for s in picked)}，判 {sentence} 天，赔偿「{compensation}」。"
            f"法官评语：{reasoning[:60]}"
        )
        saved = pc.remember(scope_id, memory_text, kind="state")
        result["memory_saved"] = (
            {"artifact_id": (saved or {}).get("artifact", {}).get("artifact_id"), "text": memory_text}
            if saved
            else None
        )
        transcript = (
            f"【{case['case_no']}】原告：{message}\n法官：{reply}\n"
            f"判决：{sentence} 天；赔偿：{compensation}；理由：{reasoning}"
        )
        pc.capture(
            scope_id,
            source_id=f"{case_id}-verdict",
            content=transcript,
            metadata={"case_no": case["case_no"], "player_id": player_id, "turn": turn},
        )
    else:
        pc.capture(
            scope_id,
            source_id=f"{case_id}-turn-{turn}",
            content=f"【{case['case_no']}】原告：{message}\n法官：{reply}",
            metadata={"case_no": case["case_no"], "player_id": player_id, "turn": turn},
        )

    result["player"] = store.profile(player_id)
    result["powercontext"] = {
        "status": "ok" if scope_id else "degraded",
        "scope_id": scope_id,
        "memory_saved": bool(result["memory_saved"]),
    }
    return result
