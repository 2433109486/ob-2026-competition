"""Assemble a task-scoped SDD context bundle from seekdb and PowerContext."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import Settings
from .db import QueryTrace, connect, save_context_run, save_query_trace
from .embeddings import embed_texts
from .powercontext import PowerContextError, PowerContextStateStore
from .retrieval import (
    RetrievedDoc,
    Task,
    dedupe,
    fetch_docs,
    linked_code,
    linked_tests,
    load_task,
    query_code,
    query_specs,
    query_tests,
    tests_for_code,
)


@dataclass(slots=True)
class ContextSelection:
    task: Task
    specs: list[RetrievedDoc]
    code: list[RetrievedDoc]
    tests: list[RetrievedDoc]
    state: dict[str, Any]
    trace: QueryTrace
    embedding_provider: str
    embedding_tokens: int
    warnings: list[str]


def _select(
    conn,
    settings: Settings,
    task: Task,
    query_vector: Sequence[float],
    trace: QueryTrace,
    *,
    include_state: bool,
) -> ContextSelection:
    warnings: list[str] = []
    spec_candidates = query_specs(conn, task, query_vector, trace)
    specs = [doc for doc in spec_candidates if doc.score >= 0.10][:6]
    if not specs:
        specs = spec_candidates[:3]
        warnings.append("spec score threshold matched nothing; kept the top three candidates")

    spec_keys = [doc.doc_key for doc in specs]
    code_linked = linked_code(conn, spec_keys, trace)
    code_candidates = query_code(conn, task, query_vector, trace)
    code = dedupe([*code_linked, *[doc for doc in code_candidates if doc.score >= 0.12]])[:8]
    code_keys = [doc.doc_key for doc in code]

    tests_linked = linked_tests(conn, spec_keys, trace)
    tests_code = tests_for_code(conn, code_keys, trace)
    tests_candidates = query_tests(conn, task, query_vector, trace)
    tests = dedupe([*tests_linked, *tests_code, *[doc for doc in tests_candidates if doc.score >= 0.12]])[:24]
    tests.sort(key=lambda doc: (0 if doc.metadata.get("kind") == "target" else 1, doc.source_path, doc.title))

    # A code symbol named in a selected spec must be present even when the
    # vector score is low; this is the graph half of the hybrid selection.
    if code_linked:
        known = {doc.doc_key for doc in code}
        code = dedupe([*code_linked, *[doc for doc in code if doc.doc_key not in known]])
        code = code[:10]

    state: dict[str, Any]
    if include_state:
        store = PowerContextStateStore(settings)
        try:
            loaded = store.load_latest(task.task_id)
            if loaded is None:
                state = {
                    "source": "powercontext",
                    "status": "empty",
                    "task_id": task.task_id,
                    "completed": [],
                    "todos": [],
                    "verifications": [],
                    "note": "no checkpoint has been saved for this task yet",
                }
            else:
                state = loaded
        except PowerContextError as error:
            state = {
                "source": "powercontext",
                "status": "unavailable",
                "task_id": task.task_id,
                "completed": [],
                "todos": [],
                "verifications": [],
                "error": str(error),
            }
            warnings.append(f"PowerContext state unavailable: {error}")
    else:
        state = {
            "source": "powercontext",
            "status": "skipped",
            "task_id": task.task_id,
            "completed": [],
            "todos": [],
            "verifications": [],
        }

    return ContextSelection(
        task=task,
        specs=specs,
        code=code,
        tests=tests,
        state=state,
        trace=trace,
        embedding_provider="minimax-embo-01",
        embedding_tokens=0,
        warnings=warnings,
    )


def _validate_sources(settings: Settings, selection: ContextSelection) -> list[str]:
    invalid: list[str] = []
    for group, docs in (("spec", selection.specs), ("code", selection.code), ("test", selection.tests)):
        for doc in docs:
            path = settings.project_root / doc.source_path
            if not path.exists():
                invalid.append(f"{group} source does not exist: {doc.source_path} ({doc.doc_key})")
    if invalid:
        invalid_set = set(invalid)
        selection.specs = [doc for doc in selection.specs if f"spec source does not exist: {doc.source_path} ({doc.doc_key})" not in invalid_set]
        selection.code = [doc for doc in selection.code if f"code source does not exist: {doc.source_path} ({doc.doc_key})" not in invalid_set]
        selection.tests = [doc for doc in selection.tests if f"test source does not exist: {doc.source_path} ({doc.doc_key})" not in invalid_set]
    return invalid


def _code_version(settings: Settings, code_docs: Sequence[RetrievedDoc]) -> tuple[str, dict[str, str]]:
    digest = hashlib.sha256()
    files: dict[str, str] = {}
    for doc in sorted(code_docs, key=lambda item: item.source_path):
        path = settings.project_root / doc.source_path
        if not path.exists():
            continue
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        files[doc.source_path] = content_hash
        digest.update(doc.source_path.encode("utf-8"))
        digest.update(content_hash.encode("utf-8"))
    return f"sha256:{digest.hexdigest()}", files


def build_context(
    settings: Settings,
    task_path: Path,
    *,
    run_id: str | None = None,
    include_state: bool = True,
    save: bool = True,
) -> dict[str, Any]:
    settings.ensure_runtime_dirs()
    run_id = run_id or f"ctx-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
    task = load_task(task_path, project_root=settings.project_root)
    embedding = embed_texts(settings, [task.query_text], purpose="query")
    if not embedding.vectors:
        raise RuntimeError("failed to embed the task query")
    query_vector = embedding.vectors[0]

    trace = QueryTrace()
    conn = connect(settings, database=settings.seekdb_database)
    try:
        selection = _select(conn, settings, task, query_vector, trace, include_state=include_state)
        selection.embedding_tokens = embedding.input_tokens
        if embedding.provider != "minimax":
            selection.embedding_provider = embedding.provider
        invalid = _validate_sources(settings, selection)
        selection.warnings.extend(invalid)
        code_version, file_hashes = _code_version(settings, selection.code)
        bundle = _compose_bundle(selection, run_id, code_version, file_hashes, embedding.provider)
        markdown = render_markdown(bundle)
        bundle["context_markdown"] = markdown
        if save:
            save_context_run(conn, run_id, task.task_id, task.body, bundle, markdown)
            save_query_trace(conn, run_id, trace)
    finally:
        conn.close()
    return bundle


def _compose_bundle(
    selection: ContextSelection,
    run_id: str,
    code_version: str,
    file_hashes: dict[str, str],
    embedding_provider: str,
) -> dict[str, Any]:
    task = selection.task
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "task": {
            "task_id": task.task_id,
            "title": task.title,
            "source_path": task.source_path,
            "keywords": task.keywords,
            "target_symbols": task.target_symbols,
            "body": task.body,
        },
        "specs": [doc.to_dict() for doc in selection.specs],
        "code": [doc.to_dict() for doc in selection.code],
        "tests": [doc.to_dict() for doc in selection.tests],
        "state": selection.state,
        "code_version": code_version,
        "code_file_hashes": file_hashes,
        "retrieval": {
            "engine": "seekdb",
            "database": "sdd_context",
            "tables": ["documents", "links", "document_versions"],
            "embedding_provider": embedding_provider,
            "embedding_tokens": selection.embedding_tokens,
            "queries": selection.trace.to_json(),
            "selected": {
                "specs": [doc.doc_key for doc in selection.specs],
                "code": [doc.doc_key for doc in selection.code],
                "tests": [doc.doc_key for doc in selection.tests],
            },
            "warnings": selection.warnings,
        },
    }


def render_markdown(bundle: dict[str, Any]) -> str:
    task = bundle["task"]
    lines: list[str] = []
    lines.append(f"# SDD Context — {task['task_id']}: {task['title']}")
    lines.append("")
    lines.append(f"- Context run: `{bundle['run_id']}`")
    lines.append(f"- Code version: `{bundle['code_version']}`")
    lines.append(f"- Assembled: {bundle['generated_at']}")
    lines.append("")
    lines.append("## 1. Task")
    lines.append("")
    lines.append(f"Source: `{task['source_path']}`")
    lines.append("")
    lines.append(task["body"].strip())
    lines.append("")

    lines.append("## 2. Applicable specifications")
    lines.append("")
    for spec in bundle["specs"]:
        meta = spec.get("metadata") or {}
        lines.append(f"### {meta.get('id', spec['title'])} — {meta.get('title', spec['title'])} (v{spec['version']})")
        lines.append("")
        lines.append(f"- Source: `{spec['path']}`")
        lines.append(f"- Status: `{spec.get('status', 'active')}`")
        lines.append(f"- Why selected: {', '.join(spec.get('reasons') or [])}")
        if meta.get("applies_to"):
            lines.append(f"- Applies to: {', '.join(f'`{symbol}`' for symbol in meta['applies_to'])}")
        lines.append("")
        for requirement in meta.get("requirements") or []:
            lines.append(f"#### {requirement['id']} {requirement['title']}")
            lines.append("")
            body = requirement["text"]
            body = body.split("\n", 1)[1].strip() if "\n" in body else body
            lines.append(body)
            lines.append("")

    lines.append("## 3. Code to inspect or modify")
    lines.append("")
    for code in bundle["code"]:
        meta = code.get("metadata") or {}
        lines.append(f"### `{code['path']}` :: `{meta.get('symbol', code['title'])}`")
        lines.append("")
        lines.append(
            f"- Lines: {meta.get('start_line', '?')}-{meta.get('end_line', '?')} · kind: `{meta.get('kind', '?')}`"
        )
        lines.append(f"- Why selected: {', '.join(code.get('reasons') or [])}")
        lines.append("")
        lines.append("```python")
        lines.append(code.get("content", "").rstrip())
        lines.append("```")
        lines.append("")

    lines.append("## 4. Tests for functional and compatibility verification")
    lines.append("")
    for test in bundle["tests"]:
        meta = test.get("metadata") or {}
        lines.append(f"### `{test['path']}::{meta.get('test_name', test['title'])}` ({meta.get('kind', '?')})")
        lines.append("")
        lines.append(f"- Specs: {', '.join(meta.get('spec_ids') or ['-'])}")
        lines.append(f"- Why selected: {', '.join(test.get('reasons') or [])}")
        lines.append("")
        lines.append("```python")
        lines.append(test.get("content", "").rstrip())
        lines.append("```")
        lines.append("")

    lines.append("## 5. Saved task state (PowerContext)")
    lines.append("")
    state = bundle.get("state") or {}
    lines.append(f"- Source: `{state.get('source', 'powercontext')}` · status: `{state.get('status', 'unknown')}`")
    if state.get("powercontext"):
        reference = state["powercontext"]
        lines.append(
            f"- Artifact: `{reference.get('artifact_id')}` revision `{reference.get('revision')}` "
            f"state_version `{reference.get('state_version')}`"
        )
    if state.get("seq"):
        lines.append(f"- Checkpoint seq: {state['seq']}")
    lines.append("")
    lines.append("### Completed")
    for item in state.get("completed") or []:
        lines.append(f"- [x] {item}")
    if not state.get("completed"):
        lines.append("- (none yet)")
    lines.append("")
    lines.append("### Todo")
    for item in state.get("todos") or []:
        lines.append(f"- [ ] {item}")
    if not state.get("todos"):
        lines.append("- (none)")
    lines.append("")
    lines.append("### Verification results")
    for verification in state.get("verifications") or []:
        lines.append(
            f"- `{verification.get('command', '?')}` → exit `{verification.get('exit_code', '?')}`"
            f" · {verification.get('summary', '')}"
        )
    if not state.get("verifications"):
        lines.append("- (none yet)")
    lines.append("")

    lines.append("## 6. Retrieval provenance")
    lines.append("")
    retrieval = bundle["retrieval"]
    lines.append(f"- Engine: `{retrieval['engine']}` database `{retrieval['database']}`")
    lines.append(f"- Embedding provider: `{retrieval['embedding_provider']}` ({retrieval['embedding_tokens']} tokens)")
    lines.append("- Queries executed against seekdb:")
    for query in retrieval["queries"]:
        lines.append(f"  - rows={query['row_count']} · {query['sql'][:180]}")
    for warning in retrieval.get("warnings") or []:
        lines.append(f"- Warning: {warning}")
    lines.append("")
    return "\n".join(lines)


def write_bundle(bundle: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "context.json"
    md_path = out_dir / "context.md"
    queries_path = out_dir / "queries.json"
    json_path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(bundle["context_markdown"], encoding="utf-8")
    queries_path.write_text(json.dumps(bundle["retrieval"]["queries"], ensure_ascii=False, indent=2), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "queries": queries_path}
