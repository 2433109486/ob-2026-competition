"""ResearchPulse (研脉) HTTP API and static application shell."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, review
from .config import settings
from .embeddings import describe as embedding_info
from .memory import PowerContextError
from .memory import client as memory_client
from .retrieval import search as hybrid_search

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("yanmai")

APP_STARTED_AT = time.time()


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    yield


app = FastAPI(
    title="研脉 ResearchPulse",
    description="面向研究生的可追溯文献综述工作台：seekdb 混合检索 + PowerContext 研究记忆。",
    version="1.0.0",
    lifespan=lifespan,
)

if settings.allowed_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.mount("/assets", StaticFiles(directory=str(settings.web_root / "assets")), name="assets")


# --------------------------------------------------------------------------- models
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    tags: List[str] = Field(default_factory=list)
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    status: str = "all"
    source_type: str = "all"
    limit: int = Field(default=12, ge=1, le=30)
    remember: bool = False
    insight: str = ""


class ProfilePayload(BaseModel):
    name: str = ""
    field: str = ""
    stage: str = ""
    goal: str = ""
    methods: List[str] = Field(default_factory=list)
    preferences: List[str] = Field(default_factory=list)
    focus_tags: List[str] = Field(default_factory=list)
    question: str = ""


class PaperPatch(BaseModel):
    status: Optional[str] = None
    priority: Optional[int] = None
    read_minutes: Optional[int] = None
    review_problem: Optional[str] = None
    review_method: Optional[str] = None
    review_sample: Optional[str] = None
    review_finding: Optional[str] = None
    review_limitation: Optional[str] = None
    review_reuse: Optional[str] = None
    tags: Optional[List[str]] = None
    takeaway: Optional[str] = None


class NotePayload(BaseModel):
    paper_id: str
    note_type: str = "note"
    content: str = Field(..., min_length=1, max_length=6000)


class MemoryNotePayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)
    kind: str = "research_note"
    paper_id: str = ""


class ReviewRequest(BaseModel):
    paper_ids: List[str] = Field(..., min_length=1, max_length=12)
    question: str = ""
    remember: bool = True
    note: str = ""


# --------------------------------------------------------------------------- lifecycle
def startup() -> None:
    settings.ensure_runtime_dirs()
    logger.info("initialising seekdb schema at %s:%s", settings.seekdb_host, settings.seekdb_port)
    seeded = db.seed_database()
    logger.info("seekdb ready: %s", seeded)
    try:
        papers = db.fetch_papers(limit=100)
        result = memory_client.seed_demo_memories(papers)
        logger.info("PowerContext demo memory: %s", result)
    except Exception as error:  # noqa: BLE001 - app remains usable in degraded mode
        logger.warning("PowerContext unavailable at startup: %s", error)


# --------------------------------------------------------------------------- helpers
def _greeting() -> str:
    hour = datetime.now().hour
    if hour < 6:
        return "夜深了"
    if hour < 11:
        return "早上好"
    if hour < 14:
        return "中午好"
    if hour < 18:
        return "下午好"
    return "晚上好"


def _get_or_404(paper_id: str) -> Dict[str, Any]:
    paper = db.fetch_paper(paper_id)
    if not paper:
        raise HTTPException(status_code=404, detail=f"资料不存在：{paper_id}")
    return paper


def _paper_recommendation(papers: List[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
    focus = {str(tag).lower() for tag in (profile.get("focus_tags") or [])}
    scored = []
    for paper in papers:
        if paper.get("status") == "read":
            continue
        tags = {str(tag).lower() for tag in (paper.get("tags") or [])}
        overlap = len(tags & focus)
        score = overlap * 2 + (4 - int(paper.get("priority") or 3)) + (0.5 if paper.get("status") == "reading" else 0)
        why = []
        matched = sorted(tags & focus)
        if matched:
            why.append("命中画像：" + "、".join(matched[:3]))
        if paper.get("status") == "reading":
            why.append("正在精读")
        if not why:
            why.append("待读队列")
        scored.append({"paper": paper, "score": score, "why": why})
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:3]


def _memory_snapshot_safe() -> Dict[str, Any]:
    try:
        return memory_client.snapshot()
    except Exception as error:  # noqa: BLE001
        logger.warning("memory snapshot failed: %s", error)
        return {
            "available": False,
            "health": {"ok": False, "error": str(error)},
            "profile": {},
            "reading": {},
            "review": {},
            "entries": [],
            "scope_id": None,
        }


# --------------------------------------------------------------------------- pages
@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(settings.web_root / "index.html")


@app.get("/favicon.svg", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(settings.web_root / "assets" / "favicon.svg")


# --------------------------------------------------------------------------- health
@app.get("/api/health")
def health() -> Dict[str, Any]:
    db_info = db.db_health()
    memory_info = memory_client.health()
    counts: Dict[str, Any] = {}
    if db_info.get("ok"):
        try:
            counts = db.table_counts()
        except Exception as error:  # noqa: BLE001
            db_info = {"ok": False, "error": str(error)}
    return {
        "ok": bool(db_info.get("ok")),
        "app": "研脉 ResearchPulse",
        "version": "1.0.0",
        "uptime_seconds": int(time.time() - APP_STARTED_AT),
        "seekdb": db_info,
        "powercontext": memory_info,
        "embedding": embedding_info(),
        "counts": counts,
    }


@app.get("/api/bootstrap")
def bootstrap() -> Dict[str, Any]:
    db_info = db.db_health()
    memory = _memory_snapshot_safe()
    papers = db.fetch_papers(limit=100) if db_info.get("ok") else []
    counts = db.table_counts() if db_info.get("ok") else {}
    profile = memory.get("profile") or {}
    recommended = _paper_recommendation(papers, profile)
    reading_memory = memory.get("reading") or {}
    continue_reading = None
    for paper in papers:
        record = reading_memory.get(paper["paper_id"]) or {}
        if record.get("status") == "reading":
            continue_reading = {**paper, "memory": record}
            break
    if not continue_reading and recommended:
        continue_reading = recommended[0]["paper"]
    reading_counts = {
        "read": sum(1 for paper in papers if paper.get("status") == "read"),
        "reading": sum(1 for paper in papers if paper.get("status") == "reading"),
        "to_read": sum(1 for paper in papers if paper.get("status") == "to_read"),
    }
    usage = db.usage_stats(days=7) if db_info.get("ok") else {"searches": 0, "avg_latency_ms": 0, "top_queries": []}
    return {
        "greeting": _greeting(),
        "person": {"name": profile.get("name", "研究者"), "field": profile.get("field", ""), "stage": profile.get("stage", "")},
        "profile": profile,
        "memory_available": bool(memory.get("available")),
        "memory_health": memory.get("health"),
        "memory_count": len(memory.get("entries") or []),
        "scope_id": memory.get("scope_id"),
        "counts": {**counts, **reading_counts},
        "reading_counts": reading_counts,
        "continue_reading": continue_reading,
        "recommended": recommended,
        "tags": db.tag_counts() if db_info.get("ok") else [],
        "usage": usage,
        "recent_searches": db.recent_searches(6) if db_info.get("ok") else [],
        "recent_activity": db.recent_activity(8) if db_info.get("ok") else [],
        "timeline": memory_client.timeline(6) if memory.get("available") else [],
        "system": {
            "seekdb": db_info,
            "powercontext": memory.get("health"),
            "embedding": embedding_info(),
        },
    }


# --------------------------------------------------------------------------- papers
@app.get("/api/papers")
def list_papers(
    q: str = Query(default="", max_length=200),
    status: str = Query(default=""),
    tag: str = Query(default=""),
    limit: int = Query(default=50, ge=1, le=100),
) -> Dict[str, Any]:
    papers = db.fetch_papers(query=q, status=status, tag=tag, limit=limit)
    return {"items": papers, "total": len(papers)}


@app.get("/api/papers/{paper_id}")
def get_paper(paper_id: str) -> Dict[str, Any]:
    paper = _get_or_404(paper_id)
    memory = _memory_snapshot_safe()
    paper["reading_memory"] = (memory.get("reading") or {}).get(paper_id)
    return paper


@app.patch("/api/papers/{paper_id}")
def patch_paper(paper_id: str, payload: PaperPatch) -> Dict[str, Any]:
    _get_or_404(paper_id)
    fields = payload.dict(exclude_unset=True)
    takeaway = fields.pop("takeaway", "")
    if not fields and not takeaway:
        return _get_or_404(paper_id)
    updated = db.update_paper(paper_id, fields)
    if not updated:
        raise HTTPException(status_code=404, detail="资料不存在")
    memory_result = None
    if "status" in fields or takeaway:
        try:
            memory_result = memory_client.save_reading(updated, updated["status"], takeaway or "")
        except PowerContextError as error:
            logger.warning("reading memory write failed: %s", error)
    db.log_activity(
        "reading",
        f"更新《{updated['title'][:32]}》",
        {"status": updated.get("status"), "fields": list(fields.keys()), "memory_saved": bool(memory_result and memory_result.get("saved"))},
    )
    return {"paper": updated, "memory": memory_result}


@app.post("/api/notes")
def create_note(payload: NotePayload) -> Dict[str, Any]:
    paper = _get_or_404(payload.paper_id)
    note = db.add_note(payload.paper_id, payload.note_type, payload.content)
    memory_result = None
    try:
        memory_result = memory_client.save_note(payload.content, payload.note_type, payload.paper_id)
    except PowerContextError as error:
        logger.warning("note memory write failed: %s", error)
    db.log_activity(
        "note",
        f"记录《{paper['title'][:28]}》笔记",
        {"note_id": note["note_id"], "memory_saved": bool(memory_result and memory_result.get("saved"))},
    )
    return {"note": note, "memory": memory_result}


# --------------------------------------------------------------------------- search
@app.post("/api/search")
def search(payload: SearchRequest) -> Dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="请输入检索问题")
    result = hybrid_search(
        query,
        {
            "tags": payload.tags,
            "year_min": payload.year_min,
            "year_max": payload.year_max,
            "status": payload.status,
            "source_type": payload.source_type,
        },
        limit=payload.limit,
    )
    if payload.remember:
        try:
            saved = memory_client.save_search_decision(query, payload.insight or f"保留 {len(result['results'])} 条结果用于综述")
            result["memory_saved"] = saved
        except PowerContextError as error:
            result["memory_saved"] = {"saved": False, "error": str(error)}
    return result


@app.get("/api/searches")
def searches(limit: int = Query(default=10, ge=1, le=50)) -> Dict[str, Any]:
    return {"items": db.recent_searches(limit)}


# --------------------------------------------------------------------------- memory
@app.get("/api/memory")
def get_memory() -> Dict[str, Any]:
    snapshot = _memory_snapshot_safe()
    return {
        "available": snapshot.get("available"),
        "health": snapshot.get("health"),
        "scope_id": snapshot.get("scope_id"),
        "profile": snapshot.get("profile"),
        "reading": list((snapshot.get("reading") or {}).values()),
        "review": snapshot.get("review"),
        "timeline": memory_client.timeline(40) if snapshot.get("available") else [],
        "evidence_file": str(memory_client.evidence_file),
    }


@app.post("/api/memory/profile")
def save_profile(payload: ProfilePayload) -> Dict[str, Any]:
    try:
        saved = memory_client.save_profile(payload.dict())
    except PowerContextError as error:
        raise HTTPException(status_code=503, detail=f"PowerContext 未就绪：{error}") from error
    db.log_activity("profile", "更新研究画像", {"fields": list(payload.dict().keys())})
    return {"saved": saved, "profile": payload.dict()}


@app.post("/api/memory/note")
def save_memory_note(payload: MemoryNotePayload) -> Dict[str, Any]:
    try:
        saved = memory_client.save_note(payload.text, payload.kind, payload.paper_id)
    except PowerContextError as error:
        raise HTTPException(status_code=503, detail=f"PowerContext 未就绪：{error}") from error
    db.log_activity("memory", "写入研究记忆", {"kind": payload.kind})
    return {"saved": saved}


@app.get("/api/memory/search")
def search_memory(q: str = Query(..., min_length=1, max_length=300), limit: int = Query(default=6, ge=1, le=20)) -> Dict[str, Any]:
    try:
        return {"items": memory_client.search(q, limit=limit)}
    except PowerContextError as error:
        raise HTTPException(status_code=503, detail=f"PowerContext 未就绪：{error}") from error


# --------------------------------------------------------------------------- review
def _selected_papers(paper_ids: List[str]) -> List[Dict[str, Any]]:
    unique = list(dict.fromkeys(paper_ids))
    papers = []
    for paper_id in unique:
        paper = db.fetch_paper(paper_id)
        if paper:
            papers.append(paper)
    if not papers:
        raise HTTPException(status_code=400, detail="请选择至少一篇有效资料")
    return papers


@app.post("/api/review/matrix")
def review_matrix(payload: ReviewRequest) -> Dict[str, Any]:
    papers = _selected_papers(payload.paper_ids)
    profile = _memory_snapshot_safe().get("profile") or {}
    question = payload.question.strip() or profile.get("question") or "当前研究问题"
    matrix = review.build_matrix(papers, question)
    draft = review.build_draft(papers, question, profile)
    memory_result = None
    if payload.remember:
        try:
            memory_result = memory_client.save_review_board(
                [paper["paper_id"] for paper in papers], question, payload.note
            )
        except PowerContextError as error:
            logger.warning("review board memory write failed: %s", error)
    db.log_activity(
        "review",
        f"生成综述矩阵（{len(papers)} 篇）",
        {"coverage": matrix["coverage"], "question": question, "memory_saved": bool(memory_result and memory_result.get("saved"))},
    )
    return {"matrix": matrix, "draft": draft, "memory": memory_result}


@app.post("/api/review/export")
def export_review(payload: ReviewRequest) -> Response:
    papers = _selected_papers(payload.paper_ids)
    profile = _memory_snapshot_safe().get("profile") or {}
    question = payload.question.strip() or profile.get("question") or "当前研究问题"
    draft = review.build_draft(papers, question, profile)
    filename = "yanmai-review-draft.md"
    return Response(
        content=draft["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- stats
@app.get("/api/stats")
def stats() -> Dict[str, Any]:
    counts = db.table_counts()
    papers = db.fetch_papers(limit=100)
    return {
        "counts": counts,
        "reading": {
            "read": sum(1 for paper in papers if paper["status"] == "read"),
            "reading": sum(1 for paper in papers if paper["status"] == "reading"),
            "to_read": sum(1 for paper in papers if paper["status"] == "to_read"),
        },
        "tags": db.tag_counts(),
        "usage": db.usage_stats(days=7),
        "embedding": embedding_info(),
    }


@app.get("/api/activity")
def activity(limit: int = Query(default=20, ge=1, le=100)) -> Dict[str, Any]:
    return {"items": db.recent_activity(limit)}


# --------------------------------------------------------------------------- errors
@app.exception_handler(PowerContextError)
async def powercontext_error_handler(_: Request, exc: PowerContextError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": f"PowerContext 未就绪：{exc}"})


@app.exception_handler(pymysql.MySQLError)
async def mysql_error_handler(_: Request, exc: pymysql.MySQLError) -> JSONResponse:
    logger.exception("seekdb error")
    return JSONResponse(status_code=503, content={"detail": f"seekdb 查询失败：{exc}"})
