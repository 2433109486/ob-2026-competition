"""PowerContext client for research profile, reading progress, and decisions.

Only explicit, user-visible writes are sent to PowerContext. Each record is an
Atomic Memory whose ``text`` is a small JSON document; the UI can therefore show
what was remembered and which later screen reused it.
"""

from __future__ import annotations

import copy
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings, settings

KIND_LABELS = {
    "research_profile": "研究画像",
    "reading_progress": "阅读进度",
    "review_board": "综述决策",
    "research_note": "研究笔记",
    "search_decision": "检索决策",
}


class PowerContextError(RuntimeError):
    def __init__(self, message: str, *, status: Optional[int] = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_default_profile() -> Dict[str, Any]:
    path = settings.seed_dir / "profile.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "name": "研究者",
        "field": "教育技术学",
        "stage": "文献综述",
        "goal": "完成一篇可追溯的文献综述",
        "methods": ["实证研究"],
        "preferences": ["先看方法与局限"],
        "focus_tags": ["生成式AI", "编程教育"],
        "question": "生成式 AI 如何影响学习？",
        "updated_at": _now(),
    }


class PowerContextClient:
    def __init__(self, config: Settings = settings) -> None:
        self.settings = config
        self.base_url = config.powercontext_url
        self.scope_file = config.powercontext_scope_file
        self.scope_file.parent.mkdir(parents=True, exist_ok=True)
        self.evidence_file = config.runtime_dir / "powercontext_calls.jsonl"

    # ------------------------------------------------------------------ transport
    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        *,
        timeout: int = 10,
    ) -> Dict[str, Any]:
        url = self.base_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                result = json.loads(body) if body else {}
                self._record(path, response.status, payload, result, int((time.perf_counter() - started) * 1000))
                return result
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            self._record(path, error.code, payload, {"error": body[:500]}, int((time.perf_counter() - started) * 1000))
            raise PowerContextError(f"PowerContext {path} 返回 HTTP {error.code}", status=error.code, body=body)
        except (URLError, TimeoutError) as error:
            self._record(path, 0, payload, {"error": str(error)}, int((time.perf_counter() - started) * 1000))
            raise PowerContextError(f"无法连接 PowerContext：{error}") from error

    def _record(
        self,
        path: str,
        status: int,
        payload: Optional[Dict[str, Any]],
        result: Dict[str, Any],
        elapsed_ms: int,
    ) -> None:
        record = {
            "ts": _now(),
            "path": path,
            "status": status,
            "kind": (payload or {}).get("kind"),
            "scope_id": (payload or {}).get("scope_id"),
            "result_keys": sorted(result.keys()) if isinstance(result, dict) else [],
            "elapsed_ms": elapsed_ms,
        }
        with self.evidence_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ scope
    def health(self) -> Dict[str, Any]:
        if not self.settings.powercontext_enabled:
            return {"ok": False, "enabled": False, "error": "POWERCONTEXT_ENABLED=false"}
        started = time.perf_counter()
        try:
            with urlopen(self.base_url + "/health/live", timeout=3) as response:
                ok = response.status == 200
            return {
                "ok": ok,
                "enabled": True,
                "url": self.base_url,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "scope_id": self.scope_file.read_text(encoding="utf-8").strip() if self.scope_file.exists() else None,
            }
        except Exception as error:  # noqa: BLE001 - health is best effort
            return {"ok": False, "enabled": True, "url": self.base_url, "error": str(error)}

    def ensure_scope(self) -> str:
        if self.scope_file.exists():
            existing = self.scope_file.read_text(encoding="utf-8").strip()
            if existing and self._scope_alive(existing):
                return existing
        response = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": "研脉 · 研究上下文",
                "summary": "Research profile, reading progress and review decisions for ResearchPulse",
                "idempotency_key": self.settings.powercontext_scope_key,
            },
        )
        scope = response.get("scope_id") or response.get("id") or (response.get("scope") or {}).get("scope_id")
        if not scope:
            raise PowerContextError(f"创建 Scope 未返回 scope_id：{response}")
        self.scope_file.write_text(str(scope), encoding="utf-8")
        return str(scope)

    def _scope_alive(self, scope_id: str) -> bool:
        try:
            self._request("GET", f"/v1/scopes/{scope_id}")
            return True
        except PowerContextError as error:
            if error.status == 404:
                return False
            return False

    # ------------------------------------------------------------------ raw memory
    def list_entries(self, limit: int = 100) -> List[Dict[str, Any]]:
        scope = self.ensure_scope()
        response = self._request(
            "POST",
            "/v1/memory/entries/list",
            {"scope_id": scope, "limit": max(1, min(100, limit))},
        )
        entries = response.get("entries")
        if entries is None:
            entries = response.get("items") or []
        parsed: List[Dict[str, Any]] = []
        for entry in entries:
            item = dict(entry)
            try:
                item["data"] = json.loads(item.get("text") or "{}")
            except (TypeError, ValueError):
                item["data"] = {"text": item.get("text")}
            artifact = item.get("artifact") or {}
            item["artifact_id"] = artifact.get("artifact_id") or artifact.get("id")
            item["revision"] = artifact.get("revision")
            parsed.append(item)
        parsed.sort(key=lambda item: str(item.get("data", {}).get("saved_at") or ""), reverse=True)
        return parsed

    def remember(self, kind: str, data: Dict[str, Any], reason: str) -> Dict[str, Any]:
        scope = self.ensure_scope()
        payload = copy.deepcopy(data)
        payload.setdefault("saved_at", _now())
        text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > 8192:
            raise PowerContextError("这条记忆超过 PowerContext 的 8192 字节上限")
        response = self._request(
            "POST",
            "/v1/memory/remember",
            {
                "scope_id": scope,
                "kind": kind,
                "text": text,
                "reason": reason[:500],
            },
        )
        records = response.get("records") or []
        record = records[0] if records else {}
        artifact = record.get("artifact") or {}
        return {
            "saved": bool(records),
            "changed": response.get("changed"),
            "scope_id": scope,
            "kind": kind,
            "artifact_id": artifact.get("artifact_id") or artifact.get("id"),
            "revision": artifact.get("revision"),
            "data": payload,
        }

    def search(self, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        scope = self.ensure_scope()
        response = self._request(
            "POST",
            "/v1/memory/search",
            {"scope_id": scope, "query": query, "mode": "fts", "limit": limit},
            timeout=6,
        )
        hits = response.get("hits") or response.get("results") or []
        items = []
        for hit in hits:
            memory = hit.get("memory") or {}
            kind = hit.get("kind") or memory.get("kind") or "research_note"
            raw = memory.get("text") or hit.get("text") or ""
            try:
                data = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                data = {"text": raw}
            items.append(
                {
                    "kind": kind,
                    "text": raw,
                    "summary": _summarize_memory(kind, data),
                    "score": hit.get("score"),
                    "matched_by": hit.get("matched_by"),
                }
            )
        return items

    def prepare(self, query: str, max_bytes: int = 3000) -> Dict[str, Any]:
        scope = self.ensure_scope()
        return self._request(
            "POST",
            "/v1/context/prepare",
            {"scope_id": scope, "query": query, "max_bytes": max_bytes},
            timeout=8,
        )

    # ------------------------------------------------------------------ domain helpers
    def snapshot(self) -> Dict[str, Any]:
        health = self.health()
        if not health.get("ok"):
            return {
                "available": False,
                "health": health,
                "profile": load_default_profile(),
                "reading": {},
                "review": {},
                "entries": [],
                "scope_id": None,
            }
        try:
            entries = self.list_entries()
        except PowerContextError as error:
            return {
                "available": False,
                "health": {**health, "error": str(error)},
                "profile": load_default_profile(),
                "reading": {},
                "review": {},
                "entries": [],
                "scope_id": None,
            }
        profile = self.latest_profile(entries)
        reading: Dict[str, Dict[str, Any]] = {}
        review: Dict[str, Any] = {}
        for entry in entries:
            data = entry.get("data") or {}
            kind = entry.get("kind")
            if kind == "reading_progress" and data.get("paper_id"):
                key = str(data["paper_id"])
                if key not in reading:
                    reading[key] = {**data, "memory": self._memory_ref(entry)}
            elif kind == "review_board" and not review:
                review = {**data, "memory": self._memory_ref(entry)}
        return {
            "available": True,
            "health": health,
            "profile": profile,
            "reading": reading,
            "review": review,
            "entries": entries,
            "scope_id": health.get("scope_id"),
        }

    def latest_profile(self, entries: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        entries = entries if entries is not None else self.list_entries()
        for entry in entries:
            if entry.get("kind") == "research_profile" and isinstance(entry.get("data"), dict):
                profile = dict(entry["data"])
                profile.setdefault("name", "研究者")
                return profile
        return load_default_profile()

    def save_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {
            "name": str(profile.get("name") or "研究者")[:40],
            "field": str(profile.get("field") or "")[:120],
            "stage": str(profile.get("stage") or "")[:80],
            "goal": str(profile.get("goal") or "")[:500],
            "methods": _string_list(profile.get("methods")),
            "preferences": _string_list(profile.get("preferences")),
            "focus_tags": _string_list(profile.get("focus_tags"))[:12],
            "question": str(profile.get("question") or "")[:500],
            "updated_at": _now(),
        }
        return self.remember("research_profile", cleaned, "用户更新研究画像")

    def save_reading(self, paper: Dict[str, Any], status: str, takeaway: str = "") -> Dict[str, Any]:
        data = {
            "paper_id": paper["paper_id"],
            "title": paper["title"],
            "status": status,
            "takeaway": takeaway[:800],
            "tags": paper.get("tags", [])[:6] if isinstance(paper.get("tags"), list) else [],
            "updated_at": _now(),
        }
        return self.remember("reading_progress", data, f"更新《{paper['title'][:60]}》的阅读进度")

    def save_review_board(self, paper_ids: List[str], question: str, note: str = "") -> Dict[str, Any]:
        data = {
            "paper_ids": paper_ids[:12],
            "question": question[:500],
            "note": note[:800],
            "updated_at": _now(),
        }
        return self.remember("review_board", data, "保存综述矩阵选择")

    def save_note(self, text: str, kind: str = "research_note", paper_id: str = "") -> Dict[str, Any]:
        data = {
            "text": text[:2000],
            "paper_id": paper_id,
            "note_kind": kind,
            "updated_at": _now(),
        }
        return self.remember("research_note", data, "保存研究笔记")

    def save_search_decision(self, query: str, insight: str) -> Dict[str, Any]:
        data = {"query": query[:500], "insight": insight[:1000], "updated_at": _now()}
        return self.remember("search_decision", data, "保存检索决策")

    def timeline(self, limit: int = 24) -> List[Dict[str, Any]]:
        try:
            entries = self.list_entries()
        except PowerContextError:
            return []
        items: List[Dict[str, Any]] = []
        for entry in entries[:limit]:
            data = entry.get("data") or {}
            kind = entry.get("kind") or "research_note"
            items.append(
                {
                    "id": entry.get("artifact_id"),
                    "kind": kind,
                    "label": KIND_LABELS.get(kind, kind),
                    "text": _summarize_memory(kind, data),
                    "data": data,
                    "saved_at": data.get("saved_at") or data.get("updated_at"),
                    "artifact_id": entry.get("artifact_id"),
                    "revision": entry.get("revision"),
                    "state": entry.get("state"),
                }
            )
        return items

    def context_for_search(self, query: str) -> Dict[str, Any]:
        snapshot = self.snapshot()
        profile = snapshot["profile"]
        focus = profile.get("focus_tags") or []
        methods = profile.get("methods") or []
        reading = snapshot.get("reading") or {}
        in_progress = [item for item in reading.values() if item.get("status") == "reading"]
        related: List[Dict[str, Any]] = []
        if snapshot.get("available"):
            try:
                related = self.search(query, limit=4)
            except PowerContextError:
                related = []
        boosts = sorted({str(tag) for tag in focus if tag})[:8]
        return {
            **snapshot,
            "focus_tags": boosts,
            "methods": methods,
            "in_progress": in_progress[:3],
            "related": related,
            "memory_summary": _profile_sentence(profile),
        }

    def seed_demo_memories(self, papers: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        snapshot = self.snapshot()
        if not snapshot.get("available"):
            return {"seeded": False, "reason": "PowerContext 不可用"}
        if any(entry.get("kind") == "research_profile" for entry in snapshot.get("entries", [])):
            return {"seeded": False, "reason": "已有研究画像，跳过初始化"}
        profile = load_default_profile()
        result = self.save_profile(profile)
        by_id = {paper["paper_id"]: paper for paper in papers}
        seeded = 0
        for paper_id, status, takeaway in [
            ("kazemitabaar2023", "read", "延迟后测必须保留；先前经验可能是调节变量。"),
            ("bastani2025", "read", "AI 提升练习表现，不等于提升学习；护栏设计是核心。"),
            ("prather2023", "reading", "用工作组报告的风险清单组织综述背景。"),
            ("groupnote2026", "read", "主终点坚持用延迟迁移，不用课堂练习成绩替代。"),
        ]:
            paper = by_id.get(paper_id)
            if paper:
                self.save_reading(paper, status, takeaway)
                seeded += 1
        self.save_review_board(
            ["kazemitabaar2023", "bastani2025", "prather2023", "denny2024"],
            profile["question"],
            "先搭建“效果证据—工具设计—评估方式”三列骨架。",
        )
        return {"seeded": True, "profile": result, "reading": seeded}

    def _memory_ref(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "artifact_id": entry.get("artifact_id"),
            "revision": entry.get("revision"),
            "saved_at": (entry.get("data") or {}).get("saved_at"),
        }


def _string_list(value: Any) -> List[str]:
    if isinstance(value, str):
        return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _profile_sentence(profile: Dict[str, Any]) -> str:
    field = profile.get("field") or "你的领域"
    stage = profile.get("stage") or "研究"
    tags = "、".join((profile.get("focus_tags") or [])[:3])
    return f"{field} · {stage}" + (f"；当前关注 {tags}" if tags else "")


def _summarize_memory(kind: str, data: Dict[str, Any]) -> str:
    if kind == "research_profile":
        return f"{data.get('field', '')} · {data.get('stage', '')}：{data.get('goal', '')}"
    if kind == "reading_progress":
        return f"{data.get('title', data.get('paper_id', ''))} · {data.get('status', '')} · {data.get('takeaway', '')}"
    if kind == "review_board":
        return f"综述矩阵：{len(data.get('paper_ids') or [])} 篇文献 · {data.get('question', '')}"
    if kind == "search_decision":
        return f"检索「{data.get('query', '')}」：{data.get('insight', '')}"
    return str(data.get("text") or data.get("note") or "")[:240]


client = PowerContextClient()
