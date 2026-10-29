"""seekdb (MySQL protocol) access for the engineering corpus."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Sequence

import pymysql

from .config import Settings

DDL = [
    """
    CREATE TABLE IF NOT EXISTS documents (
      doc_key VARCHAR(255) NOT NULL PRIMARY KEY,
      doc_type VARCHAR(16) NOT NULL,
      source_path VARCHAR(512) NOT NULL,
      title VARCHAR(255) NOT NULL,
      version INT NOT NULL DEFAULT 1,
      status VARCHAR(16) NOT NULL DEFAULT 'active',
      tags VARCHAR(512) NOT NULL DEFAULT '',
      metadata_json MEDIUMTEXT NOT NULL,
      content MEDIUMTEXT NOT NULL,
      search_text MEDIUMTEXT NOT NULL,
      content_hash CHAR(64) NOT NULL,
      embedding VECTOR(1536),
      updated_at DATETIME NOT NULL,
      FULLTEXT INDEX ft_documents (search_text) WITH PARSER ngram2,
      VECTOR INDEX vidx_documents (embedding) WITH (DISTANCE=cosine, TYPE=hnsw, LIB=vsag)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS document_versions (
      revision INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      doc_key VARCHAR(255) NOT NULL,
      version INT NOT NULL,
      status VARCHAR(16) NOT NULL,
      source_path VARCHAR(512) NOT NULL,
      content MEDIUMTEXT NOT NULL,
      content_hash CHAR(64) NOT NULL,
      tags VARCHAR(512) NOT NULL DEFAULT '',
      metadata_json MEDIUMTEXT NOT NULL,
      ingested_at DATETIME NOT NULL,
      INDEX idx_versions_key (doc_key, revision)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS links (
      from_key VARCHAR(255) NOT NULL,
      to_key VARCHAR(255) NOT NULL,
      relation VARCHAR(32) NOT NULL,
      weight DOUBLE NOT NULL DEFAULT 1.0,
      PRIMARY KEY (from_key, to_key, relation)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS context_runs (
      run_id VARCHAR(64) NOT NULL PRIMARY KEY,
      task_id VARCHAR(128) NOT NULL,
      task_text MEDIUMTEXT NOT NULL,
      context_json MEDIUMTEXT NOT NULL,
      context_md MEDIUMTEXT NOT NULL,
      created_at DATETIME NOT NULL
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS query_log (
      id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
      run_id VARCHAR(64) NOT NULL,
      sql_text MEDIUMTEXT NOT NULL,
      params_json MEDIUMTEXT NOT NULL,
      row_count INT NOT NULL,
      elapsed_ms INT NOT NULL,
      created_at DATETIME NOT NULL,
      INDEX idx_query_run (run_id)
    ) ORGANIZATION = HEAP
    """,
    """
    CREATE TABLE IF NOT EXISTS ingest_runs (
      run_id VARCHAR(64) NOT NULL PRIMARY KEY,
      started_at DATETIME NOT NULL,
      finished_at DATETIME NOT NULL,
      doc_count INT NOT NULL,
      status VARCHAR(16) NOT NULL,
      notes MEDIUMTEXT NOT NULL
    ) ORGANIZATION = HEAP
    """,
]


@dataclass(slots=True)
class QueryRecord:
    sql: str
    params: Sequence[Any]
    row_count: int
    elapsed_ms: int


class QueryTrace:
    """Collect SQL statements so a context run can prove what seekdb returned."""

    def __init__(self) -> None:
        self.records: list[QueryRecord] = []

    def add(self, sql: str, params: Sequence[Any], row_count: int, elapsed_ms: int) -> None:
        self.records.append(QueryRecord(sql=sql, params=list(params), row_count=row_count, elapsed_ms=elapsed_ms))

    def to_json(self) -> list[dict[str, Any]]:
        return [
            {
                "sql": " ".join(record.sql.split()),
                "params": [str(param)[:500] for param in record.params],
                "row_count": record.row_count,
                "elapsed_ms": record.elapsed_ms,
            }
            for record in self.records
        ]


def connect(settings: Settings, *, database: str | None = None) -> pymysql.connections.Connection:
    return pymysql.connect(
        host=settings.seekdb_host,
        port=settings.seekdb_port,
        user=settings.seekdb_user,
        password=settings.seekdb_password,
        database=database,
        charset="utf8mb4",
        autocommit=True,
        connect_timeout=10,
        read_timeout=30,
        write_timeout=30,
    )


def vector_literal(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"


def ensure_schema(settings: Settings, *, reset: bool = False) -> dict[str, int]:
    admin = connect(settings)
    try:
        with admin.cursor() as cur:
            cur.execute(f"CREATE DATABASE IF NOT EXISTS `{settings.seekdb_database}`")
    finally:
        admin.close()

    conn = connect(settings, database=settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            if reset:
                for table in (
                    "query_log",
                    "context_runs",
                    "links",
                    "document_versions",
                    "documents",
                    "ingest_runs",
                ):
                    cur.execute(f"DROP TABLE IF EXISTS `{table}`")
            for statement in DDL:
                cur.execute(statement)
            cur.execute("SELECT COUNT(*) FROM documents")
            documents = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM document_versions")
            versions = int(cur.fetchone()[0])
            cur.execute("SELECT COUNT(*) FROM links")
            links = int(cur.fetchone()[0])
        return {"documents": documents, "versions": versions, "links": links}
    finally:
        conn.close()


@contextmanager
def traced_cursor(
    conn: pymysql.connections.Connection,
    trace: QueryTrace,
    sql: str,
    params: Sequence[Any] = (),
) -> Iterator[pymysql.cursors.Cursor]:
    started = time.perf_counter()
    cur = conn.cursor()
    try:
        cur.execute(sql, tuple(params))
        yield cur
    finally:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        trace.add(sql, params, cur.rowcount if cur.rowcount is not None else -1, elapsed_ms)
        cur.close()


def save_query_trace(conn: pymysql.connections.Connection, run_id: str, trace: QueryTrace) -> None:
    if not trace.records:
        return
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO query_log (run_id, sql_text, params_json, row_count, elapsed_ms, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            [
                (
                    run_id,
                    " ".join(record.sql.split()),
                    json.dumps(record.params, ensure_ascii=False)[:6000],
                    record.row_count,
                    record.elapsed_ms,
                )
                for record in trace.records
            ],
        )


def save_context_run(
    conn: pymysql.connections.Connection,
    run_id: str,
    task_id: str,
    task_text: str,
    context: dict[str, Any],
    markdown: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO context_runs (run_id, task_id, task_text, context_json, context_md, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON DUPLICATE KEY UPDATE context_json=VALUES(context_json), context_md=VALUES(context_md)
            """,
            (run_id, task_id, task_text, json.dumps(context, ensure_ascii=False), markdown),
        )
