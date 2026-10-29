"""PowerContext HTTP state store.

Task checkpoints are written as explicit Atomic Memory records (kind
``sdd_task_state``) and read back by a later process. The module never embeds a
credential and records only request metadata in its local evidence log.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings


class PowerContextError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(slots=True)
class Checkpoint:
    task_id: str
    seq: int
    completed: list[str]
    todos: list[str]
    verifications: list[dict[str, Any]]
    context_run_id: str | None = None
    code_version: str | None = None
    extra: dict[str, Any] | None = None

    def to_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "task_id": self.task_id,
            "seq": self.seq,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "completed": self.completed,
            "todos": self.todos,
            "verifications": self.verifications,
        }
        if self.context_run_id:
            state["context_run_id"] = self.context_run_id
        if self.code_version:
            state["code_version"] = self.code_version
        if self.extra:
            state.update(self.extra)
        return state


class PowerContextStateStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.powercontext_url
        self.scope_file = settings.powercontext_scope_file
        self.state_kind = settings.powercontext_state_kind
        self.scope_key = settings.powercontext_scope_key
        self.records_path = settings.demo_dir / "powercontext_records.jsonl"
        self.records_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ HTTP
    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        started = time.perf_counter()
        try:
            with urlopen(request, timeout=20) as response:
                body = response.read().decode("utf-8")
                result = json.loads(body) if body else {}
                self._record(path, response.status, payload, result)
                return result
        except HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            self._record(path, error.code, payload, {"error": body[:1000]})
            raise PowerContextError(f"PowerContext {path} returned HTTP {error.code}", status=error.code, body=body)
        except URLError as error:
            raise PowerContextError(f"PowerContext is unreachable at {self.base_url}: {error.reason}") from error
        finally:
            _ = int((time.perf_counter() - started) * 1000)

    def _record(self, path: str, status: int, payload: dict[str, Any] | None, result: dict[str, Any]) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "path": path,
            "status": status,
            "request_keys": sorted(payload.keys()) if payload else [],
            "scope_id_present": bool(payload and payload.get("scope_id")),
            "result_keys": sorted(result.keys()) if isinstance(result, dict) else [],
        }
        with self.records_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    def health(self) -> bool:
        try:
            with urlopen(f"{self.base_url}/health/live", timeout=3) as response:
                return response.status == 200
        except (HTTPError, URLError, TimeoutError):
            return False

    # ------------------------------------------------------------------ scope
    def ensure_scope(self) -> str:
        if self.scope_file.exists():
            scope_id = self.scope_file.read_text(encoding="utf-8").strip()
            if scope_id and self._scope_alive(scope_id):
                return scope_id
        response = self._request(
            "POST",
            "/v1/scopes",
            {
                "title": "BookNest SDD",
                "summary": "Engineering context for the BookNest price-filter task",
                "idempotency_key": self.scope_key,
            },
        )
        scope_id = (
            response.get("scope_id")
            or response.get("id")
            or (response.get("scope") or {}).get("scope_id")
            or (response.get("scope") or {}).get("id")
        )
        if not scope_id:
            raise PowerContextError(f"PowerContext scope creation returned no scope_id: {response}")
        self.scope_file.parent.mkdir(parents=True, exist_ok=True)
        self.scope_file.write_text(str(scope_id), encoding="utf-8")
        return str(scope_id)

    def _scope_alive(self, scope_id: str) -> bool:
        try:
            self._request("GET", f"/v1/scopes/{scope_id}")
            return True
        except PowerContextError as error:
            if error.status == 404:
                return False
            raise

    # ------------------------------------------------------------------ state
    def save_checkpoint(self, checkpoint: Checkpoint) -> dict[str, Any]:
        scope_id = self.ensure_scope()
        state = checkpoint.to_state()
        text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
        if len(text.encode("utf-8")) > 8192:
            raise ValueError("PowerContext memory text exceeds 8192 UTF-8 bytes")
        response = self._request(
            "POST",
            "/v1/memory/remember",
            {
                "scope_id": scope_id,
                "kind": self.state_kind,
                "text": text,
                "reason": f"SDD task checkpoint {checkpoint.task_id} seq {checkpoint.seq}",
            },
        )
        records = response.get("records") or []
        record = records[0] if records else {}
        artifact = record.get("artifact") or {}
        return {
            "scope_id": scope_id,
            "state": state,
            "artifact": artifact,
            "artifact_id": artifact.get("artifact_id") or artifact.get("id"),
            "revision": artifact.get("revision"),
            "state_version": record.get("state_version"),
            "changed": response.get("changed"),
        }

    def list_entries(self) -> list[dict[str, Any]]:
        scope_id = self.ensure_scope()
        response = self._request(
            "POST",
            "/v1/memory/entries/list",
            {"scope_id": scope_id, "limit": 100},
        )
        entries = response.get("entries") or []
        return [entry for entry in entries if isinstance(entry, dict)]

    def load_latest(self, task_id: str) -> dict[str, Any] | None:
        latest: tuple[int, dict[str, Any], dict[str, Any]] | None = None
        for entry in self.list_entries():
            if entry.get("kind") != self.state_kind:
                continue
            try:
                state = json.loads(entry.get("text") or "{}")
            except json.JSONDecodeError:
                continue
            if state.get("task_id") != task_id:
                continue
            seq = int(state.get("seq") or 0)
            if latest is None or seq > latest[0]:
                latest = (seq, state, entry)
        if latest is None:
            return None
        seq, state, entry = latest
        artifact = entry.get("artifact") or {}
        return {
            "source": "powercontext",
            "status": "loaded",
            "task_id": task_id,
            "seq": seq,
            "completed": state.get("completed") or [],
            "todos": state.get("todos") or [],
            "verifications": state.get("verifications") or [],
            "updated_at": state.get("updated_at"),
            "state": state,
            "powercontext": {
                "scope_id": self.scope_file.read_text(encoding="utf-8").strip() if self.scope_file.exists() else None,
                "artifact_id": artifact.get("artifact_id") or artifact.get("id"),
                "revision": artifact.get("revision"),
                "state": entry.get("state"),
                "state_version": entry.get("state_version"),
            },
        }

    def save_source(self, source_id: str, content: str, metadata: dict[str, Any]) -> dict[str, Any]:
        scope_id = self.ensure_scope()
        response = self._request(
            "POST",
            "/v1/sources/content",
            {
                "scope_id": scope_id,
                "source_id": source_id,
                "content": content[:12000],
                "metadata": metadata,
            },
        )
        return response

    def prepare(self, query: str, *, max_bytes: int = 4000) -> dict[str, Any]:
        scope_id = self.ensure_scope()
        return self._request(
            "POST",
            "/v1/context/prepare",
            {"scope_id": scope_id, "query": query, "max_bytes": max_bytes},
        )
