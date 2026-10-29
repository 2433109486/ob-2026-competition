"""PowerContext HTTP 客户端。

职责：保存并复用“叙事记忆”——法官对玩家的主观印象、上次庭审的金句、
玩家的惯用伎俩。与 seekdb 的分工是：

* seekdb = 客观数据（法条、判例、案卷、战绩）
* PowerContext = 主观记忆（跨会话、跨案件仍然生效的“人味”上下文）

所有调用都做了降级：PowerContext 不可用时庭审照常进行，
响应里 `pc.status` 会标记 degraded，方便评审核对。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from typing import Any

from .config import Settings
from .db import Store


class PowerContextClient:
    def __init__(self, settings: Settings, store: Store) -> None:
        self.settings = settings
        self.store = store

    # ------------------------------------------------------------------ HTTP
    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            self.settings.pc_base_url + path,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.settings.pc_timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    # ------------------------------------------------------------------ 能力
    def available(self) -> bool:
        if not self.settings.pc_enabled:
            return False
        try:
            with urllib.request.urlopen(self.settings.pc_base_url + "/health/live", timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False

    def ensure_scope(self, player_id: str, profile: dict[str, Any]) -> str | None:
        """每个玩家一个稳定 Scope；Scope ID 存回 seekdb 的 players 表。"""

        if not self.settings.pc_enabled:
            return None
        with self.store.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pc_scope_id FROM players WHERE player_id = %s", (player_id,))
                row = cur.fetchone()
        if row and row.get("pc_scope_id"):
            return row["pc_scope_id"]
        try:
            created = self._post(
                "/v1/scopes",
                {
                    "title": f"离谱法庭 · {player_id}",
                    "summary": f"玩家 {player_id} 的庭审记忆：{profile.get('title', '法庭新鲜人')}",
                    # 每个新玩家档案对应一个新 Scope；带随机后缀避免
                    # “重置数据后又被幂等键接回旧记忆”。
                    "idempotency_key": f"{self.settings.pc_scope_prefix}-{player_id}-{uuid.uuid4().hex[:8]}",
                },
            )
            scope_id = created.get("scope_id") or created.get("id")
            if scope_id:
                self.store.set_scope(player_id, scope_id)
            return scope_id
        except Exception:
            return None

    # ------------------------------------------------------------------ 读写
    def recall(self, scope_id: str | None, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if not scope_id or not self.settings.pc_enabled:
            return []
        try:
            data = self._post(
                "/v1/memory/search",
                {"scope_id": scope_id, "query": query, "limit": limit},
            )
        except Exception:
            return []
        memories: list[dict[str, Any]] = []
        for hit in data.get("hits", []):
            memory = hit.get("memory") or {}
            text = memory.get("text") or ""
            if not text:
                continue
            memories.append(
                {
                    "text": text,
                    "kind": memory.get("kind", "state"),
                    "score": round(float(hit.get("score") or 0), 6),
                    "matched_by": hit.get("matched_by", []),
                    "artifact_id": (memory.get("artifact") or {}).get("artifact_id"),
                }
            )
        return memories

    def remember(self, scope_id: str | None, text: str, kind: str = "state") -> dict[str, Any] | None:
        if not scope_id or not self.settings.pc_enabled:
            return None
        try:
            data = self._post(
                "/v1/memory/remember",
                {"scope_id": scope_id, "kind": kind, "text": text},
            )
        except Exception:
            return None
        records = data.get("records") or []
        return records[0] if records else None

    def capture(self, scope_id: str | None, source_id: str, content: str, metadata: dict[str, Any]) -> bool:
        """把本轮庭审全文写入 Source journal，保留可审计的原始证据。"""

        if not scope_id or not self.settings.pc_enabled:
            return False
        try:
            self._post(
                "/v1/sources/content",
                {
                    "scope_id": scope_id,
                    "source_id": source_id,
                    "content": content,
                    "metadata": metadata,
                },
            )
            return True
        except Exception:
            return False
