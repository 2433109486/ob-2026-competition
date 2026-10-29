"""MiniMax chat-completions client and constrained patch protocol.

The model is asked for complete file contents in a small JSON envelope. The
harness validates every path before writing, so a malformed or over-broad model
response cannot touch tests, specs, or files outside the two implementation
modules.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings

ALLOWED_PATHS = ("booknest/service.py", "booknest/api.py")
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


class MiniMaxError(RuntimeError):
    pass


@dataclass(slots=True)
class ModelReply:
    content: str
    reasoning: str
    model: str
    response_id: str | None
    usage: dict[str, Any]
    latency_ms: int
    raw: dict[str, Any]


class MiniMaxClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.records_dir = settings.records_dir
        self.records_dir.mkdir(parents=True, exist_ok=True)

    def chat(self, messages: Sequence[dict[str, str]], *, label: str) -> ModelReply:
        if not self.settings.minimax_api_key:
            raise MiniMaxError("MINIMAX_API_KEY is not configured")
        url = f"{self.settings.minimax_base_url}/chat/completions"
        payload: dict[str, Any] = {
            "model": self.settings.minimax_model,
            "messages": list(messages),
            "max_completion_tokens": 12000,
            "reasoning_effort": "high",
        }
        headers = {
            "Authorization": f"Bearer {self.settings.minimax_api_key}",
            "Content-Type": "application/json",
        }
        started = time.perf_counter()
        last_error: Exception | None = None
        raw: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                raw = self._post(url, headers, payload)
                break
            except HTTPError as error:
                body = error.read().decode("utf-8", errors="replace")
                last_error = MiniMaxError(f"MiniMax HTTP {error.code}: {body[:800]}")
                if error.code == 400 and "max_completion_tokens" in body:
                    payload.pop("max_completion_tokens", None)
                    payload["max_tokens"] = 12000
                    continue
                if error.code in {408, 429, 500, 502, 503, 504}:
                    time.sleep(2 + attempt * 2)
                    continue
                break
            except (URLError, TimeoutError, ValueError) as error:
                last_error = error
                time.sleep(2 + attempt * 2)
        if raw is None:
            raise MiniMaxError(f"MiniMax request failed after retries: {last_error}")
        latency_ms = int((time.perf_counter() - started) * 1000)
        choices = raw.get("choices") or []
        message = (choices[0] or {}).get("message", {}) if choices else {}
        content = str(message.get("content") or "")
        reasoning = str(message.get("reasoning_content") or "")
        reply = ModelReply(
            content=content,
            reasoning=reasoning,
            model=str(raw.get("model") or self.settings.minimax_model),
            response_id=raw.get("id"),
            usage=raw.get("usage") or {},
            latency_ms=latency_ms,
            raw=raw,
        )
        self._record(label, messages, reply)
        return reply

    def _post(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=300) as response:
            return json.load(response)

    def _record(self, label: str, messages: Sequence[dict[str, str]], reply: ModelReply) -> None:
        stamp = datetime.now(timezone.utc).isoformat()
        request_path = self.records_dir / f"{label}-request.json"
        response_path = self.records_dir / f"{label}-response.json"
        request_path.write_text(
            json.dumps(
                {
                    "ts": stamp,
                    "model": self.settings.minimax_model,
                    "endpoint": f"{self.settings.minimax_base_url}/chat/completions",
                    "messages": list(messages),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        response_path.write_text(
            json.dumps(
                {
                    "ts": stamp,
                    "model": reply.model,
                    "response_id": reply.response_id,
                    "latency_ms": reply.latency_ms,
                    "usage": reply.usage,
                    "content": reply.content,
                    "reasoning_content": reply.reasoning,
                    "raw": reply.raw,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        with (self.records_dir / "calls.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "ts": stamp,
                        "label": label,
                        "model": reply.model,
                        "response_id": reply.response_id,
                        "latency_ms": reply.latency_ms,
                        "usage": reply.usage,
                        "request_bytes": len(json.dumps(list(messages), ensure_ascii=False).encode("utf-8")),
                        "response_bytes": len(reply.content.encode("utf-8")),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )


def build_patch_messages(
    context_markdown: str,
    files: dict[str, str],
    *,
    feedback: str | None = None,
) -> list[dict[str, str]]:
    file_blocks = "\n\n".join(
        f"### FILE: {path}\n```python\n{content.rstrip()}\n```" for path, content in files.items()
    )
    system = (
        "You are a senior Python engineer working in a small, tested repository. "
        "You must use the supplied SDD context as the authority for the change. "
        "Return only one JSON object, with no markdown fences and no prose around it."
    )
    feedback_block = ""
    if feedback:
        feedback_block = (
            "\n## Previous attempt failed\n\n"
            "The harness ran the target tests and observed the output below. Fix the implementation.\n\n"
            "```text\n" + feedback[-6000:] + "\n```\n"
        )
    user = f"""# Development task

Implement the task described by the SDD context below. Modify only these files:

- `booknest/service.py`
- `booknest/api.py`

Do not modify tests, specs, or any other file. Preserve all existing behaviour
listed in the compatibility spec. The implementation must make the included
target tests pass and must not break the regression tests.

## SDD context (authoritative)

{context_markdown}

## Current files

{file_blocks}
{feedback_block}
## Output contract

Return a JSON object shaped exactly like this:

{{
  "summary": "one paragraph describing the change",
  "files": [
    {{"path": "booknest/service.py", "content": "complete file content"}},
    {{"path": "booknest/api.py", "content": "complete file content"}}
  ],
  "notes": ["short implementation notes"]
}}

Requirements for the JSON:
- `files` must contain complete, syntactically valid Python files, not diffs.
- Use only the two allowed paths above.
- Do not include ``` fences inside the JSON strings.
- Keep the public function signatures compatible with the tests.
"""
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def parse_patch(content: str) -> dict[str, Any]:
    text = _THINK.sub("", content).strip()
    match = _FENCE.search(text)
    if match:
        text = match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise MiniMaxError("model response did not contain a JSON object")
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        raise MiniMaxError(f"model response was not valid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise MiniMaxError("model response JSON must be an object")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise MiniMaxError("model response has no files array")
    normalized: list[dict[str, str]] = []
    for item in files:
        if not isinstance(item, dict):
            raise MiniMaxError("each files entry must be an object")
        path = str(item.get("path") or "").replace("\\", "/").strip()
        content_value = item.get("content")
        if path not in ALLOWED_PATHS:
            raise MiniMaxError(f"model attempted to modify a non-allowed path: {path!r}")
        if not isinstance(content_value, str) or not content_value.strip():
            raise MiniMaxError(f"empty content for {path}")
        if "```" in content_value:
            raise MiniMaxError(f"content for {path} contains a markdown fence")
        normalized.append({"path": path, "content": content_value})
    return {
        "summary": str(payload.get("summary") or ""),
        "files": normalized,
        "notes": [str(note) for note in (payload.get("notes") or [])],
    }


def apply_patch(root: Path, patch: dict[str, Any]) -> list[Path]:
    written: list[Path] = []
    for item in patch["files"]:
        relative = item["path"]
        if relative not in ALLOWED_PATHS:
            raise MiniMaxError(f"refusing to write non-allowed path: {relative}")
        target = (root / relative).resolve()
        if root.resolve() not in target.parents:
            raise MiniMaxError(f"path escapes repository root: {relative}")
        target.write_text(item["content"].rstrip() + "\n", encoding="utf-8")
        written.append(target)
    return written
