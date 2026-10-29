"""End-to-end demonstration for the BookNest SDD context system.

The script is intentionally explicit: every stage writes evidence under
``demo/`` or ``artifacts/`` so a reviewer can audit the before/after claims.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sdd_context.config import Settings  # noqa: E402
from sdd_context.context import build_context, write_bundle  # noqa: E402
from sdd_context.db import connect  # noqa: E402
from sdd_context.ingest import ingest  # noqa: E402
from sdd_context.minimax_client import MiniMaxClient, apply_patch, build_patch_messages, parse_patch  # noqa: E402
from sdd_context.powercontext import Checkpoint, PowerContextStateStore  # noqa: E402

SERVER_PORT = 8765


def powercontext_exe() -> Path:
    candidates = [
        os.environ.get("POWERCONTEXT_EXE"),
        shutil.which("powercontext"),
        str(Path(r"D:\agent\sandbox\pc-venv\Scripts\powercontext.exe")),
        str(ROOT / ".venv" / "Scripts" / "powercontext.exe"),
        str(ROOT / ".venv" / "bin" / "powercontext"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return Path(candidate)
    raise RuntimeError("powercontext CLI not found; set POWERCONTEXT_EXE to its path")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_version() -> str:
    digest = hashlib.sha256()
    for relative in ("booknest/service.py", "booknest/api.py"):
        digest.update(relative.encode("utf-8"))
        digest.update(sha256_file(ROOT / relative).encode("utf-8"))
    return f"sha256:{digest.hexdigest()}"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_command(command: list[str], *, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(ROOT)
    env["COLUMNS"] = "120"
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=env,
    )


def summarize_pytest(output: str) -> tuple[int, int, str]:
    import re

    summary = ""
    for line in output.splitlines():
        text = line.strip()
        if " passed" in text or " failed" in text:
            summary = text
    passed_match = re.search(r"(\d+) passed", output)
    failed_match = re.search(r"(\d+) failed", output)
    passed = int(passed_match.group(1)) if passed_match else 0
    failed = int(failed_match.group(1)) if failed_match else 0
    return passed, failed, summary


def run_pytest(label: str, phase: str) -> dict[str, Any]:
    version = code_version()
    result = run_command([sys.executable, "-m", "pytest", "-q"])
    passed, failed, summary = summarize_pytest(result.stdout + "\n" + result.stderr)
    log_path = ROOT / "artifacts" / "test_logs" / f"{label}.log"
    header = (
        f"command: {sys.executable} -m pytest -q\n"
        f"cwd: {ROOT}\n"
        f"phase: {phase}\n"
        f"code_version: {version}\n"
        f"exit_code: {result.returncode}\n"
        f"timestamp: {now()}\n"
        f"pytest_summary: {summary}\n"
        "---- output ----\n"
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(header + result.stdout + ("\n[stderr]\n" + result.stderr if result.stderr else ""), encoding="utf-8")
    return {
        "label": label,
        "phase": phase,
        "command": f"{sys.executable} -m pytest -q",
        "exit_code": result.returncode,
        "passed": passed,
        "failed": failed,
        "summary": summary,
        "code_version": version,
        "log": str(log_path.relative_to(ROOT)),
        "output_tail": (result.stdout + "\n" + result.stderr)[-4000:],
    }


def server_pid() -> int | None:
    if os.name == "nt":
        try:
            output = subprocess.check_output(["netstat", "-ano"], text=True, encoding="utf-8", errors="replace")
        except subprocess.SubprocessError:
            return None
        for line in output.splitlines():
            if f":{SERVER_PORT}" in line and "LISTENING" in line.upper():
                parts = line.split()
                try:
                    return int(parts[-1])
                except (ValueError, IndexError):
                    continue
        return None
    try:
        output = subprocess.check_output(["lsof", "-ti", f"tcp:{SERVER_PORT}"], text=True)
        return int(output.strip().splitlines()[0])
    except (subprocess.SubprocessError, ValueError, IndexError):
        return None


def health() -> bool:
    try:
        import urllib.request

        with urllib.request.urlopen(f"http://127.0.0.1:{SERVER_PORT}/health/live", timeout=3) as response:
            return response.status == 200
    except Exception:  # noqa: BLE001
        return False


def stop_server() -> None:
    pid = server_pid()
    if pid is None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    else:
        subprocess.run(["kill", "-9", str(pid)], capture_output=True)
    for _ in range(30):
        if not health():
            return
        time.sleep(0.5)


def start_server() -> None:
    if health():
        return
    env = os.environ.copy()
    env["TMP"] = str(ROOT / "demo" / "runtime" / "work")
    env["TEMP"] = env["TMP"]
    env["PYTHONIOENCODING"] = "utf-8"
    log_path = ROOT / "demo" / "runtime" / "powercontext.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8")
    process = subprocess.Popen(
        [str(powercontext_exe()), "server", "run", "--env-file", ".env.powercontext"],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        env=env,
    )
    write_text(ROOT / "demo" / "runtime" / "powercontext.pid", str(process.pid))
    for _ in range(120):
        if health():
            return
        if process.poll() is not None:
            raise RuntimeError(f"PowerContext exited with {process.returncode}; see {log_path}")
        time.sleep(0.5)
    raise RuntimeError("PowerContext did not become healthy in time")


def restart_server() -> None:
    stop_server()
    if health():
        raise RuntimeError("PowerContext is still healthy after stop")
    start_server()
    if not health():
        raise RuntimeError("PowerContext did not restart")


def reset_working_tree() -> None:
    for relative in ("booknest/service.py", "booknest/api.py"):
        shutil.copy2(ROOT / "baseline" / relative, ROOT / relative)
    shutil.copy2(
        ROOT / "baseline" / "specs" / "BOOK-SPEC-001-price-filter.md",
        ROOT / "specs" / "BOOK-SPEC-001-price-filter.md",
    )
    for cache in (ROOT / "booknest" / "__pycache__", ROOT / "tests" / "__pycache__", ROOT / ".pytest_cache"):
        shutil.rmtree(cache, ignore_errors=True)


def clean_demo() -> None:
    for relative in (
        "demo/context",
        "demo/state",
        "demo/minimax_records",
        "artifacts/test_logs",
        "artifacts/before",
        "artifacts/after",
        "demo/powercontext_records.jsonl",
        "demo/summary.json",
        "artifacts/changes.diff",
        "artifacts/spec-changes.diff",
    ):
        path = ROOT / relative
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()
    for path in (ROOT / "demo").glob("0*.json"):
        path.unlink()
    (ROOT / "artifacts/test_logs").mkdir(parents=True, exist_ok=True)
    (ROOT / "demo/state").mkdir(parents=True, exist_ok=True)


def snapshot(stage: str, spec_source: Path) -> None:
    target = ROOT / "artifacts" / stage
    for relative in ("booknest/service.py", "booknest/api.py"):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)
    destination = target / "specs/BOOK-SPEC-001-price-filter.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(spec_source, destination)


def write_diffs() -> None:
    code_parts: list[str] = []
    for relative in ("booknest/service.py", "booknest/api.py"):
        before = (ROOT / "artifacts/before" / relative).read_text(encoding="utf-8").splitlines(keepends=True)
        after = (ROOT / "artifacts/after" / relative).read_text(encoding="utf-8").splitlines(keepends=True)
        code_parts.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"before/{relative}",
                tofile=f"after/{relative}",
            )
        )
    write_text(ROOT / "artifacts/changes.diff", "".join(code_parts))

    before_spec = (ROOT / "artifacts/before/specs/BOOK-SPEC-001-price-filter.md").read_text(encoding="utf-8").splitlines(keepends=True)
    after_spec = (ROOT / "artifacts/after/specs/BOOK-SPEC-001-price-filter.md").read_text(encoding="utf-8").splitlines(keepends=True)
    spec_diff = difflib.unified_diff(
        before_spec,
        after_spec,
        fromfile="before/specs/BOOK-SPEC-001-price-filter.md",
        tofile="after/specs/BOOK-SPEC-001-price-filter.md",
    )
    write_text(ROOT / "artifacts/spec-changes.diff", "".join(spec_diff))


def context_for_prompt(settings: Settings, run_id: str) -> dict[str, Any]:
    bundle = build_context(settings, ROOT / "tasks/BOOK-001.md", run_id=run_id, include_state=True, save=True)
    write_bundle(bundle, ROOT / "demo/context" / run_id)
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.parse_args(argv)

    settings = Settings.load()
    settings.ensure_runtime_dirs()
    slug = datetime.now().strftime("%Y%m%d-%H%M%S")
    settings.powercontext_scope_key = f"booknest-sdd-{slug}"
    settings.powercontext_scope_file.unlink(missing_ok=True)

    stop_server()
    clean_demo()
    reset_working_tree()
    snapshot("before", ROOT / "baseline/specs/BOOK-SPEC-001-price-filter.md")
    start_server()

    summary: dict[str, Any] = {"run": slug, "started_at": now(), "model": settings.minimax_model}
    summary["powercontext_url"] = settings.powercontext_url
    summary["seekdb"] = f"{settings.seekdb_host}:{settings.seekdb_port}/{settings.seekdb_database}"

    print("[1/9] ingesting v1 corpus into seekdb")
    ingest_summary = ingest(settings, reset=True, verbose=False)
    write_json(ROOT / "demo/01_ingest_v1.json", {
        "run_id": ingest_summary.run_id,
        "counts": ingest_summary.counts,
        "embedding_provider": ingest_summary.embedding_provider,
        "embedding_tokens": ingest_summary.embedding_tokens,
        "specs": ingest_summary.specs,
        "links": ingest_summary.links,
    })
    summary["ingest_v1"] = {
        "counts": ingest_summary.counts,
        "embedding_provider": ingest_summary.embedding_provider,
        "embedding_tokens": ingest_summary.embedding_tokens,
        "links": ingest_summary.links,
    }

    print("[2/9] building initial context and running the baseline tests")
    before_bundle = context_for_prompt(settings, f"ctx-before-{slug}")
    write_json(ROOT / "demo/01_context_before.json", before_bundle)
    write_text(ROOT / "demo/01_context_before.md", before_bundle["context_markdown"])
    before_tests = run_pytest("01_tests_before", "before")
    if before_tests["exit_code"] == 0 or before_tests["failed"] == 0:
        raise RuntimeError(f"baseline target tests must fail, got {before_tests['summary']}")
    summary["before_tests"] = before_tests

    store = PowerContextStateStore(settings)
    before_source = store.save_source(
        f"book-001-tests-before-{slug}",
        Path(ROOT / before_tests["log"]).read_text(encoding="utf-8"),
        {"task_id": "BOOK-001", "phase": "before", "exit_code": before_tests["exit_code"]},
    )
    checkpoint1 = store.save_checkpoint(
        Checkpoint(
            task_id="BOOK-001",
            seq=1,
            completed=[
                "ingested v1 specs, code, and tests into seekdb",
                "built the first SDD context bundle",
                "ran baseline functional tests and captured the expected failure",
            ],
            todos=["apply a MiniMax-generated patch", "run functional and regression tests"],
            verifications=[
                {
                    "command": before_tests["command"],
                    "exit_code": before_tests["exit_code"],
                    "summary": before_tests["summary"],
                    "log": before_tests["log"],
                    "code_version": before_tests["code_version"],
                }
            ],
            context_run_id=before_bundle["run_id"],
            code_version=before_tests["code_version"],
            extra={"evidence_sources": [before_source.get("source") or before_source]},
        )
    )
    write_json(ROOT / "demo/state/checkpoint-1.json", checkpoint1)
    summary["checkpoint_1"] = {"artifact_id": checkpoint1.get("artifact_id"), "revision": checkpoint1.get("revision")}

    print("[3/9] rebuilding context with the saved PowerContext state")
    prompt_bundle = context_for_prompt(settings, f"ctx-prompt-{slug}")
    write_json(ROOT / "demo/02_context_before_with_state.json", prompt_bundle)
    if prompt_bundle["state"].get("status") != "loaded" or prompt_bundle["state"].get("seq") != 1:
        raise RuntimeError(f"context did not load checkpoint 1: {prompt_bundle['state']}")

    print("[4/9] asking MiniMax for the implementation")
    client = MiniMaxClient(settings)
    attempts: list[dict[str, Any]] = []
    feedback: str | None = None
    final_tests: dict[str, Any] | None = None
    for attempt in range(1, 4):
        files = {
            "booknest/service.py": (ROOT / "booknest/service.py").read_text(encoding="utf-8"),
            "booknest/api.py": (ROOT / "booknest/api.py").read_text(encoding="utf-8"),
        }
        messages = build_patch_messages(prompt_bundle["context_markdown"], files, feedback=feedback)
        reply = client.chat(messages, label=f"call-{attempt:02d}")
        record: dict[str, Any] = {
            "attempt": attempt,
            "response_id": reply.response_id,
            "model": reply.model,
            "usage": reply.usage,
            "latency_ms": reply.latency_ms,
            "summary": None,
            "paths": [],
            "tests": None,
        }
        try:
            patch = parse_patch(reply.content)
            record["summary"] = patch["summary"]
            record["paths"] = [item["path"] for item in patch["files"]]
            write_json(ROOT / "demo/minimax_records" / f"call-{attempt:02d}-patch.json", patch)
            apply_patch(ROOT, patch)
        except Exception as error:  # noqa: BLE001
            record["parse_error"] = f"{type(error).__name__}: {error}"
            attempts.append(record)
            feedback = f"Your previous response could not be applied: {error}. Return the required JSON object."
            continue

        tests = run_pytest(f"02_tests_after_attempt_{attempt:02d}", "after")
        record["tests"] = tests
        attempts.append(record)
        if tests["exit_code"] == 0:
            final_tests = tests
            break
        feedback = tests["output_tail"]

    write_json(ROOT / "demo/03_minimax_attempts.json", attempts)
    summary["minimax_attempts"] = attempts
    if final_tests is None:
        raise RuntimeError("MiniMax did not produce a passing patch in three attempts")

    print("[5/9] snapshotting the code change and recording the passing tests")
    after_tests = run_pytest("02_tests_after", "after")
    if after_tests["exit_code"] != 0:
        raise RuntimeError(f"final test run failed: {after_tests['summary']}")
    snapshot("after", ROOT / "specs/BOOK-SPEC-001-price-filter.md")
    summary["after_tests"] = after_tests
    summary["diff"] = "artifacts/changes.diff"

    after_source = store.save_source(
        f"book-001-tests-after-{slug}",
        Path(ROOT / after_tests["log"]).read_text(encoding="utf-8"),
        {"task_id": "BOOK-001", "phase": "after", "exit_code": after_tests["exit_code"]},
    )
    checkpoint2 = store.save_checkpoint(
        Checkpoint(
            task_id="BOOK-001",
            seq=2,
            completed=[
                "ingested v1 specs, code, and tests into seekdb",
                "built the first SDD context bundle",
                "applied the MiniMax-generated patch to service.py and api.py",
                "all functional and regression tests pass",
            ],
            todos=["update BOOK-SPEC-001 to v2 and re-import", "read the state after a module restart"],
            verifications=[
                {
                    "command": before_tests["command"],
                    "exit_code": before_tests["exit_code"],
                    "summary": before_tests["summary"],
                    "log": before_tests["log"],
                    "code_version": before_tests["code_version"],
                },
                {
                    "command": after_tests["command"],
                    "exit_code": after_tests["exit_code"],
                    "summary": after_tests["summary"],
                    "log": after_tests["log"],
                    "code_version": after_tests["code_version"],
                },
            ],
            context_run_id=prompt_bundle["run_id"],
            code_version=after_tests["code_version"],
            extra={"evidence_sources": [before_source.get("source"), after_source.get("source")]},
        )
    )
    write_json(ROOT / "demo/state/checkpoint-2.json", checkpoint2)
    summary["checkpoint_2"] = {"artifact_id": checkpoint2.get("artifact_id"), "revision": checkpoint2.get("revision")}

    print("[6/9] updating the spec to v2 and re-importing")
    shutil.copy2(
        ROOT / "specs/updates/BOOK-SPEC-001-price-filter.v2.md",
        ROOT / "specs/BOOK-SPEC-001-price-filter.md",
    )
    snapshot("after", ROOT / "specs/BOOK-SPEC-001-price-filter.md")
    write_diffs()
    ingest_v2 = ingest(settings, reset=False, verbose=False)
    write_json(ROOT / "demo/04_ingest_v2.json", {
        "run_id": ingest_v2.run_id,
        "counts": ingest_v2.counts,
        "embedding_provider": ingest_v2.embedding_provider,
        "embedding_tokens": ingest_v2.embedding_tokens,
        "versions": ingest_v2.versions,
    })
    after_spec_bundle = context_for_prompt(settings, f"ctx-after-spec-{slug}")
    write_json(ROOT / "demo/04_context_after_spec_update.json", after_spec_bundle)
    write_text(ROOT / "demo/04_context_after_spec_update.md", after_spec_bundle["context_markdown"])

    spec_v1 = next(item for item in before_bundle["specs"] if item["metadata"].get("id") == "BOOK-SPEC-001")
    spec_v2 = next(item for item in after_spec_bundle["specs"] if item["metadata"].get("id") == "BOOK-SPEC-001")
    v1_reqs = [req["id"] for req in spec_v1["metadata"].get("requirements") or []]
    v2_reqs = [req["id"] for req in spec_v2["metadata"].get("requirements") or []]
    if spec_v1["version"] != 1 or spec_v2["version"] != 2:
        raise RuntimeError(f"unexpected spec versions: before={spec_v1['version']} after={spec_v2['version']}")
    if "REQ-005" not in v2_reqs or "REQ-005" in v1_reqs:
        raise RuntimeError(f"updated requirement not reflected: v1={v1_reqs} v2={v2_reqs}")

    conn = connect(settings, database=settings.seekdb_database)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version, status FROM document_versions WHERE doc_key='spec:BOOK-SPEC-001' ORDER BY revision DESC"
            )
            history = [{"version": int(row[0]), "status": str(row[1])} for row in cur.fetchall()]
    finally:
        conn.close()
    write_json(
        ROOT / "demo/05_spec_update_evidence.json",
        {
            "before": {"version": spec_v1["version"], "requirements": v1_reqs, "run_id": before_bundle["run_id"]},
            "after": {
                "version": spec_v2["version"],
                "requirements": v2_reqs,
                "run_id": after_spec_bundle["run_id"],
                "source": spec_v2["path"],
            },
            "document_versions": history,
        },
    )
    if not any(row["version"] == 1 and row["status"] == "superseded" for row in history):
        raise RuntimeError(f"v1 was not marked superseded: {history}")
    summary["spec_update"] = {"before_version": spec_v1["version"], "after_version": spec_v2["version"], "history": history}

    checkpoint3 = store.save_checkpoint(
        Checkpoint(
            task_id="BOOK-001",
            seq=3,
            completed=[
                "ingested v1 specs, code, and tests into seekdb",
                "built the first SDD context bundle",
                "applied the MiniMax-generated patch to service.py and api.py",
                "all functional and regression tests pass",
                "updated BOOK-SPEC-001 to v2, re-ingested it, and confirmed the context uses REQ-005",
            ],
            todos=[],
            verifications=[
                {
                    "command": before_tests["command"],
                    "exit_code": before_tests["exit_code"],
                    "summary": before_tests["summary"],
                    "log": before_tests["log"],
                    "code_version": before_tests["code_version"],
                },
                {
                    "command": after_tests["command"],
                    "exit_code": after_tests["exit_code"],
                    "summary": after_tests["summary"],
                    "log": after_tests["log"],
                    "code_version": after_tests["code_version"],
                },
                {
                    "command": "sdd_context context --task tasks/BOOK-001.md",
                    "exit_code": 0,
                    "summary": "context returned BOOK-SPEC-001 v2 with REQ-005",
                    "context_run_id": after_spec_bundle["run_id"],
                },
            ],
            context_run_id=after_spec_bundle["run_id"],
            code_version=after_tests["code_version"],
        )
    )
    write_json(ROOT / "demo/state/checkpoint-3.json", checkpoint3)
    summary["checkpoint_3"] = {"artifact_id": checkpoint3.get("artifact_id"), "revision": checkpoint3.get("revision")}

    print("[7/9] restarting PowerContext and reading the state from a new process")
    restart_server()
    cli = run_command(
        [
            sys.executable,
            "-m",
            "sdd_context.cli",
            "context",
            "--task",
            "tasks/BOOK-001.md",
            "--out",
            "demo/context/06_after_restart",
        ],
        timeout=180,
    )
    if cli.returncode != 0:
        raise RuntimeError(f"post-restart context failed: {cli.stderr}")
    restarted_bundle = json.loads((ROOT / "demo/context/06_after_restart/context.json").read_text(encoding="utf-8"))
    state_after_restart = restarted_bundle["state"]
    if state_after_restart.get("status") != "loaded" or state_after_restart.get("seq") != 3:
        raise RuntimeError(f"state was not reused after restart: {state_after_restart}")
    if "updated BOOK-SPEC-001 to v2" not in " ".join(state_after_restart.get("completed") or []):
        raise RuntimeError("restarted state is missing the v2 completion record")
    write_json(ROOT / "demo/07_state_after_restart.json", state_after_restart)
    summary["state_after_restart"] = {
        "status": state_after_restart.get("status"),
        "seq": state_after_restart.get("seq"),
        "artifact_id": (state_after_restart.get("powercontext") or {}).get("artifact_id"),
    }

    print("[8/9] verifying the database and context sources")
    verify = run_command([sys.executable, "-m", "sdd_context.cli", "verify"], timeout=60)
    write_text(ROOT / "demo/08_verify.txt", verify.stdout + "\n" + verify.stderr)
    if verify.returncode != 0:
        raise RuntimeError(f"verify failed: {verify.stdout} {verify.stderr}")

    print("[9/9] writing summary")
    source_check = {
        "specs": [
            {"id": item["metadata"].get("id"), "path": item["path"], "exists": (ROOT / item["path"]).exists()}
            for item in after_spec_bundle["specs"]
        ],
        "code": [
            {
                "path": item["path"],
                "symbol": item["metadata"].get("symbol"),
                "exists": (ROOT / item["path"]).exists(),
            }
            for item in after_spec_bundle["code"]
        ],
        "tests": [
            {"path": item["path"], "test": item["metadata"].get("test_name"), "exists": (ROOT / item["path"]).exists()}
            for item in after_spec_bundle["tests"]
        ],
    }
    all_exist = all(entry["exists"] for group in source_check.values() for entry in group)
    summary.update(
        {
            "finished_at": now(),
            "acceptance": {
                "runnable": True,
                "minimax_participated": any(item.get("response_id") for item in attempts),
                "context_sources_exist": all_exist,
                "seekdb_queries": len(after_spec_bundle["retrieval"]["queries"]),
                "state_reused_after_restart": True,
                "before_failed": before_tests["failed"] > 0,
                "after_passed": after_tests["exit_code"] == 0 and after_tests["failed"] == 0,
                "spec_update_reflected": True,
            },
            "source_check": source_check,
            "verification": verify.stdout,
        }
    )
    write_json(ROOT / "demo/summary.json", summary)
    print(json.dumps(summary["acceptance"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
