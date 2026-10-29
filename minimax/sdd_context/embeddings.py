"""Embedding providers: MiniMax ``embo-01`` with a deterministic fallback.

The fallback keeps ingestion and retrieval working when the embedding endpoint
is unavailable; every result records which provider was actually used.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import Settings

_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD = re.compile(r"[a-zA-Z0-9_]+")


@dataclass(slots=True)
class EmbeddingBatch:
    vectors: list[list[float]]
    provider: str
    model: str
    dimensions: int
    requests: int
    input_tokens: int
    warnings: list[str] = field(default_factory=list)


def normalize(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in vector))
    if norm <= 0:
        return [0.0 for _ in vector]
    return [float(value) / norm for value in vector]


def _fallback_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens = _WORD.findall(lowered)
    chars = _CJK.findall(lowered)
    tokens.extend(chars)
    tokens.extend(a + b for a, b in zip(chars, chars[1:]))
    return tokens


def hash_embedding(text: str, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for token in _fallback_tokens(text):
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimension
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign
    return normalize(vector)


def _post_json(url: str, headers: dict[str, str], payload: dict, timeout: int = 90) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(url, data=body, headers=headers, method="POST")
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def _record(settings: Settings, record: dict) -> None:
    path = settings.records_dir / "embeddings.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def embed_texts(
    settings: Settings,
    texts: Sequence[str],
    *,
    purpose: str,
    allow_fallback: bool = True,
) -> EmbeddingBatch:
    """Embed texts with MiniMax, falling back to a deterministic vectorizer."""

    if not texts:
        return EmbeddingBatch([], "none", "", settings.embedding_dimension, 0, 0)

    if not settings.minimax_api_key:
        if not allow_fallback:
            raise RuntimeError("MINIMAX_API_KEY is not configured")
        return _fallback_batch(settings, texts, "MINIMAX_API_KEY is not configured")

    endpoint = f"{settings.minimax_base_url}/embeddings"
    headers = {
        "Authorization": f"Bearer {settings.minimax_api_key}",
        "Content-Type": "application/json",
    }
    vectors: list[list[float]] = []
    total_tokens = 0
    requests = 0
    started = time.perf_counter()
    try:
        for start in range(0, len(texts), settings.embedding_batch_size):
            batch = list(texts[start : start + settings.embedding_batch_size])
            payload = {
                "model": settings.minimax_embedding_model,
                "texts": batch,
                "type": "query" if purpose == "query" else "db",
            }
            last_error: Exception | None = None
            response: dict | None = None
            for attempt in range(3):
                try:
                    response = _post_json(endpoint, headers, payload)
                    break
                except (HTTPError, URLError, TimeoutError, ValueError) as error:
                    last_error = error
                    time.sleep(1.0 + attempt)
            if response is None:
                raise RuntimeError(f"MiniMax embedding failed: {last_error}")
            base_resp = response.get("base_resp")
            if isinstance(base_resp, dict) and base_resp.get("status_code") not in (None, 0):
                raise RuntimeError(
                    f"MiniMax embedding status {base_resp.get('status_code')}: {base_resp.get('status_msg')}"
                )
            rows = response.get("vectors")
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise RuntimeError("MiniMax embedding returned an unexpected payload")
            for row in rows:
                if not isinstance(row, list) or len(row) != settings.embedding_dimension:
                    raise RuntimeError(
                        f"embedding dimension mismatch: expected {settings.embedding_dimension}, got "
                        f"{len(row) if isinstance(row, list) else 'non-list'}"
                    )
                vectors.append(normalize(row))
            requests += 1
            total_tokens += int(response.get("total_tokens") or 0)
    except Exception as error:  # noqa: BLE001 - provider failures fall back deliberately
        if not allow_fallback:
            raise
        return _fallback_batch(settings, texts, str(error))

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    _record(
        settings,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": "minimax",
            "model": settings.minimax_embedding_model,
            "purpose": purpose,
            "text_count": len(texts),
            "dimensions": settings.embedding_dimension,
            "requests": requests,
            "input_tokens": total_tokens,
            "elapsed_ms": elapsed_ms,
        },
    )
    return EmbeddingBatch(
        vectors=vectors,
        provider="minimax",
        model=settings.minimax_embedding_model,
        dimensions=settings.embedding_dimension,
        requests=requests,
        input_tokens=total_tokens,
    )


def _fallback_batch(settings: Settings, texts: Sequence[str], warning: str) -> EmbeddingBatch:
    started = time.perf_counter()
    vectors = [hash_embedding(text, settings.embedding_dimension) for text in texts]
    _record(
        settings,
        {
            "ts": datetime.now(timezone.utc).isoformat(),
            "provider": "hash-fallback",
            "model": "md5-hash-1536",
            "purpose": "fallback",
            "text_count": len(texts),
            "dimensions": settings.embedding_dimension,
            "warning": warning[:300],
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        },
    )
    return EmbeddingBatch(
        vectors=vectors,
        provider="hash-fallback",
        model="md5-hash-1536",
        dimensions=settings.embedding_dimension,
        requests=0,
        input_tokens=0,
        warnings=[warning],
    )
