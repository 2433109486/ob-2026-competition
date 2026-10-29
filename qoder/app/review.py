"""Deterministic review-matrix and review-draft assembly.

This is deliberately extractive: every sentence is grounded in a structured
field that the researcher can edit. It gives a traceable first draft rather than
inventing claims that are not in the library.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

COLUMNS: List[Tuple[str, str]] = [
    ("problem", "研究问题"),
    ("method", "研究设计"),
    ("sample", "样本 / 情境"),
    ("finding", "主要发现"),
    ("limitation", "局限"),
    ("reuse", "可复用点"),
]

_FIELD_MAP = {
    "problem": "review_problem",
    "method": "review_method",
    "sample": "review_sample",
    "finding": "review_finding",
    "limitation": "review_limitation",
    "reuse": "review_reuse",
}


def _value(paper: Dict[str, Any], key: str) -> str:
    return str(paper.get(_FIELD_MAP[key]) or "").strip()


def _short(text: str, limit: int = 110) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _is_empirical(paper: Dict[str, Any]) -> bool:
    method = str(paper.get("review_method", ""))
    # "非原始实证研究" and "专家研讨/文献综合" are evidence reviews, not new data.
    if any(token in method for token in ["非原始", "非实证", "工作组报告", "观点与分析", "理论综合", "文献综合", "叙述性综述"]):
        return False
    return any(token in method for token in ["随机", "对照实验", "问卷", "访谈", "调查", "实验", "混合方法", "元分析"])


def build_matrix(papers: List[Dict[str, Any]], question: str) -> Dict[str, Any]:
    rows = []
    for index, paper in enumerate(papers, start=1):
        cells = {key: _value(paper, key) for key, _ in COLUMNS}
        missing = [key for key, value in cells.items() if len(value) < 6]
        rows.append(
            {
                "index": index,
                "paper_id": paper["paper_id"],
                "title": paper["title"],
                "authors": paper.get("authors", ""),
                "year": paper.get("year"),
                "venue": paper.get("venue", ""),
                "doi": paper.get("doi", ""),
                "status": paper.get("status", "to_read"),
                "source_type": paper.get("source_type", "paper"),
                "cells": cells,
                "missing": missing,
            }
        )
    gaps = []
    for key, label in COLUMNS:
        filled = sum(1 for row in rows if len(row["cells"].get(key, "")) >= 6)
        if filled < len(rows):
            gaps.append(
                {
                    "column": key,
                    "label": label,
                    "filled": filled,
                    "total": len(rows),
                    "missing_titles": [row["title"] for row in rows if len(row["cells"].get(key, "")) < 6],
                }
            )
    coverage = round(
        100
        * sum(1 for row in rows for key, _ in COLUMNS if len(row["cells"].get(key, "")) >= 6)
        / max(1, len(rows) * len(COLUMNS))
    )
    return {
        "question": question,
        "columns": [{"key": key, "label": label} for key, label in COLUMNS],
        "rows": rows,
        "gaps": gaps,
        "coverage": coverage,
        "paper_count": len(rows),
        "empirical_count": sum(1 for paper in papers if _is_empirical(paper)),
    }


def build_draft(papers: List[Dict[str, Any]], question: str, profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    profile = profile or {}
    citations = []
    by_id: Dict[str, int] = {}
    for index, paper in enumerate(papers, start=1):
        by_id[paper["paper_id"]] = index
        citations.append(
            {
                "index": index,
                "paper_id": paper["paper_id"],
                "cite": paper.get("cite_text") or f"{paper.get('authors', '')} ({paper.get('year', '')}). {paper.get('title', '')}.",
                "doi": paper.get("doi", ""),
                "url": paper.get("url", ""),
            }
        )

    empirical = [paper for paper in papers if _is_empirical(paper)]
    reviews = [paper for paper in papers if not _is_empirical(paper)]
    intro = (
        f"围绕「{question}」，本资料库目前纳入 {len(papers)} 份资料，其中 {len(empirical)} 份包含实证或调查数据。"
        f"以下草稿只使用资料库中已经结构化记录的研究问题、设计、发现与局限，引用编号对应文末列表；"
        f"它用于搭建综述骨架，不替代对原文的核对。"
    )

    findings = []
    for paper in papers:
        idx = by_id[paper["paper_id"]]
        authors = str(paper.get("authors", "")).split(",")[0].strip() or "该研究"
        year = paper.get("year", "")
        problem = _short(_value(paper, "problem"), 70)
        method = _short(_value(paper, "method"), 80)
        finding = _short(_value(paper, "finding"), 150)
        if finding:
            findings.append(f"{authors}（{year}）聚焦“{problem}”，采用{method}，主要发现是：{finding} [{idx}]。")

    design = []
    for paper in empirical[:6]:
        idx = by_id[paper["paper_id"]]
        design.append(
            f"[{idx}] 的证据来自{_short(_value(paper, 'method'), 70).rstrip('。；;')}；"
            f"样本/情境为{_short(_value(paper, 'sample'), 70).rstrip('。；;')}。"
        )
    if not design:
        design.append("当前选择中还没有可识别的实证研究，建议补充随机对照实验或准实验研究后再写“证据强度”一节。")
    review_note = "；".join(
        f"[{by_id[paper['paper_id']]}] {_short(_value(paper, 'method'), 54).rstrip('。；;')}" for paper in reviews
    )

    disagreements = []
    for paper in papers:
        idx = by_id[paper["paper_id"]]
        finding = _value(paper, "finding")
        if any(token in finding for token in ["下降", "不显著", "没有显著", "损害", "风险"]):
            disagreements.append(f"[{idx}] 提供了需要与“AI 提升表现”叙事对照的结果：{_short(finding, 140)}")
    if not disagreements:
        disagreements.append("当前资料尚未形成明显的相反证据；这可能意味着样本不足，而不是结论一致。")

    limitations = []
    for paper in papers:
        idx = by_id[paper["paper_id"]]
        limitation = _value(paper, "limitation")
        if limitation:
            limitations.append(f"[{idx}] {_short(limitation, 120)}")
    if not limitations:
        limitations.append("所选文献的局限字段尚未填写，矩阵覆盖度不足以支持“研究空白”判断。")

    reuse = []
    for paper in papers:
        idx = by_id[paper["paper_id"]]
        value = _value(paper, "reuse")
        if value:
            reuse.append(f"[{idx}] {_short(value, 120)}")

    question = profile.get("question") or question
    future = (
        f"对「{question}」而言，下一步最值得补的不是更多“AI 有没有用”的均值比较，"
        f"而是把 AI 使用方式、脚手架设计和延迟迁移放进同一个设计。"
        f"如果沿用当前资料库，建议优先补齐：非英语母语学习者的公平性证据、超过一学期的纵向研究，"
        f"以及能区分“直接索取答案”和“解释—验证—互动”的过程数据。"
    )

    sections = [
        {"title": "一、问题从哪里来", "body": intro},
        {
            "title": "二、已有研究怎么做",
            "body": "从所选资料看，研究设计并不处在同一证据层级。"
            + " ".join(design)
            + (f" 另外，{review_note} 属于证据综合或立场分析，不提供新的实验效应量。" if review_note else "")
            + " 因此，综述里不能把实验结论、工作组的风险清单和立场文章混成同一种证据；它们分别回答“短期是否有效”“领域应该担心什么”和“评价方式该如何改”。",
        },
        {"title": "三、主要发现与分歧", "body": " ".join(findings) + " 其中最值得在综述中展开的分歧是：练习阶段的表现提升，是否能在撤掉 AI 后转化为独立表现。 " + " ".join(disagreements)},
        {"title": "四、局限与研究空白", "body": " ".join(limitations) + f" 综合来看，当前证据在“短期、单工具、单学科”上较集中，长期迁移与公平性仍然是空白。"},
        {"title": "五、对当前研究的启示", "body": " ".join(reuse) + " " + future},
    ]
    markdown_lines = [f"# {question}", "", f"> 由研脉根据 {len(papers)} 份已选资料生成的可追溯草稿。引用编号对应文末列表。", ""]
    for section in sections:
        markdown_lines.extend([f"## {section['title']}", "", section["body"], ""])
    markdown_lines.extend(["## 参考文献", ""])
    for citation in citations:
        markdown_lines.append(f"[{citation['index']}] {citation['cite']}" + (f" DOI: {citation['doi']}" if citation["doi"] else ""))
        markdown_lines.append("")
    return {
        "question": question,
        "sections": sections,
        "citations": citations,
        "markdown": "\n".join(markdown_lines).strip(),
        "paper_count": len(papers),
        "empirical_count": len(empirical),
        "review_count": len(reviews),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
