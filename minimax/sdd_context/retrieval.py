"""Hybrid retrieval over the seekdb corpus.

seekdb performs both the cosine-vector ranking and the ngram full-text scoring
in one SQL statement. The module adds small, explicit boosts for task tags and
for a spec's ``applies_to`` symbols so the selected context is explainable.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import Settings
from .db import QueryTrace, vector_literal
from .ingest import parse_frontmatter

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "for",
    "with",
    "in",
    "on",
    "is",
    "are",
    "be",
    "as",
    "by",
    "this",
    "that",
    "we",
    "must",
    "should",
    "的",
    "了",
    "与",
    "和",
    "在",
    "是",
    "为",
    "及",
    "并",
    "要",
    "把",
}


@dataclass(slots=True)
class Task:
    task_id: str
    title: str
    keywords: list[str]
    target_symbols: list[str]
    body: str
    source_path: str

    @property
    def query_text(self) -> str:
        return "\n".join([self.title, " ".join(self.keywords), " ".join(self.target_symbols), self.body])


@dataclass(slots=True)
class RetrievedDoc:
    doc_key: str
    doc_type: str
    source_path: str
    title: str
    version: int
    status: str
    tags: list[str]
    metadata: dict[str, Any]
    content: str
    score: float
    reasons: list[str] = field(default_factory=list)
    vector_distance: float = 1.0
    text_score: float = 0.0

    def to_dict(self, *, include_content: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "doc_key": self.doc_key,
            "type": self.doc_type,
            "path": self.source_path,
            "title": self.title,
            "version": self.version,
            "tags": self.tags,
            "score": round(self.score, 4),
            "reasons": self.reasons,
            "source": "seekdb:sdd_context.documents",
            "metadata": self.metadata,
        }
        if include_content:
            payload["content"] = self.content
        return payload


def tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = [word for word in _WORD.findall(lowered) if word not in _STOPWORDS and len(word) > 1]
    chars = _CJK.findall(lowered)
    words.extend(char for char in chars if char not in _STOPWORDS)
    words.extend(a + b for a, b in zip(chars, chars[1:]))
    return words


def load_task(path: Path, *, project_root: Path) -> Task:
    text = path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    keywords = meta.get("keywords") or []
    target_symbols = meta.get("target_symbols") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    if isinstance(target_symbols, str):
        target_symbols = [target_symbols]
    return Task(
        task_id=str(meta.get("task_id") or path.stem),
        title=str(meta.get("title") or path.stem),
        keywords=[str(item) for item in keywords],
        target_symbols=[str(item) for item in target_symbols],
        body=body.strip(),
        source_path=path.resolve().relative_to(project_root.resolve()).as_posix(),
    )


def _query_rows(
    conn,
    trace: QueryTrace,
    sql: str,
    params: Sequence[Any],
) -> list[dict[str, Any]]:
    started = time.perf_counter()
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        columns = [description[0] for description in cur.description]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    trace.add(sql, params, len(rows), elapsed_ms)
    return rows


def _row_to_doc(row: dict[str, Any], *, score: float, reasons: list[str]) -> RetrievedDoc:
    metadata = json.loads(row.get("metadata_json") or "{}")
    tags = [tag for tag in str(row.get("tags") or "").split(",") if tag]
    return RetrievedDoc(
        doc_key=str(row["doc_key"]),
        doc_type=str(row["doc_type"]),
        source_path=str(row["source_path"]),
        title=str(row["title"]),
        version=int(row["version"]),
        status=str(row["status"]),
        tags=tags,
        metadata=metadata,
        content=str(row["content"]),
        score=score,
        reasons=reasons,
        vector_distance=float(row.get("vector_distance") or 1.0),
        text_score=float(row.get("text_score") or 0.0),
    )


def _tag_overlap(task: Task, doc_tags: Iterable[str]) -> tuple[float, list[str]]:
    wanted = {keyword.lower() for keyword in task.keywords}
    actual = {str(tag).lower() for tag in doc_tags}
    matched = sorted(wanted & actual)
    if not wanted:
        return 0.0, []
    return len(matched) / len(wanted), matched


def _symbol_match(task: Task, metadata: dict[str, Any]) -> tuple[float, str | None]:
    applies_to = metadata.get("applies_to") or []
    if isinstance(applies_to, str):
        applies_to = [applies_to]
    for symbol in task.target_symbols:
        if symbol in applies_to:
            return 1.0, symbol
    return 0.0, None


def query_specs(
    conn,
    task: Task,
    query_vector: Sequence[float],
    trace: QueryTrace,
    *,
    limit: int = 50,
) -> list[RetrievedDoc]:
    sql = """
        SELECT doc_key, doc_type, source_path, title, version, status, tags,
               metadata_json, content,
               cosine_distance(embedding, %s) AS vector_distance,
               MATCH(search_text) AGAINST(%s) AS text_score
        FROM documents
        WHERE status='active' AND doc_type IN ('spec', 'decision')
        ORDER BY vector_distance ASC
        LIMIT %s
    """
    rows = _query_rows(conn, trace, sql, [vector_literal(query_vector), task.query_text, limit])
    results: list[RetrievedDoc] = []
    for row in rows:
        vector_score = max(0.0, 1.0 - float(row.get("vector_distance") or 1.0))
        text_score = min(1.0, float(row.get("text_score") or 0.0) * 2.5)
        tag_score, matched_tags = _tag_overlap(task, str(row.get("tags") or "").split(","))
        metadata = json.loads(row.get("metadata_json") or "{}")
        symbol_score, matched_symbol = _symbol_match(task, metadata)
        score = 0.50 * vector_score + 0.22 * text_score + 0.18 * tag_score + 0.10 * symbol_score
        reasons = [
            f"vector={vector_score:.3f}",
            f"text={text_score:.3f}",
            f"tags={','.join(matched_tags) or '-'}",
            f"symbol={matched_symbol or '-'}",
        ]
        results.append(_row_to_doc(row, score=score, reasons=reasons))
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def query_code(
    conn,
    task: Task,
    query_vector: Sequence[float],
    trace: QueryTrace,
    *,
    limit: int = 50,
) -> list[RetrievedDoc]:
    sql = """
        SELECT doc_key, doc_type, source_path, title, version, status, tags,
               metadata_json, content,
               cosine_distance(embedding, %s) AS vector_distance,
               MATCH(search_text) AGAINST(%s) AS text_score
        FROM documents
        WHERE status='active' AND doc_type='code'
        ORDER BY vector_distance ASC
        LIMIT %s
    """
    rows = _query_rows(conn, trace, sql, [vector_literal(query_vector), task.query_text, limit])
    results: list[RetrievedDoc] = []
    for row in rows:
        vector_score = max(0.0, 1.0 - float(row.get("vector_distance") or 1.0))
        text_score = min(1.0, float(row.get("text_score") or 0.0) * 2.5)
        metadata = json.loads(row.get("metadata_json") or "{}")
        symbol_score, matched_symbol = _symbol_match(task, metadata)
        score = 0.62 * vector_score + 0.18 * text_score + 0.20 * symbol_score
        results.append(
            _row_to_doc(
                row,
                score=score,
                reasons=[
                    f"vector={vector_score:.3f}",
                    f"text={text_score:.3f}",
                    f"symbol={matched_symbol or '-'}",
                ],
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def query_tests(
    conn,
    task: Task,
    query_vector: Sequence[float],
    trace: QueryTrace,
    *,
    limit: int = 50,
) -> list[RetrievedDoc]:
    sql = """
        SELECT doc_key, doc_type, source_path, title, version, status, tags,
               metadata_json, content,
               cosine_distance(embedding, %s) AS vector_distance,
               MATCH(search_text) AGAINST(%s) AS text_score
        FROM documents
        WHERE status='active' AND doc_type='test'
        ORDER BY vector_distance ASC
        LIMIT %s
    """
    rows = _query_rows(conn, trace, sql, [vector_literal(query_vector), task.query_text, limit])
    results: list[RetrievedDoc] = []
    for row in rows:
        vector_score = max(0.0, 1.0 - float(row.get("vector_distance") or 1.0))
        text_score = min(1.0, float(row.get("text_score") or 0.0) * 2.5)
        metadata = json.loads(row.get("metadata_json") or "{}")
        kind = str(metadata.get("kind") or "")
        score = 0.70 * vector_score + 0.20 * text_score + (0.10 if kind == "target" else 0.05)
        results.append(
            _row_to_doc(
                row,
                score=score,
                reasons=[f"vector={vector_score:.3f}", f"text={text_score:.3f}", f"kind={kind or '-'}"],
            )
        )
    results.sort(key=lambda item: item.score, reverse=True)
    return results


def fetch_docs(conn, keys: Sequence[str], trace: QueryTrace) -> list[RetrievedDoc]:
    if not keys:
        return []
    placeholders = ",".join(["%s"] * len(keys))
    sql = f"""
        SELECT doc_key, doc_type, source_path, title, version, status, tags,
               metadata_json, content, 0.0 AS vector_distance, 0.0 AS text_score
        FROM documents
        WHERE status='active' AND doc_key IN ({placeholders})
    """
    rows = _query_rows(conn, trace, sql, list(keys))
    order = {key: index for index, key in enumerate(keys)}
    rows.sort(key=lambda row: order.get(str(row["doc_key"]), 999))
    return [_row_to_doc(row, score=1.0, reasons=["linked by spec/test graph"]) for row in rows]


def linked_tests(conn, source_keys: Sequence[str], trace: QueryTrace) -> list[RetrievedDoc]:
    if not source_keys:
        return []
    placeholders = ",".join(["%s"] * len(source_keys))
    sql = f"""
        SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags,
               d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score
        FROM documents d
        JOIN links l ON l.to_key = d.doc_key
        WHERE l.from_key IN ({placeholders}) AND l.relation='verified_by' AND d.status='active'
        ORDER BY d.doc_key
    """
    rows = _query_rows(conn, trace, sql, list(source_keys))
    return [
        _row_to_doc(row, score=0.95, reasons=["linked from an applicable spec via seekdb.links"])
        for row in rows
    ]


def linked_code(conn, source_keys: Sequence[str], trace: QueryTrace) -> list[RetrievedDoc]:
    if not source_keys:
        return []
    placeholders = ",".join(["%s"] * len(source_keys))
    sql = f"""
        SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags,
               d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score
        FROM documents d
        JOIN links l ON l.to_key = d.doc_key
        WHERE l.from_key IN ({placeholders}) AND l.relation='applies_to' AND d.status='active'
        ORDER BY d.doc_key
    """
    rows = _query_rows(conn, trace, sql, list(source_keys))
    return [
        _row_to_doc(row, score=0.98, reasons=["declared in spec applies_to via seekdb.links"])
        for row in rows
    ]


def tests_for_code(conn, code_keys: Sequence[str], trace: QueryTrace) -> list[RetrievedDoc]:
    if not code_keys:
        return []
    placeholders = ",".join(["%s"] * len(code_keys))
    sql = f"""
        SELECT d.doc_key, d.doc_type, d.source_path, d.title, d.version, d.status, d.tags,
               d.metadata_json, d.content, 0.0 AS vector_distance, 0.0 AS text_score
        FROM documents d
        JOIN links l ON l.to_key = d.doc_key
        WHERE l.from_key IN ({placeholders}) AND l.relation='covered_by' AND d.status='active'
        ORDER BY d.doc_key
    """
    rows = _query_rows(conn, trace, sql, list(code_keys))
    return [
        _row_to_doc(row, score=0.85, reasons=["test covers a selected code symbol via seekdb.links"])
        for row in rows
    ]


def dedupe(items: Iterable[RetrievedDoc]) -> list[RetrievedDoc]:
    seen: dict[str, RetrievedDoc] = {}
    for item in items:
        current = seen.get(item.doc_key)
        if current is None or item.score > current.score:
            seen[item.doc_key] = item
    return list(seen.values())
