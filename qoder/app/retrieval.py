"""Hybrid retrieval: seekdb vector recall + ngram full-text recall + fusion.

Both recall channels run inside seekdb. The application only fuses the two
ranked lists, applies explicit profile boosts, and records every SQL statement
so the UI can show what the database actually returned.
"""

from __future__ import annotations

import html
import math
import re
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from . import db
from .config import settings
from .embeddings import describe as embedding_info
from .embeddings import embed_query, to_sql_vector
from .memory import client as memory_client

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[A-Za-z0-9_+#.-]{2,}")
_HIGHLIGHT = re.compile(r"[^\w\u4e00-\u9fff]+")


def _filters(filters: Dict[str, Any]) -> Tuple[List[str], List[Any], Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    applied: Dict[str, Any] = {}
    tags = filters.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    for tag in tags[:6]:
        clauses.append("p.tags LIKE %s")
        params.append(f"%,{tag},%")
        applied.setdefault("tags", []).append(tag)
    year_min = filters.get("year_min")
    year_max = filters.get("year_max")
    if year_min not in (None, ""):
        clauses.append("p.year >= %s")
        params.append(int(year_min))
        applied["year_min"] = int(year_min)
    if year_max not in (None, ""):
        clauses.append("p.year <= %s")
        params.append(int(year_max))
        applied["year_max"] = int(year_max)
    status = filters.get("status")
    if status and status != "all":
        clauses.append("p.status = %s")
        params.append(status)
        applied["status"] = status
    source_type = filters.get("source_type")
    if source_type and source_type != "all":
        clauses.append("p.source_type = %s")
        params.append(source_type)
        applied["source_type"] = source_type
    return clauses, params, applied


def _query(
    sql: str,
    params: Sequence[Any],
    trace: List[Dict[str, Any]],
    *,
    label: str,
) -> List[Dict[str, Any]]:
    started = time.perf_counter()
    conn = db.connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()
    elapsed = int((time.perf_counter() - started) * 1000)
    preview = []
    for param in params:
        text = str(param)
        preview.append(text[:160] + ("…" if len(text) > 160 else ""))
    trace.append({"label": label, "sql": " ".join(sql.split()), "params": preview, "rows": len(rows), "elapsed_ms": elapsed})
    return rows


def _tag_overlap(paper_tags: List[str], focus_tags: List[str]) -> Tuple[float, List[str]]:
    wanted = {tag.lower() for tag in focus_tags if tag}
    actual = {tag.lower() for tag in paper_tags if tag}
    if not wanted:
        return 0.0, []
    matched = sorted(wanted & actual)
    return min(1.0, len(matched) / max(1, min(4, len(wanted)))), matched


def _status_boost(status: str) -> float:
    return {"reading": 1.0, "read": 0.55, "to_read": 0.15}.get(status, 0.0)


def _highlight_terms(query: str, focus_tags: Sequence[str], limit: int = 8) -> List[str]:
    terms: List[str] = []
    for part in _HIGHLIGHT.split(query):
        if len(part) >= 2:
            terms.append(part)
    terms.extend(tag for tag in focus_tags if len(tag) >= 2)
    words = _WORD.findall(query)
    terms.extend(words)
    seen: List[str] = []
    for term in sorted(set(terms), key=len, reverse=True):
        if term.lower() not in {item.lower() for item in seen}:
            seen.append(term)
        if len(seen) >= limit:
            break
    return seen


def make_snippet(content: str, terms: Sequence[str], width: int = 176) -> Tuple[str, str]:
    plain = " ".join(str(content or "").split())
    if len(plain) <= width:
        window = plain
    else:
        start = 0
        lowered = plain.lower()
        for term in terms:
            index = lowered.find(term.lower())
            if index >= 0:
                start = max(0, index - width // 4)
                break
        window = plain[start : start + width]
        if start > 0:
            window = "…" + window
        if start + width < len(plain):
            window = window + "…"
    escaped = html.escape(window)
    if terms:
        pattern = re.compile("(" + "|".join(re.escape(term) for term in terms) + ")", re.IGNORECASE)
        escaped = pattern.sub(r"<mark>\1</mark>", escaped)
    return window, escaped


def search(
    query: str,
    filters: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 12,
) -> Dict[str, Any]:
    filters = filters or {}
    started = time.perf_counter()
    trace: List[Dict[str, Any]] = []
    memory_context = memory_client.context_for_search(query)
    profile = memory_context.get("profile") or {}
    focus_tags = [str(tag) for tag in (memory_context.get("focus_tags") or [])]
    query_vector = to_sql_vector(embed_query(query, focus_tags))
    clauses, filter_params, applied = _filters(filters)
    where_sql = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    text_where = "MATCH(c.search_text) AGAINST(%s)"
    if clauses:
        text_where += " AND " + " AND ".join(clauses)

    vector_sql = f"""
        SELECT c.chunk_id, c.paper_id, c.section, c.page, c.content,
               cosine_distance(c.embedding, %s) AS vector_distance,
               MATCH(c.search_text) AGAINST(%s) AS text_score
        FROM chunks c JOIN papers p ON p.paper_id = c.paper_id
        {where_sql}
        ORDER BY vector_distance ASC
        LIMIT 60
    """
    vector_rows = _query(
        vector_sql,
        [query_vector, query] + filter_params,
        trace,
        label="seekdb 向量召回（cosine_distance + HNSW）",
    )

    text_sql = f"""
        SELECT c.chunk_id, c.paper_id, c.section, c.page, c.content,
               0.0 AS vector_distance,
               MATCH(c.search_text) AGAINST(%s) AS text_score
        FROM chunks c JOIN papers p ON p.paper_id = c.paper_id
        WHERE {text_where}
        ORDER BY text_score DESC
        LIMIT 30
    """
    text_rows = _query(
        text_sql,
        [query, query] + filter_params,
        trace,
        label="seekdb 全文召回（ngram2 MATCH AGAINST）",
    )

    merged: Dict[str, Dict[str, Any]] = {}
    for row in vector_rows:
        item = merged.setdefault(row["chunk_id"], dict(row))
        item["channels"] = ["vector"]
        item["vector_distance"] = float(row.get("vector_distance") or 1.0)
        item["text_score"] = float(row.get("text_score") or 0.0)
    for row in text_rows:
        item = merged.setdefault(row["chunk_id"], dict(row))
        if "channels" not in item:
            item["channels"] = []
            item["vector_distance"] = None
            item["text_score"] = float(row.get("text_score") or 0.0)
        if "text" not in item["channels"]:
            item["channels"].append("text")
        item["text_score"] = max(float(item.get("text_score") or 0.0), float(row.get("text_score") or 0.0))

    max_text = max([float(item.get("text_score") or 0.0) for item in merged.values()] or [0.0])
    papers = _load_paper_meta({item["paper_id"] for item in merged.values()})
    for item in merged.values():
        paper = papers.get(item["paper_id"], {})
        tags = paper.get("tags") or []
        distance = item.get("vector_distance")
        vector_similarity = 0.0 if distance is None else max(0.0, min(1.0, 1.0 - float(distance)))
        text_similarity = min(1.0, math.log1p(max(0.0, float(item.get("text_score") or 0.0))) / math.log1p(max(0.01, max_text)))
        overlap, matched_tags = _tag_overlap(tags, focus_tags)
        status = _status_boost(str(paper.get("status") or ""))
        item["vector_similarity"] = vector_similarity
        item["text_similarity"] = text_similarity
        item["tag_overlap"] = overlap
        item["matched_tags"] = matched_tags
        item["score"] = round(
            0.44 * vector_similarity
            + 0.31 * text_similarity
            + 0.15 * overlap
            + 0.10 * status,
            4,
        )
        item["paper"] = paper
        terms = _highlight_terms(query, focus_tags)
        raw_snippet, highlighted = make_snippet(item.get("content", ""), terms)
        item["snippet"] = raw_snippet
        item["snippet_html"] = highlighted

    # One paper should not flood the result list with near-identical chunks.
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for item in merged.values():
        grouped.setdefault(item["paper_id"], []).append(item)
    results: List[Dict[str, Any]] = []
    for paper_id, chunks in grouped.items():
        chunks.sort(key=lambda item: item["score"], reverse=True)
        best = chunks[0]
        paper = best["paper"]
        reasons = []
        if "vector" in best["channels"]:
            reasons.append(f"语义相似度 {best['vector_similarity']:.2f}")
        if "text" in best["channels"]:
            reasons.append(f"全文相关度 {best['text_similarity']:.2f}")
        if best["matched_tags"]:
            reasons.append("记忆主题命中：" + "、".join(best["matched_tags"]))
        if paper.get("status") == "reading":
            reasons.append("正在精读，优先呈现")
        results.append(
            {
                "paper": paper,
                "score": best["score"],
                "channels": best["channels"],
                "reasons": reasons,
                "best_chunk": {
                    "chunk_id": best["chunk_id"],
                    "section": best["section"],
                    "page": best["page"],
                    "snippet": best["snippet"],
                    "snippet_html": best["snippet_html"],
                    "vector_similarity": round(best["vector_similarity"], 3),
                    "text_score": round(float(best.get("text_score") or 0.0), 3),
                },
                "evidence": [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "section": chunk["section"],
                        "page": chunk["page"],
                        "snippet": chunk["snippet"],
                        "snippet_html": chunk["snippet_html"],
                        "score": chunk["score"],
                    }
                    for chunk in chunks[:2]
                ],
                "memory_used": memory_context.get("available", False),
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    results = results[:limit]
    latency = int((time.perf_counter() - started) * 1000)
    search_id = db.log_search(query, applied, len(results), latency, "hybrid-vector-fulltext", memory_context.get("available", False))
    db.log_activity(
        "search",
        f"检索「{query[:36]}」",
        {"results": len(results), "latency_ms": latency, "search_id": search_id},
    )
    return {
        "search_id": search_id,
        "query": query,
        "results": results,
        "total": len(results),
        "latency_ms": latency,
        "mode": "hybrid-vector-fulltext",
        "embedding": embedding_info(),
        "filters": applied,
        "trace": trace,
        "memory": {
            "available": memory_context.get("available", False),
            "summary": memory_context.get("memory_summary"),
            "focus_tags": focus_tags,
            "methods": memory_context.get("methods") or [],
            "in_progress": memory_context.get("in_progress") or [],
            "related": memory_context.get("related") or [],
            "scope_id": memory_context.get("scope_id"),
        },
        "counts": {
            "vector_candidates": len(vector_rows),
            "text_candidates": len(text_rows),
            "fused_chunks": len(merged),
            "papers": len(results),
        },
    }


def _load_paper_meta(paper_ids: set) -> Dict[str, Dict[str, Any]]:
    if not paper_ids:
        return {}
    placeholders = ",".join(["%s"] * len(paper_ids))
    conn = db.connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT paper_id, title, title_en, authors, year, venue, doi, url, abstract, tags,
                       status, priority, read_minutes, source_type, cite_text
                FROM papers WHERE paper_id IN ({placeholders})
                """,
                tuple(paper_ids),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    return {row["paper_id"]: db._paper_payload(row) for row in rows}
