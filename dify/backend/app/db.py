"""seekdb 访问层：法典检索、判例库、庭审与玩家档案。

seekdb 在这里承担三类“应用数据”职责：
1. `statutes`：荒诞法典语料，向量 + 全文 + 标量标签的混合检索；
2. `precedents`：历史判例，供相似案件召回；
3. `players` / `cases` / `turns` / `counters`：玩家档案、案件状态、庭审记录与案号序列。
"""

from __future__ import annotations

import json
import re
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import pymysql
from pymysql.cursors import DictCursor

from .config import Settings
from .embeddings import Embedder, to_sql_vector
from .statutes import STATUTES, infer_tag

RRF_K = 60


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def sanitize_fts(query: str) -> str:
    """全文检索只保留中英文与数字，避免把标点当成语法。"""

    terms = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", query)
    # ngram2 对超长中文串也能切分；限制词数避免查询过宽
    return " ".join(terms[:24]) or "案件"


_STOP_BIGRAMS = {
    "我的", "你的", "他的", "她的", "它的", "我要", "要告", "它还", "每天",
    "一个", "这个", "那个", "然后", "就是", "因为", "所以", "可以", "已经",
    "现在", "还是", "什么", "怎么", "不是", "我们", "他们", "你们", "一下",
}


def _bigrams(text: str) -> set[str]:
    grams: set[str] = set()
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) == 1:
            grams.add(run)
        grams.update(run[i : i + 2] for i in range(len(run) - 1))
    for word in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
        grams.add(word)
    return grams


def _overlap_count(query: str, content: str) -> int:
    return len((_bigrams(query) - _STOP_BIGRAMS) & _bigrams(content))


class Store:
    def __init__(self, settings: Settings, embedder: Embedder) -> None:
        self.settings = settings
        self.embedder = embedder

    @contextmanager
    def connect(self) -> Iterator[pymysql.connections.Connection]:
        conn = pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password,
            database=self.settings.seekdb_database,
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=5,
            cursorclass=DictCursor,
        )
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------ 初始化
    def init_schema(self, recreate: bool = False) -> None:
        db = self.settings.seekdb_database
        dim = self.settings.embedding_dim
        admin = pymysql.connect(
            host=self.settings.seekdb_host,
            port=self.settings.seekdb_port,
            user=self.settings.seekdb_user,
            password=self.settings.seekdb_password,
            charset="utf8mb4",
            autocommit=True,
        )
        try:
            with admin.cursor() as cur:
                cur.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{db}` DEFAULT CHARACTER SET utf8mb4"
                )
        finally:
            admin.close()

        statements = [
            f"""
            CREATE TABLE IF NOT EXISTS statutes (
              code       VARCHAR(16) PRIMARY KEY,
              title      VARCHAR(80)  NOT NULL,
              content    TEXT         NOT NULL,
              tag        VARCHAR(16)  NOT NULL,
              min_days   INT          NOT NULL,
              max_days   INT          NOT NULL,
              fine       VARCHAR(64)  NOT NULL,
              severity   INT          NOT NULL,
              embedding  VECTOR({dim}) NOT NULL,
              FULLTEXT INDEX ft_statutes (content) WITH PARSER ngram2,
              VECTOR INDEX vidx_statutes (embedding) WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag),
              KEY idx_statutes_tag (tag)
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS players (
              player_id       VARCHAR(64) PRIMARY KEY,
              pc_scope_id     VARCHAR(64) NULL,
              cases           INT NOT NULL DEFAULT 0,
              convictions     INT NOT NULL DEFAULT 0,
              total_days      INT NOT NULL DEFAULT 0,
              absurdity_sum   INT NOT NULL DEFAULT 0,
              first_seen      DATETIME NOT NULL,
              last_seen       DATETIME NOT NULL
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS cases (
              case_id         VARCHAR(32) PRIMARY KEY,
              case_no         VARCHAR(64) NOT NULL,
              conversation_id VARCHAR(128) NOT NULL,
              player_id       VARCHAR(64) NOT NULL,
              defendant       VARCHAR(128) NULL,
              charge          VARCHAR(128) NULL,
              status          VARCHAR(16) NOT NULL,
              turn            INT NOT NULL DEFAULT 0,
              created_at      DATETIME NOT NULL,
              updated_at      DATETIME NOT NULL,
              KEY idx_cases_conv (conversation_id),
              KEY idx_cases_player (player_id)
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS turns (
              id          BIGINT PRIMARY KEY,
              case_id     VARCHAR(32) NOT NULL,
              turn        INT NOT NULL,
              role        VARCHAR(16) NOT NULL,
              content     TEXT NOT NULL,
              created_at  DATETIME NOT NULL,
              KEY idx_turns_case (case_id)
            ) ORGANIZATION = HEAP
            """,
            f"""
            CREATE TABLE IF NOT EXISTS precedents (
              id           BIGINT PRIMARY KEY,
              case_id      VARCHAR(32) NOT NULL,
              case_no      VARCHAR(64) NOT NULL,
              player_id    VARCHAR(64) NOT NULL,
              defendant    VARCHAR(128) NOT NULL,
              charge       VARCHAR(128) NOT NULL,
              summary      TEXT NOT NULL,
              cited        VARCHAR(255) NOT NULL,
              sentence_days INT NOT NULL,
              absurdity    INT NOT NULL,
              attitude     VARCHAR(16) NOT NULL,
              created_at   DATETIME NOT NULL,
              embedding    VECTOR({dim}) NOT NULL,
              FULLTEXT INDEX ft_precedents (summary) WITH PARSER ngram2,
              VECTOR INDEX vidx_precedents (embedding) WITH (DISTANCE=l2, TYPE=hnsw, LIB=vsag),
              KEY idx_precedents_player (player_id)
            ) ORGANIZATION = HEAP
            """,
            """
            CREATE TABLE IF NOT EXISTS counters (
              name  VARCHAR(32) PRIMARY KEY,
              value INT NOT NULL
            ) ORGANIZATION = HEAP
            """,
        ]

        with self.connect() as conn:
            with conn.cursor() as cur:
                if recreate:
                    for table in ("turns", "precedents", "cases", "players", "statutes", "counters"):
                        cur.execute(f"DROP TABLE IF EXISTS {table}")
                for ddl in statements:
                    cur.execute(ddl)
                cur.execute(
                    "INSERT INTO counters (name, value) VALUES ('case_no', 0) "
                    "ON DUPLICATE KEY UPDATE value = value"
                )

    def seed_statutes(self, force: bool = False) -> int:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM statutes")
                existing = cur.fetchone()["n"]
                if existing and not force:
                    return existing
                rows = []
                for statute in STATUTES:
                    content = (
                        f"{statute.title}。{statute.text}\n"
                        f"案由：{statute.tag}。关键词：{statute.keywords}"
                    )
                    vector = self.embedder.embed_one(content)
                    rows.append(
                        (
                            statute.code,
                            statute.title,
                            content,
                            statute.tag,
                            statute.min_days,
                            statute.max_days,
                            statute.fine,
                            statute.severity,
                            to_sql_vector(vector),
                        )
                    )
                cur.execute("DELETE FROM statutes")
                cur.executemany(
                    "INSERT INTO statutes "
                    "(code, title, content, tag, min_days, max_days, fine, severity, embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    rows,
                )
                return len(rows)

    # ------------------------------------------------------------------ 玩家
    def get_or_create_player(self, player_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM players WHERE player_id = %s", (player_id,))
                row = cur.fetchone()
                if row:
                    cur.execute("UPDATE players SET last_seen = %s WHERE player_id = %s", (_now(), player_id))
                    return row
                cur.execute(
                    "INSERT INTO players (player_id, cases, convictions, total_days, absurdity_sum, first_seen, last_seen) "
                    "VALUES (%s, 0, 0, 0, 0, %s, %s)",
                    (player_id, _now(), _now()),
                )
                cur.execute("SELECT * FROM players WHERE player_id = %s", (player_id,))
                return cur.fetchone()

    def set_scope(self, player_id: str, scope_id: str) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE players SET pc_scope_id = %s WHERE player_id = %s", (scope_id, player_id))

    def profile(self, player_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM players WHERE player_id = %s", (player_id,))
                row = cur.fetchone()
        if not row:
            return {
                "player_id": player_id,
                "cases": 0,
                "convictions": 0,
                "total_days": 0,
                "avg_absurdity": 0,
                "title": "法庭新鲜人",
            }
        convictions = row["convictions"]
        cases = row["cases"]
        avg = round(row["absurdity_sum"] / convictions) if convictions else 0
        if convictions == 0:
            title = "法庭新鲜人"
        elif convictions == 1:
            title = "初犯旁听生"
        elif convictions <= 3:
            title = "法庭常客"
        elif convictions <= 6:
            title = "诉讼惯犯"
        else:
            title = "法外狂徒"
        return {
            "player_id": player_id,
            "cases": cases,
            "convictions": convictions,
            "total_days": row["total_days"],
            "avg_absurdity": avg,
            "title": title,
            "first_seen": str(row["first_seen"]),
        }

    # ------------------------------------------------------------------ 案件
    def _next_case_no(self, cur) -> str:
        cur.execute("UPDATE counters SET value = value + 1 WHERE name = 'case_no'")
        cur.execute("SELECT value FROM counters WHERE name = 'case_no'")
        seq = cur.fetchone()["value"]
        return f"（3026）离民初字第{seq:04d}号"

    def get_or_create_case(self, player_id: str, conversation_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM cases WHERE conversation_id = %s AND status = 'open' "
                    "ORDER BY created_at DESC LIMIT 1",
                    (conversation_id,),
                )
                row = cur.fetchone()
                if row:
                    return row
                case_id = "AB-" + uuid.uuid4().hex[:8].upper()
                case_no = self._next_case_no(cur)
                cur.execute(
                    "INSERT INTO cases (case_id, case_no, conversation_id, player_id, status, turn, created_at, updated_at) "
                    "VALUES (%s,%s,%s,%s,'open',0,%s,%s)",
                    (case_id, case_no, conversation_id, player_id, _now(), _now()),
                )
                cur.execute("UPDATE players SET cases = cases + 1, last_seen = %s WHERE player_id = %s", (_now(), player_id))
                cur.execute("SELECT * FROM cases WHERE case_id = %s", (case_id,))
                return cur.fetchone()

    def update_case(self, case_id: str, **fields: Any) -> None:
        if not fields:
            return
        columns = ", ".join(f"{key} = %s" for key in fields)
        params = list(fields.values()) + [_now(), case_id]
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"UPDATE cases SET {columns}, updated_at = %s WHERE case_id = %s", params)

    def add_turn(self, case_id: str, turn: int, role: str, content: str) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO turns (id, case_id, turn, role, content, created_at) VALUES (%s,%s,%s,%s,%s,%s)",
                    (int(uuid.uuid4().int % (2**62)), case_id, turn, role, content, _now()),
                )

    def transcript(self, case_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT turn, role, content FROM turns WHERE case_id = %s ORDER BY turn, id", (case_id,))
                return list(cur.fetchall())

    # ------------------------------------------------------------------ 检索
    def _vector_search(self, cur, query: str, limit: int, tag: str | None) -> list[dict[str, Any]]:
        vector = to_sql_vector(self.embedder.embed_one(query))
        where = "WHERE tag = %s" if tag else ""
        params: list[Any] = [vector]
        if tag:
            params.append(tag)
        params.append(limit)
        cur.execute(
            f"SELECT code, title, content, tag, min_days, max_days, fine, severity, "
            f"l2_distance(embedding, %s) AS dist FROM statutes {where} ORDER BY dist LIMIT %s",
            params,
        )
        return list(cur.fetchall())

    def _fulltext_search(self, cur, query: str, limit: int, tag: str | None) -> list[dict[str, Any]]:
        fts = sanitize_fts(query)
        where = "WHERE tag = %s AND MATCH(content) AGAINST(%s)" if tag else "WHERE MATCH(content) AGAINST(%s)"
        params: list[Any] = [tag, fts] if tag else [fts]
        params.append(limit)
        cur.execute(
            f"SELECT code, title, content, tag, min_days, max_days, fine, severity "
            f"FROM statutes {where} LIMIT %s",
            params,
        )
        return list(cur.fetchall())

    def search_statutes(self, query: str, k: int = 3) -> tuple[list[dict[str, Any]], str | None]:
        """向量召回 + 全文召回 + 标量标签过滤，用 RRF 融合。"""

        tag = infer_tag(query)
        with self.connect() as conn:
            with conn.cursor() as cur:
                vector_rows = self._vector_search(cur, query, 8, tag)
                text_rows = self._fulltext_search(cur, query, 8, tag)
                if not vector_rows and not text_rows:
                    vector_rows = self._vector_search(cur, query, 8, None)
                    text_rows = self._fulltext_search(cur, query, 8, None)
                    tag = None
                if not vector_rows:
                    vector_rows = self._vector_search(cur, query, 8, None)
                if not text_rows:
                    text_rows = []

        scores: dict[str, float] = {}
        channels: dict[str, set[str]] = {}
        rows: dict[str, dict[str, Any]] = {}
        for source, items in (("vector", vector_rows), ("fulltext", text_rows)):
            for rank, item in enumerate(items):
                code = item["code"]
                rows[code] = item
                scores[code] = scores.get(code, 0.0) + 1.0 / (RRF_K + rank + 1)
                channels.setdefault(code, set()).add(source)

        # RRF 只反映“被两个通道同时召回”，对“每天”这类高频词没有区分度。
        # 追加一个轻量的词面重合度修正，避免“多肉养死罪”混进猫的案件。
        for code, item in rows.items():
            overlap = _overlap_count(query, item["content"])
            item["overlap"] = overlap
            scores[code] += 0.02 * min(overlap, 6)

        ranked = sorted(rows.values(), key=lambda r: scores[r["code"]], reverse=True)[:k]
        for item in ranked:
            item["score"] = round(scores[item["code"]], 6)
            item["channels"] = sorted(channels[item["code"]])
            item["text"] = item.pop("content")
        return ranked, tag

    def search_precedents(self, query: str, k: int = 2) -> list[dict[str, Any]]:
        vector = to_sql_vector(self.embedder.embed_one(query))
        fts = sanitize_fts(query)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, case_no, defendant, charge, summary, cited, sentence_days, absurdity, attitude, "
                    "l2_distance(embedding, %s) AS dist FROM precedents ORDER BY dist LIMIT %s",
                    (vector, 8),
                )
                vector_rows = list(cur.fetchall())
                cur.execute(
                    "SELECT id, case_no, defendant, charge, summary, cited, sentence_days, absurdity, attitude "
                    "FROM precedents WHERE MATCH(summary) AGAINST(%s) LIMIT %s",
                    (fts, 8),
                )
                text_rows = list(cur.fetchall())

        scores: dict[int, float] = {}
        rows: dict[int, dict[str, Any]] = {}
        channels: dict[int, set[str]] = {}
        for source, items in (("vector", vector_rows), ("fulltext", text_rows)):
            for rank, item in enumerate(items):
                key = item["id"]
                rows[key] = item
                scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank + 1)
                channels.setdefault(key, set()).add(source)
        ranked = sorted(rows.values(), key=lambda r: scores[r["id"]], reverse=True)[:k]
        for item in ranked:
            item["score"] = round(scores[item["id"]], 6)
            item["channels"] = sorted(channels[item["id"]])
        return ranked

    # ------------------------------------------------------------------ 判决
    def record_verdict(
        self,
        *,
        case_id: str,
        case_no: str,
        player_id: str,
        defendant: str,
        charge: str,
        summary: str,
        cited: list[str],
        sentence_days: int,
        absurdity: int,
        attitude: str,
    ) -> int:
        precedent_id = int(uuid.uuid4().int % (2**62))
        vector = self.embedder.embed_one(summary)
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO precedents (id, case_id, case_no, player_id, defendant, charge, summary, cited, "
                    "sentence_days, absurdity, attitude, created_at, embedding) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        precedent_id,
                        case_id,
                        case_no,
                        player_id,
                        defendant,
                        charge,
                        summary,
                        ",".join(cited),
                        sentence_days,
                        absurdity,
                        attitude,
                        _now(),
                        to_sql_vector(vector),
                    ),
                )
                cur.execute(
                    "UPDATE players SET convictions = convictions + 1, total_days = total_days + %s, "
                    "absurdity_sum = absurdity_sum + %s, last_seen = %s WHERE player_id = %s",
                    (sentence_days, absurdity, _now(), player_id),
                )
        return precedent_id

    # ------------------------------------------------------------------ 统计
    def docket_stats(self) -> dict[str, Any]:
        with self.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS n FROM precedents")
                precedents = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(*) AS n FROM players")
                players = cur.fetchone()["n"]
                cur.execute("SELECT COUNT(*) AS n FROM cases")
                cases = cur.fetchone()["n"]
                cur.execute("SELECT cited FROM precedents")
                counter: dict[str, int] = {}
                for row in cur.fetchall():
                    for code in (row["cited"] or "").split(","):
                        if code:
                            counter[code] = counter.get(code, 0) + 1
                top = []
                for code, count in sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:3]:
                    cur.execute("SELECT title FROM statutes WHERE code = %s", (code,))
                    title_row = cur.fetchone()
                    top.append({"code": code, "title": title_row["title"] if title_row else code, "n": count})
        return {"precedents": precedents, "players": players, "cases": cases, "top_cited": top}


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)
