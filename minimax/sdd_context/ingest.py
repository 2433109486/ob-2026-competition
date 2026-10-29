"""Ingest specifications, code symbols, and tests into seekdb.

The corpus is parsed from the working tree. Specifications use YAML-like
frontmatter, code is indexed per top-level symbol with ``ast``, and tests carry
their spec links in comments. Re-ingestion is idempotent and keeps a version
history so an updated specification replaces the previous head.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import Settings
from .db import QueryTrace, connect, ensure_schema, traced_cursor, vector_literal
from .embeddings import embed_texts

_SPEC_SECTION = re.compile(r"^##\s+([A-Z]+-\d+)\s+(.+)$", re.MULTILINE)
_SPEC_COMMENT = re.compile(r"#\s*spec:\s*([A-Za-z0-9_.-]+)")
_KIND_COMMENT = re.compile(r"#\s*kind:\s*([A-Za-z0-9_-]+)")
_WORD = re.compile(r"[A-Za-z0-9_]+")
_CJK = re.compile(r"[\u4e00-\u9fff]")


@dataclass(slots=True)
class Doc:
    doc_key: str
    doc_type: str
    source_path: str
    title: str
    version: int
    status: str
    tags: list[str]
    metadata: dict[str, Any]
    content: str
    search_text: str
    content_hash: str = ""
    embedding: list[float] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.content_hash:
            self.content_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class IngestSummary:
    run_id: str
    counts: dict[str, int]
    specs: list[str]
    code_symbols: list[str]
    tests: list[str]
    embedding_provider: str
    embedding_tokens: int
    versions: int
    links: int


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _parse_value(value: str) -> Any:
    value = _strip_quotes(value)
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(part) for part in inner.split(",") if part.strip()]
    if value.lower() in {"", "null", "none", "~"}:
        return ""
    return value


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    block = text[3:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    meta: dict[str, Any] = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = _parse_value(value)
    return meta, body


def split_requirements(body: str) -> list[dict[str, str]]:
    matches = list(_SPEC_SECTION.finditer(body))
    requirements: list[dict[str, str]] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[start:end].strip()
        requirements.append(
            {
                "id": match.group(1),
                "title": match.group(2).strip(),
                "text": section,
            }
        )
    return requirements


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = [token for token in _WORD.findall(lowered) if len(token) > 1]
    chars = _CJK.findall(lowered)
    tokens.extend(chars)
    tokens.extend(a + b for a, b in zip(chars, chars[1:]))
    return tokens


def _tags_for(text: str, limit: int = 18) -> list[str]:
    seen: list[str] = []
    for token in _tokens(text):
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _module_name(path: Path, root: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    return relative.with_suffix("").as_posix().replace("/", ".")


def _spec_docs(settings: Settings) -> tuple[list[Doc], list[str]]:
    docs: list[Doc] = []
    warnings: list[str] = []
    if not settings.specs_dir.exists():
        return docs, [f"specs directory missing: {settings.specs_dir}"]
    for path in sorted(settings.specs_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        spec_id = str(meta.get("id") or path.stem).strip()
        kind = str(meta.get("kind") or "spec").strip().lower()
        doc_type = kind if kind in {"spec", "decision"} else "spec"
        declared_version = int(str(meta.get("version") or "1"))
        status = str(meta.get("status") or "active").strip().lower()
        tags = meta.get("tags") or []
        applies_to = meta.get("applies_to") or []
        if isinstance(tags, str):
            tags = [tags]
        if isinstance(applies_to, str):
            applies_to = [applies_to]
        title = str(meta.get("title") or spec_id)
        requirements = split_requirements(body)
        search_text = " ".join(
            [
                spec_id,
                title,
                " ".join(str(tag) for tag in tags),
                " ".join(str(symbol) for symbol in applies_to),
                body,
            ]
        )
        docs.append(
            Doc(
                doc_key=f"{doc_type}:{spec_id}",
                doc_type=doc_type,
                source_path=_relative(path, settings.project_root),
                title=f"{spec_id} {title}",
                version=declared_version,
                status="active" if status == "active" else "retired",
                tags=[str(tag) for tag in tags],
                metadata={
                    "id": spec_id,
                    "kind": kind,
                    "title": title,
                    "applies_to": [str(symbol) for symbol in applies_to],
                    "supersedes": str(meta.get("supersedes") or ""),
                    "declared_version": declared_version,
                    "requirements": requirements,
                },
                content=body.strip(),
                search_text=search_text,
            )
        )
        if not requirements:
            warnings.append(f"no requirement sections found in {path.name}")
    return docs, warnings


def _code_docs(settings: Settings) -> tuple[list[Doc], list[str]]:
    docs: list[Doc] = []
    warnings: list[str] = []
    for base in settings.code_dirs:
        if not base.exists():
            warnings.append(f"code directory missing: {base}")
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            source = path.read_text(encoding="utf-8")
            try:
                tree = ast.parse(source)
            except SyntaxError as error:
                warnings.append(f"cannot parse {path}: {error}")
                continue
            lines = source.splitlines()
            module = _module_name(path, settings.project_root)
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                end_line = getattr(node, "end_lineno", None) or node.lineno
                segment = "\n".join(lines[node.lineno - 1 : end_line])
                docstring = ast.get_docstring(node) or ""
                qualname = node.name
                symbol = f"{module}.{qualname}"
                signature = lines[node.lineno - 1].strip()
                tags = _tags_for(f"{symbol} {path.name} {docstring} {segment[:1200]}")
                docs.append(
                    Doc(
                        doc_key=f"code:{_relative(path, settings.project_root)}#{qualname}",
                        doc_type="code",
                        source_path=_relative(path, settings.project_root),
                        title=symbol,
                        version=1,
                        status="active",
                        tags=tags,
                        metadata={
                            "symbol": symbol,
                            "qualname": qualname,
                            "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                            "module": module,
                            "start_line": node.lineno,
                            "end_line": end_line,
                            "signature": signature,
                            "docstring": docstring,
                        },
                        content=segment,
                        search_text=f"{symbol} {path.name} {docstring} {segment}",
                    )
                )
    return docs, warnings


def _test_docs(settings: Settings) -> tuple[list[Doc], list[str]]:
    docs: list[Doc] = []
    warnings: list[str] = []
    if not settings.tests_dir.exists():
        return docs, [f"tests directory missing: {settings.tests_dir}"]
    for path in sorted(settings.tests_dir.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError as error:
            warnings.append(f"cannot parse {path}: {error}")
            continue
        lines = source.splitlines()
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test_"):
                continue
            end_line = getattr(node, "end_lineno", None) or node.lineno
            segment = "\n".join(lines[node.lineno - 1 : end_line])
            comment_lines: list[str] = []
            for previous in reversed(lines[: node.lineno - 1]):
                stripped = previous.strip()
                if stripped.startswith("#"):
                    comment_lines.append(previous)
                elif stripped == "":
                    if comment_lines:
                        break
                else:
                    break
            comment_block = "\n".join(reversed(comment_lines))
            spec_ids = list(dict.fromkeys(_SPEC_COMMENT.findall(comment_block)))
            kinds = _KIND_COMMENT.findall(comment_block)
            kind = kinds[0].lower() if kinds else ("target" if spec_ids else "regression")
            tags = ["test", kind] + [spec.lower() for spec in spec_ids]
            tags += _tags_for(path.name, limit=4)
            relpath = _relative(path, settings.project_root)
            docs.append(
                Doc(
                    doc_key=f"test:{relpath}::{node.name}",
                    doc_type="test",
                    source_path=relpath,
                    title=node.name,
                    version=1,
                    status="active",
                    tags=list(dict.fromkeys(tags)),
                    metadata={
                        "test_name": node.name,
                        "kind": kind,
                        "spec_ids": spec_ids,
                        "start_line": node.lineno,
                        "end_line": end_line,
                    },
                    content=segment,
                    search_text=f"{node.name} {kind} {' '.join(spec_ids)} {segment}",
                )
            )
    return docs, warnings


def _existing(conn, doc_key: str) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT version, content_hash, status, doc_type FROM documents WHERE doc_key=%s",
            (doc_key,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {"version": int(row[0]), "content_hash": str(row[1]), "status": str(row[2]), "doc_type": str(row[3])}


def _upsert_documents(conn, docs: Sequence[Doc], run_id: str) -> int:
    changed = 0
    with conn.cursor() as cur:
        for doc in docs:
            previous = _existing(conn, doc.doc_key)
            is_changed = previous is None or previous["content_hash"] != doc.content_hash
            if is_changed:
                changed += 1
                next_version = doc.version
                if previous and doc.doc_type in {"code", "test"}:
                    next_version = previous["version"] + 1
                doc.version = next_version
                cur.execute(
                    "UPDATE document_versions SET status='superseded' WHERE doc_key=%s AND status='active'",
                    (doc.doc_key,),
                )
                cur.execute(
                    """
                    INSERT INTO document_versions
                      (doc_key, version, status, source_path, content, content_hash, tags, metadata_json, ingested_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    """,
                    (
                        doc.doc_key,
                        doc.version,
                        "active" if doc.status == "active" else "retired",
                        doc.source_path,
                        doc.content,
                        doc.content_hash,
                        json.dumps(doc.tags, ensure_ascii=False),
                        json.dumps(doc.metadata, ensure_ascii=False),
                    ),
                )
            cur.execute(
                """
                INSERT INTO documents
                  (doc_key, doc_type, source_path, title, version, status, tags, metadata_json,
                   content, search_text, content_hash, embedding, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                  doc_type=VALUES(doc_type), source_path=VALUES(source_path), title=VALUES(title),
                  version=VALUES(version), status=VALUES(status), tags=VALUES(tags),
                  metadata_json=VALUES(metadata_json), content=VALUES(content),
                  search_text=VALUES(search_text), content_hash=VALUES(content_hash),
                  embedding=VALUES(embedding), updated_at=NOW()
                """,
                (
                    doc.doc_key,
                    doc.doc_type,
                    doc.source_path,
                    doc.title,
                    doc.version,
                    doc.status,
                    ",".join(doc.tags),
                    json.dumps(doc.metadata, ensure_ascii=False),
                    doc.content,
                    doc.search_text,
                    doc.content_hash,
                    vector_literal(doc.embedding),
                ),
            )
    return changed


def _retire_missing(conn, seen: set[str]) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT doc_key FROM documents WHERE status='active'")
        active = [str(row[0]) for row in cur.fetchall()]
        missing = [key for key in active if key not in seen]
        for key in missing:
            cur.execute("UPDATE documents SET status='retired', updated_at=NOW() WHERE doc_key=%s", (key,))
    return len(missing)


def _rebuild_links(conn, docs: Sequence[Doc]) -> int:
    by_symbol = {doc.metadata.get("symbol"): doc.doc_key for doc in docs if doc.doc_type == "code"}
    by_id = {doc.metadata.get("id"): doc.doc_key for doc in docs if doc.doc_type in {"spec", "decision"}}
    links: set[tuple[str, str, str, float]] = set()

    for doc in docs:
        if doc.doc_type not in {"spec", "decision"}:
            continue
        for symbol in doc.metadata.get("applies_to", []):
            target = by_symbol.get(symbol)
            if target is None:
                suffix = "." + str(symbol).split(".")[-1]
                target = next((key for symbol_key, key in by_symbol.items() if str(symbol_key).endswith(suffix)), None)
            if target:
                links.add((doc.doc_key, target, "applies_to", 1.0))
                links.add((target, doc.doc_key, "governed_by", 1.0))

    for doc in docs:
        if doc.doc_type != "test":
            continue
        for spec_id in doc.metadata.get("spec_ids", []):
            spec_key = by_id.get(spec_id)
            if spec_key:
                links.add((spec_key, doc.doc_key, "verified_by", 1.0))
                links.add((doc.doc_key, spec_key, "verifies", 1.0))
        for symbol, code_key in by_symbol.items():
            short = str(symbol).split(".")[-1]
            if short and short in doc.content:
                links.add((code_key, doc.doc_key, "covered_by", 0.5))

    with conn.cursor() as cur:
        cur.execute("DELETE FROM links")
        if links:
            cur.executemany(
                "INSERT INTO links (from_key, to_key, relation, weight) VALUES (%s, %s, %s, %s)",
                sorted(links),
            )
    return len(links)


def ingest(settings: Settings, *, reset: bool = False, verbose: bool = True) -> IngestSummary:
    settings.ensure_runtime_dirs()
    run_id = f"ingest-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    counts = ensure_schema(settings, reset=reset)
    spec_docs, spec_warnings = _spec_docs(settings)
    code_docs, code_warnings = _code_docs(settings)
    test_docs, test_warnings = _test_docs(settings)
    docs = spec_docs + code_docs + test_docs
    if not docs:
        raise RuntimeError("nothing to ingest: no specs, code, or tests were found")

    texts = [doc.search_text[:6000] for doc in docs]
    batch = embed_texts(settings, texts, purpose="db")
    for doc, vector in zip(docs, batch.vectors):
        doc.embedding = vector

    conn = connect(settings, database=settings.seekdb_database)
    try:
        changed = _upsert_documents(conn, docs, run_id)
        retired = _retire_missing(conn, {doc.doc_key for doc in docs})
        link_count = _rebuild_links(conn, docs)
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM document_versions")
            versions = int(cur.fetchone()[0])
            cur.execute(
                """
                INSERT INTO ingest_runs (run_id, started_at, finished_at, doc_count, status, notes)
                VALUES (%s, NOW(), NOW(), %s, %s, %s)
                """,
                (
                    run_id,
                    len(docs),
                    "ok",
                    json.dumps(
                        {
                            "changed": changed,
                            "retired": retired,
                            "links": link_count,
                            "embedding_provider": batch.provider,
                            "warnings": spec_warnings + code_warnings + test_warnings,
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    finally:
        conn.close()

    summary = IngestSummary(
        run_id=run_id,
        counts={
            "specs": sum(1 for doc in docs if doc.doc_type in {"spec", "decision"}),
            "code": sum(1 for doc in docs if doc.doc_type == "code"),
            "tests": sum(1 for doc in docs if doc.doc_type == "test"),
            "changed": changed,
            "retired": retired,
        },
        specs=[doc.doc_key for doc in spec_docs],
        code_symbols=[doc.metadata["symbol"] for doc in code_docs],
        tests=[doc.doc_key for doc in test_docs],
        embedding_provider=batch.provider,
        embedding_tokens=batch.input_tokens,
        versions=versions,
        links=link_count,
    )
    if batch.warnings:
        summary.counts["embedding_warnings"] = len(batch.warnings)
    if verbose:
        print(json.dumps(_summary_payload(summary), ensure_ascii=False, indent=2))
        for warning in spec_warnings + code_warnings + test_warnings:
            print(f"[warn] {warning}")
    return summary


def _summary_payload(summary: IngestSummary) -> dict[str, Any]:
    return {
        "run_id": summary.run_id,
        "counts": summary.counts,
        "embedding_provider": summary.embedding_provider,
        "embedding_tokens": summary.embedding_tokens,
        "versions": summary.versions,
        "links": summary.links,
        "specs": summary.specs,
        "code_symbols": summary.code_symbols,
        "tests": summary.tests,
    }
