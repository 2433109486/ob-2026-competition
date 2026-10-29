"""FastAPI 服务：Dify 通过 HTTP Request 节点调用。

端点：
- GET  /api/v1/health                 健康检查（含 seekdb / PowerContext / embedding 配置）
- POST /api/v1/court/intake           立案：检索法条、判例与跨会话记忆
- POST /api/v1/court/commit           结案：校验引用、量刑、写判例与记忆
- GET  /api/v1/court/dossier/{id}     玩家档案
- GET  /api/v1/court/stats            法庭统计
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

from .config import settings
from .court import commit as commit_case
from .court import intake as intake_case
from .db import Store
from .embeddings import Embedder
from .powercontext import PowerContextClient
from .render import render_answer

logger = logging.getLogger("absurd-court")

embedder = Embedder(
    settings.embedding_backend,
    settings.embedding_dim,
    settings.embedding_base_url,
    settings.embedding_api_key,
    settings.embedding_model,
)
store = Store(settings, embedder)
pc = PowerContextClient(settings, store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.environ.get("COURT_AUTO_INIT", "1") == "1":
        attempts = int(os.environ.get("COURT_INIT_RETRIES", "30"))
        delay = float(os.environ.get("COURT_INIT_DELAY", "2"))
        for attempt in range(1, attempts + 1):
            try:
                store.init_schema()
                count = store.seed_statutes()
                logger.info("seekdb ready, %s statutes", count)
                break
            except Exception as exc:  # pragma: no cover - 启动期可见即可
                if attempt == attempts:
                    logger.exception("seekdb init failed after %s attempts: %s", attempts, exc)
                else:
                    logger.warning("seekdb not ready (%s/%s): %s", attempt, attempts, exc)
                    time.sleep(delay)
    yield


app = FastAPI(title="宇宙离谱法庭", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class IntakeRequest(BaseModel):
    player_id: str = Field(default="", max_length=64)
    user_id: str = Field(default="", max_length=64)
    conversation_id: str = Field(default="default", max_length=128)
    message: str = Field(min_length=1, max_length=2000)


class CommitRequest(BaseModel):
    player_id: str = Field(default="", max_length=64)
    user_id: str = Field(default="", max_length=64)
    conversation_id: str = Field(default="default", max_length=128)
    case_id: str = Field(min_length=1, max_length=32)
    message: str = Field(default="", max_length=2000)
    judge: dict[str, Any] | str = Field(default_factory=dict)
    fallback_statutes: list[dict[str, Any]] | str | None = None

    @field_validator("judge")
    @classmethod
    def _parse_judge(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text or "{}")
        return value or {}

    @field_validator("fallback_statutes")
    @classmethod
    def _parse_fallback(cls, value: Any) -> Any:
        if isinstance(value, str):
            return json.loads(value) if value.strip() else []
        return value


@app.get("/api/v1/health")
def health() -> dict[str, Any]:
    status: dict[str, Any] = {"ok": True, "config": settings.masked()}
    try:
        stats = store.docket_stats()
        status["seekdb"] = {"ok": True, **stats}
    except Exception as exc:
        status["seekdb"] = {"ok": False, "error": str(exc)}
        status["ok"] = False
    status["powercontext"] = {"ok": pc.available(), "url": settings.pc_base_url if settings.pc_enabled else None}
    return status


def _player(payload: IntakeRequest | CommitRequest) -> str:
    """优先使用玩家自填 ID，其次用 Dify 的系统用户 ID，最后退回 guest。"""

    return (payload.player_id or "").strip() or (payload.user_id or "").strip() or "guest"


@app.post("/api/v1/court/intake")
def intake(payload: IntakeRequest) -> dict[str, Any]:
    try:
        return intake_case(
            store,
            pc,
            settings,
            player_id=_player(payload),
            conversation_id=payload.conversation_id or "default",
            message=payload.message.strip(),
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"intake failed: {exc}") from exc


@app.post("/api/v1/court/commit")
def commit(payload: CommitRequest) -> dict[str, Any]:
    try:
        result = commit_case(
            store,
            pc,
            settings,
            player_id=_player(payload),
            conversation_id=payload.conversation_id or "default",
            case_id=payload.case_id,
            message=payload.message,
            judge=payload.judge,
            fallback_statutes=payload.fallback_statutes or [],
        )
        result["answer_md"] = render_answer(result)
        return result
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"commit failed: {exc}") from exc


@app.get("/api/v1/court/dossier/{player_id}")
def dossier(player_id: str) -> dict[str, Any]:
    return {"ok": True, "player": store.profile(player_id)}


@app.get("/api/v1/court/stats")
def stats() -> dict[str, Any]:
    return {"ok": True, **store.docket_stats()}
