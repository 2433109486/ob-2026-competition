"""seekdb access, schema, seed import, and evidence logging."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings, settings
from .embeddings import embed_document, to_sql_vector

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS papers (
      paper_id VARCHAR(64) NOT NULL PRIMARY KEY,
      title VARCHAR(512) NOT NULL,
      title_en VARCHAR(512) NOT NULL DEFAULT '',
      authors VARCHAR(512) NOT NULL DEFAULT '',
      year INT NOT NULL,
      venue VARCHAR(255) NOT NULL DEFAULT '',
      doi VARCHAR(128) NOT NULL DEFAULT '',
      url VARCHAR(512) NOT NULL DEFAULT '',
      abstract MEDIUMTEXT NOT NULL,
      tags VARCHAR(512) NOT NULL DEFAULT '',
      status VARCHAR(16) NOT NULL DEFAULT 'to_read',
      priority INT NOT NULL DEFAULT 3,
      read_minutes INT NOT NULL DEFAULT 0,
      source_type VARCHAR(16) NOT NULL DEFAULT 'paper',
      cite_text VARCHAR(1024) NOT NULL DEFAULT '',
      review_problem MEDIUMTEXT NOT NULL,
      review_method MEDIUMTEXT NOT NULL,
      review_sample MEDIUMTEXT NOT NULL,
      review_finding MEDIUMTEXT NOT NULL,
      review_limitation MEDIUMTEXT NOT NULL,
      review_reuse MEDIUMTEXT NOT NULL,
      added_at DATETIME NOT NULL,
      updated_at DATETIME NOT NULL,
      last_read_at DATETIME NULL,
      INDEX idx_papers_year (year),
      INDEX idx_papers_status (status)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
      chunk_id VARCHAR(96) NOT NULL PRIMARY KEY,
      paper_id VARCHAR(64) NOT NULL,
      section VARCHAR(64) NOT NULL,
      page VARCHAR(32) NOT NULL DEFAULT '',
      content MEDIUMTEXT NOT NULL,
      search_text MEDIUMTEXT NOT NULL,
      embedding VECTOR(768),
      FULLTEXT INDEX ft_chunks (search_text) WITH PARSER ngram2,
      VECTOR INDEX vidx_chunks (embedding) WITH (DISTANCE=cosine, TYPE=hnsw, LIB=vsag),
      INDEX idx_chunks_paper (paper_id)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS notes (
      note_id VARCHAR(64) NOT NULL PRIMARY KEY,
      paper_id VARCHAR(64) NOT NULL,
      note_type VARCHAR(24) NOT NULL DEFAULT 'note',
      content MEDIUMTEXT NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_notes_paper (paper_id)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS search_log (
      search_id VARCHAR(64) NOT NULL PRIMARY KEY,
      query VARCHAR(512) NOT NULL,
      filters_json MEDIUMTEXT NOT NULL,
      result_count INT NOT NULL,
      latency_ms INT NOT NULL,
      mode VARCHAR(32) NOT NULL,
      memory_used TINYINT NOT NULL DEFAULT 0,
      created_at DATETIME NOT NULL,
      INDEX idx_search_created (created_at)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS activity (
      activity_id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      kind VARCHAR(32) NOT NULL,
      title VARCHAR(255) NOT NULL,
      detail_json MEDIUMTEXT NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_activity_created (created_at)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS app_meta (
      meta_key VARCHAR(128) NOT NULL PRIMARY KEY,
      meta_value MEDIUMTEXT NOT NULL,
      updated_at DATETIME NOT NULL
    ) ORGANIZATION = HEAP
    """,
]

TABLE_ORDER = ["chunks", "notes", "search_log", "activity", "papers", "app_meta"]


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def ensure_tag_string(tags: str) -> str:
    clean = [item.strip() for item in str(tags or "").replace("，", ",").split(",") if item.strip()]
    return "," + ",".join(dict.fromkeys(clean)) + "," if clean else ",,"


def tag_list(tags: str) -> List[str]:
    return [item for item in str(tags or "").replace("，", ",").split(",") if item]


def connect(database: Optional[str] = None) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=8,
        read_timeout=30,
        write_timeout=30,
        cursorclass=DictCursor,
    )


def ping() -> Dict[str, Any]:
    started = time.perf_counter()
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION() AS version")
            version = cur.fetchone()["version"]
    finally:
        conn.close()
    return {
        "ok": True,
        "version": version,
        "database": settings.seekdb_database,
        "latency_ms": int((time.perf_counter() - started) * 1000),
    }


def ensure_schema(*, reset: bool = False) -> None:
    admin = connect()
    try:
        with admin.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.seekdb_database}`")
    finally:
        admin.close()

    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            if reset:
                for table in TABLE_ORDER:
                    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            for statement in SCHEMA_STATEMENTS:
                cur.execute(statement)
    finally:
        conn.close()


def table_counts() -> Dict[str, int]:
    conn = connect(settings.seekdb_database)
    try:
        counts: Dict[str, int] = {}
        with conn.cursor() as cur:
            for table in ["papers", "chunks", "notes", "search_log", "activity"]:
                cur.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                counts[table] = int(cur.fetchone()["n"])
        return counts
    finally:
        conn.close()


def seed_database(*, force: bool = False) -> Dict[str, Any]:
    ensure_schema(reset=force)
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM papers")
            existing = int(cur.fetchone()["n"])
            if existing and not force:
                return {"seeded": False, "papers": existing, **table_counts()}

            if force:
                for table in ["chunks", "notes", "search_log", "activity", "papers", "app_meta"]:
                    cur.execute(f"DELETE FROM `{table}`")

            payload = json.loads((settings.seed_dir / "papers.json").read_text(encoding="utf-8"))
            papers = payload["papers"]
            timestamp = now_utc()
            chunk_rows: List[Sequence[Any]] = []
            note_rows: List[Sequence[Any]] = []
            for paper in papers:
                tags = ensure_tag_string(paper.get("tags", ""))
                review = paper.get("review", {})
                cur.execute(
                    """
                    INSERT INTO papers (
                      paper_id, title, title_en, authors, year, venue, doi, url, abstract,
                      tags, status, priority, read_minutes, source_type, cite_text,
                      review_problem, review_method, review_sample, review_finding,
                      review_limitation, review_reuse, added_at, updated_at, last_read_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        paper["paper_id"],
                        paper["title"],
                        paper.get("title_en", ""),
                        paper.get("authors", ""),
                        int(paper.get("year", 0)),
                        paper.get("venue", ""),
                        paper.get("doi", ""),
                        paper.get("url", ""),
                        paper.get("abstract", ""),
                        tags,
                        paper.get("status", "to_read"),
                        int(paper.get("priority", 3)),
                        int(paper.get("read_minutes", 0)),
                        paper.get("source_type", "paper"),
                        paper.get("cite_text", ""),
                        review.get("problem", ""),
                        review.get("method", ""),
                        review.get("sample", ""),
                        review.get("finding", ""),
                        review.get("limitation", ""),
                        review.get("reuse", ""),
                        timestamp,
                        timestamp,
                        timestamp if paper.get("status") in {"read", "reading"} else None,
                    ),
                )
                for index, chunk in enumerate(paper.get("chunks", []), start=1):
                    search_text = " ".join(
                        [
                            paper["title"],
                            paper.get("title_en", ""),
                            paper.get("tags", ""),
                            chunk.get("section", ""),
                            chunk.get("content", ""),
                        ]
                    )
                    vector = embed_document(
                        paper["title"],
                        paper.get("tags", ""),
                        chunk.get("section", ""),
                        chunk.get("content", ""),
                    )
                    chunk_rows.append(
                        (
                            f"{paper['paper_id']}-c{index}",
                            paper["paper_id"],
                            chunk.get("section", "正文"),
                            chunk.get("page", ""),
                            chunk.get("content", ""),
                            search_text,
                            to_sql_vector(vector),
                        )
                    )
                for index, note in enumerate(paper.get("notes", []), start=1):
                    note_rows.append(
                        (
                            f"{paper['paper_id']}-n{index}",
                            paper["paper_id"],
                            note.get("note_type", "note"),
                            note.get("content", ""),
                            timestamp,
                        )
                    )

            if chunk_rows:
                cur.executemany(
                    """
                    INSERT INTO chunks (chunk_id, paper_id, section, page, content, search_text, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """,
                    chunk_rows,
                )
            if note_rows:
                cur.executemany(
                    """
                    INSERT INTO notes (note_id, paper_id, note_type, content, created_at)
                    VALUES (%s,%s,%s,%s,%s)
                    """,
                    note_rows,
                )
            cur.execute(
                "INSERT INTO app_meta (meta_key, meta_value, updated_at) VALUES ('seeded_at', %s, %s)",
                (timestamp, timestamp),
            )
            cur.execute(
                "INSERT INTO activity (kind, title, detail_json, created_at) VALUES (%s,%s,%s,%s)",
                (
                    "seed",
                    "导入演示资料库",
                    json.dumps({"papers": len(papers), "chunks": len(chunk_rows)}, ensure_ascii=False),
                    timestamp,
                ),
            )
        return {
            "seeded": True,
            "papers": len(papers),
            "chunks": len(chunk_rows),
            "notes": len(note_rows),
            **table_counts(),
        }
    finally:
        conn.close()


def log_activity(kind: str, title: str, detail: Optional[Dict[str, Any]] = None) -> None:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO activity (kind, title, detail_json, created_at) VALUES (%s,%s,%s,%s)",
                (kind, title[:255], json.dumps(detail or {}, ensure_ascii=False), now_utc()),
            )
    finally:
        conn.close()


def recent_activity(limit: int = 12) -> List[Dict[str, Any]]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT activity_id, kind, title, detail_json, created_at
                FROM activity ORDER BY activity_id DESC LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for row in rows:
        row["detail"] = _safe_json(row.pop("detail_json", "{}"))
        row["created_at"] = str(row["created_at"])
    return rows


def log_search(
    query: str,
    filters: Dict[str, Any],
    result_count: int,
    latency_ms: int,
    mode: str,
    memory_used: bool,
) -> str:
    search_id = "srch_" + uuid.uuid4().hex[:12]
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO search_log
                  (search_id, query, filters_json, result_count, latency_ms, mode, memory_used, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    search_id,
                    query[:500],
                    json.dumps(filters, ensure_ascii=False),
                    result_count,
                    latency_ms,
                    mode,
                    1 if memory_used else 0,
                    now_utc(),
                ),
            )
    finally:
        conn.close()
    return search_id


def usage_stats(days: int = 7) -> Dict[str, Any]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS searches,
                       COALESCE(AVG(latency_ms), 0) AS avg_latency,
                       COALESCE(SUM(memory_used), 0) AS memory_searches
                FROM search_log
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                """,
                (days,),
            )
            summary = cur.fetchone()
            cur.execute(
                """
                SELECT query, COUNT(*) AS n FROM search_log
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY query ORDER BY n DESC, query ASC LIMIT 5
                """,
                (days,),
            )
            top_queries = cur.fetchall()
    finally:
        conn.close()
    return {
        "days": days,
        "searches": int(summary["searches"] or 0),
        "avg_latency_ms": int(float(summary["avg_latency"] or 0)),
        "memory_searches": int(summary["memory_searches"] or 0),
        "top_queries": [{"query": row["query"], "count": int(row["n"])} for row in top_queries],
    }


def tag_counts() -> List[Dict[str, Any]]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT tags FROM papers")
            rows = cur.fetchall()
    finally:
        conn.close()
    counts: Dict[str, int] = {}
    for row in rows:
        for tag in tag_list(row.get("tags", "")):
            counts[tag] = counts.get(tag, 0) + 1
    return [{"name": name, "count": count} for name, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def recent_searches(limit: int = 8) -> List[Dict[str, Any]]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT search_id, query, result_count, latency_ms, mode, memory_used, created_at
                FROM search_log ORDER BY created_at DESC LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    for row in rows:
        row["created_at"] = str(row["created_at"])
        row["memory_used"] = bool(row["memory_used"])
    return rows


def _safe_json(value: str) -> Any:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}


@contextmanager
def cursor() -> Iterator[DictCursor]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


def fetch_papers(
    *,
    query: str = "",
    status: str = "",
    tag: str = "",
    limit: int = 50,
) -> List[Dict[str, Any]]:
    clauses = ["1=1"]
    params: List[Any] = []
    if query:
        clauses.append("(title LIKE %s OR title_en LIKE %s OR abstract LIKE %s OR authors LIKE %s)")
        like = f"%{query}%"
        params.extend([like, like, like, like])
    if status:
        clauses.append("status = %s")
        params.append(status)
    if tag:
        clauses.append("tags LIKE %s")
        params.append(f"%,{tag},%")
    params.append(limit)
    sql = f"""
        SELECT paper_id, title, title_en, authors, year, venue, doi, url, abstract, tags,
               status, priority, read_minutes, source_type, cite_text, last_read_at, updated_at,
               review_problem, review_method, review_sample, review_finding, review_limitation, review_reuse
        FROM papers WHERE {' AND '.join(clauses)}
        ORDER BY priority ASC, year DESC LIMIT %s
    """
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    finally:
        conn.close()
    return [_paper_payload(row) for row in rows]


def fetch_paper(paper_id: str) -> Optional[Dict[str, Any]]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT paper_id, title, title_en, authors, year, venue, doi, url, abstract, tags,
                       status, priority, read_minutes, source_type, cite_text, last_read_at, updated_at,
                       review_problem, review_method, review_sample, review_finding, review_limitation, review_reuse
                FROM papers WHERE paper_id=%s
                """,
                (paper_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            cur.execute(
                "SELECT chunk_id, section, page, content FROM chunks WHERE paper_id=%s ORDER BY chunk_id",
                (paper_id,),
            )
            chunks = cur.fetchall()
            cur.execute(
                "SELECT note_id, note_type, content, created_at FROM notes WHERE paper_id=%s ORDER BY created_at DESC",
                (paper_id,),
            )
            notes = cur.fetchall()
    finally:
        conn.close()
    payload = _paper_payload(row)
    payload["chunks"] = chunks
    payload["notes"] = [
        {**note, "created_at": str(note["created_at"])} for note in notes
    ]
    return payload


def update_paper(paper_id: str, fields: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    allowed = {
        "status",
        "priority",
        "read_minutes",
        "review_problem",
        "review_method",
        "review_sample",
        "review_finding",
        "review_limitation",
        "review_reuse",
        "tags",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    if not updates:
        return fetch_paper(paper_id)
    if "tags" in updates:
        updates["tags"] = ensure_tag_string(updates["tags"])
    assignments = ", ".join(f"`{key}`=%s" for key in updates)
    assignments += ", updated_at=%s"
    values = list(updates.values()) + [now_utc()]
    if updates.get("status") in {"read", "reading"}:
        assignments += ", last_read_at=%s"
        values.append(now_utc())
    values.append(paper_id)
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE papers SET {assignments} WHERE paper_id=%s", tuple(values))
    finally:
        conn.close()
    return fetch_paper(paper_id)


def add_note(paper_id: str, note_type: str, content: str) -> Dict[str, Any]:
    note_id = "note_" + uuid.uuid4().hex[:12]
    timestamp = now_utc()
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notes (note_id, paper_id, note_type, content, created_at) VALUES (%s,%s,%s,%s,%s)",
                (note_id, paper_id, note_type, content, timestamp),
            )
    finally:
        conn.close()
    return {"note_id": note_id, "paper_id": paper_id, "note_type": note_type, "content": content, "created_at": timestamp}


def _paper_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    row = dict(row)
    row["tags"] = tag_list(row.get("tags", ""))
    for key in ("last_read_at", "updated_at"):
        if row.get(key) is not None:
            row[key] = str(row[key])
    return row


def get_meta(key: str) -> Optional[str]:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT meta_value FROM app_meta WHERE meta_key=%s", (key,))
            row = cur.fetchone()
            return row["meta_value"] if row else None
    finally:
        conn.close()


def set_meta(key: str, value: str) -> None:
    conn = connect(settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_meta (meta_key, meta_value, updated_at) VALUES (%s,%s,%s)
                ON DUPLICATE KEY UPDATE meta_value=VALUES(meta_value), updated_at=VALUES(updated_at)
                """,
                (key, value, now_utc()),
            )
    finally:
        conn.close()


def db_health() -> Dict[str, Any]:
    try:
        return ping()
    except Exception as error:  # noqa: BLE001 - health endpoint must not crash
        return {"ok": False, "error": str(error)}
