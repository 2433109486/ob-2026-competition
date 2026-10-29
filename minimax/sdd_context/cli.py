"""CLI entry point for the SDD context module.

Examples:
    python -m sdd_context.cli init --reset
    python -m sdd_context.cli context --task tasks/BOOK-001.md
    python -m sdd_context.cli state-show --task tasks/BOOK-001.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .config import Settings
from .context import build_context, write_bundle
from .db import connect
from .ingest import ingest
from .powercontext import Checkpoint, PowerContextError, PowerContextStateStore


def _settings() -> Settings:
    settings = Settings.load()
    settings.ensure_runtime_dirs()
    return settings


def _cmd_init(args: argparse.Namespace) -> int:
    settings = _settings()
    summary = ingest(settings, reset=args.reset, verbose=True)
    return 0 if summary.counts["specs"] and summary.counts["code"] and summary.counts["tests"] else 1


def _cmd_context(args: argparse.Namespace) -> int:
    settings = _settings()
    task_path = Path(args.task)
    if not task_path.is_absolute():
        task_path = settings.project_root / task_path
    bundle = build_context(
        settings,
        task_path,
        run_id=args.run_id,
        include_state=not args.no_state,
        save=not args.no_save,
    )
    paths = write_bundle(bundle, Path(args.out) if args.out else settings.demo_dir / "context" / "latest")
    print(
        json.dumps(
            {
                "run_id": bundle["run_id"],
                "task_id": bundle["task"]["task_id"],
                "specs": [spec["metadata"].get("id") for spec in bundle["specs"]],
                "code": [f"{doc['path']}::{doc['metadata'].get('symbol')}" for doc in bundle["code"]],
                "tests": [f"{doc['path']}::{doc['metadata'].get('test_name')}" for doc in bundle["tests"]],
                "state_status": bundle["state"].get("status"),
                "state_seq": bundle["state"].get("seq"),
                "paths": {key: str(value) for key, value in paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _cmd_state_save(args: argparse.Namespace) -> int:
    settings = _settings()
    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    checkpoint = Checkpoint(
        task_id=str(payload["task_id"]),
        seq=int(payload["seq"]),
        completed=[str(item) for item in payload.get("completed") or []],
        todos=[str(item) for item in payload.get("todos") or []],
        verifications=list(payload.get("verifications") or []),
        context_run_id=payload.get("context_run_id"),
        code_version=payload.get("code_version"),
        extra=payload.get("extra"),
    )
    store = PowerContextStateStore(settings)
    if not store.health():
        raise SystemExit(f"PowerContext is not reachable at {settings.powercontext_url}")
    result = store.save_checkpoint(checkpoint)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _cmd_state_show(args: argparse.Namespace) -> int:
    settings = _settings()
    store = PowerContextStateStore(settings)
    if not store.health():
        raise SystemExit(f"PowerContext is not reachable at {settings.powercontext_url}")
    loaded = store.load_latest(args.task_id)
    if loaded is None:
        print(json.dumps({"status": "empty", "task_id": args.task_id}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(loaded, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(loaded, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


def _cmd_verify(args: argparse.Namespace) -> int:
    settings = _settings()
    conn = connect(settings, database=settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents WHERE status='active'")
            active_docs = int(cur.fetchone()[0])
            cur.execute("SELECT doc_key, version, status FROM documents WHERE doc_type IN ('spec','decision')")
            specs = {str(row[0]): {"version": int(row[1]), "status": str(row[2])} for row in cur.fetchall()}
            cur.execute("SELECT doc_key, version, status FROM document_versions WHERE doc_key='spec:BOOK-SPEC-001' ORDER BY revision DESC")
            spec_versions = [{"version": int(row[1]), "status": str(row[2])} for row in cur.fetchall()]
            cur.execute("SELECT COUNT(*) FROM links")
            links = int(cur.fetchone()[0])
    finally:
        conn.close()
    required = ["spec:BOOK-SPEC-001", "spec:BOOK-SPEC-002", "spec:BOOK-SPEC-003", "decision:BOOK-DEC-001"]
    missing = [key for key in required if key not in specs]
    state = None
    try:
        store = PowerContextStateStore(settings)
        if store.health():
            state = store.load_latest("BOOK-001")
    except PowerContextError:
        state = None
    payload: dict[str, Any] = {
        "seekdb": {"active_docs": active_docs, "links": links, "specs": specs, "missing": missing},
        "spec_001_versions": spec_versions,
        "powercontext": {
            "reachable": state is not None or _powercontext_reachable(settings),
            "state_status": (state or {}).get("status"),
            "state_seq": (state or {}).get("seq"),
        },
        "source_files": {
            "service": (settings.project_root / "booknest/service.py").exists(),
            "api": (settings.project_root / "booknest/api.py").exists(),
            "target_tests": (settings.project_root / "tests/test_price_filter.py").exists(),
            "regression_tests": (settings.project_root / "tests/test_search_existing.py").exists(),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if not missing and active_docs > 0 else 1


def _powercontext_reachable(settings: Settings) -> bool:
    try:
        return PowerContextStateStore(settings).health()
    except Exception:  # noqa: BLE001
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sdd-context", description="SDD context module for BookNest")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="create the seekdb schema and ingest the corpus")
    init.add_argument("--reset", action="store_true", help="drop and recreate the context tables")
    init.set_defaults(func=_cmd_init)

    ingest_parser = sub.add_parser("ingest", help="re-ingest the corpus")
    ingest_parser.add_argument("--reset", action="store_true", help="drop and recreate the context tables")
    ingest_parser.set_defaults(func=_cmd_init)

    context = sub.add_parser("context", help="build a task context bundle")
    context.add_argument("--task", required=True)
    context.add_argument("--out")
    context.add_argument("--run-id")
    context.add_argument("--no-state", action="store_true", help="skip the PowerContext read")
    context.add_argument("--no-save", action="store_true", help="do not persist the context run")
    context.set_defaults(func=_cmd_context)

    state_save = sub.add_parser("state-save", help="save a task checkpoint to PowerContext")
    state_save.add_argument("--payload", required=True, help="JSON checkpoint payload")
    state_save.set_defaults(func=_cmd_state_save)

    state_show = sub.add_parser("state-show", help="read the latest task checkpoint from PowerContext")
    state_show.add_argument("--task-id", default="BOOK-001")
    state_show.add_argument("--out")
    state_show.set_defaults(func=_cmd_state_show)

    verify = sub.add_parser("verify", help="verify seekdb, sources, and PowerContext state")
    verify.set_defaults(func=_cmd_verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PowerContextError as error:
        print(f"PowerContext error: {error}", file=sys.stderr)
        return 3
    except Exception as error:  # noqa: BLE001 - CLI boundary
        print(f"error: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
