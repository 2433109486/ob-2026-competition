# Copyright (c) 2026 OceanBase.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Coalesce concurrent Embedding calls and cache successful vectors."""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Any

from powercontext.builtin.inference.models import EmbeddingResult, InferenceUsage

DEFAULT_MAX_BATCH_SIZE = 64
DEFAULT_COALESCE_MS = 5.0
DEFAULT_CACHE_SIZE = 1024


@dataclass(frozen=True, slots=True)
class _Outcome:
    vector: tuple[float, ...]
    batch: object | None
    usage: InferenceUsage


class CoalescingEmbeddingModel:
    """Share in-flight Embedding work across calls and reuse successful vectors."""

    def __init__(
        self,
        model: Any,
        *,
        max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
        coalesce_ms: float = DEFAULT_COALESCE_MS,
        cache_size: int = DEFAULT_CACHE_SIZE,
    ) -> None:
        if not callable(getattr(model, "embed", None)):
            raise ValueError("model must provide an async embed method")
        if not isinstance(max_batch_size, int) or isinstance(max_batch_size, bool) or max_batch_size < 1:
            raise ValueError("max_batch_size must be a positive integer")
        if not isinstance(coalesce_ms, (int, float)) or isinstance(coalesce_ms, bool) or coalesce_ms < 0:
            raise ValueError("coalesce_ms must be a non-negative number")
        if not isinstance(cache_size, int) or isinstance(cache_size, bool) or cache_size < 0:
            raise ValueError("cache_size must be a non-negative integer")
        self._model = model
        self._max_batch_size = max_batch_size
        self._coalesce_seconds = float(coalesce_ms) / 1000.0
        self._cache_size = cache_size
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future[_Outcome]] = {}
        self._pending: deque[str] = deque()
        self._flush_handle: asyncio.TimerHandle | asyncio.Handle | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    @property
    def profile(self):
        return self._model.profile

    async def embed(self, texts: tuple[str, ...], /) -> EmbeddingResult:
        if isinstance(texts, str):
            raise ValueError("texts must be a sequence of strings")
        inputs = tuple(texts)
        if not inputs:
            return EmbeddingResult(vectors=(), usage=InferenceUsage(requests=0))

        vectors: dict[str, tuple[float, ...]] = {}
        futures: dict[str, asyncio.Future[_Outcome]] = {}
        for text in dict.fromkeys(inputs):
            cached = self._cache.get(text)
            if cached is not None:
                self._cache.move_to_end(text)
                vectors[text] = cached
                continue
            futures[text] = self._enqueue(text)

        batch_usage: dict[object, InferenceUsage] = {}
        for text, future in futures.items():
            outcome = await asyncio.shield(future)
            vectors[text] = outcome.vector
            if outcome.batch is not None:
                batch_usage[outcome.batch] = outcome.usage

        return EmbeddingResult(
            vectors=tuple(vectors[text] for text in inputs),
            usage=_combine_usage(tuple(batch_usage.values())),
        )

    def _enqueue(self, text: str) -> asyncio.Future[_Outcome]:
        existing = self._inflight.get(text)
        if existing is not None:
            return existing
        future: asyncio.Future[_Outcome] = asyncio.get_running_loop().create_future()
        self._inflight[text] = future
        self._pending.append(text)
        if self._flush_handle is None:
            loop = asyncio.get_running_loop()
            if self._coalesce_seconds > 0:
                self._flush_handle = loop.call_later(self._coalesce_seconds, self._flush)
            else:
                self._flush_handle = loop.call_soon(self._flush)
        return future

    def _flush(self) -> None:
        self._flush_handle = None
        while self._pending:
            size = min(self._max_batch_size, len(self._pending))
            chunk = [self._pending.popleft() for _ in range(size)]
            futures = [self._inflight[text] for text in chunk]
            token = object()
            task = asyncio.create_task(self._run_batch(chunk, futures, token))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_batch(
        self,
        chunk: list[str],
        futures: list[asyncio.Future[_Outcome]],
        token: object,
    ) -> None:
        try:
            result = await self._model.embed(tuple(chunk))
        except Exception as error:  # noqa: BLE001 - provider failures reach every waiter
            for text, future in zip(chunk, futures, strict=True):
                self._inflight.pop(text, None)
                if not future.done():
                    future.set_exception(error)
            return

        if len(result.vectors) != len(chunk):
            failure = ValueError("embedding provider returned the wrong number of vectors")
            for text, future in zip(chunk, futures, strict=True):
                self._inflight.pop(text, None)
                if not future.done():
                    future.set_exception(failure)
            return

        for text, vector, future in zip(chunk, result.vectors, futures, strict=True):
            self._inflight.pop(text, None)
            self._store(text, vector)
            if not future.done():
                future.set_result(_Outcome(vector=vector, batch=token, usage=result.usage))

    def _store(self, text: str, vector: tuple[float, ...]) -> None:
        if self._cache_size <= 0:
            return
        self._cache[text] = vector
        self._cache.move_to_end(text)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)


def _combine_usage(usages: tuple[InferenceUsage, ...]) -> InferenceUsage:
    requests = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    for usage in usages:
        requests += usage.requests
        if usage.input_tokens is not None:
            input_tokens = (input_tokens or 0) + usage.input_tokens
        if usage.output_tokens is not None:
            output_tokens = (output_tokens or 0) + usage.output_tokens
    return InferenceUsage(requests=requests, input_tokens=input_tokens, output_tokens=output_tokens)


__all__ = [
    "DEFAULT_CACHE_SIZE",
    "DEFAULT_COALESCE_MS",
    "DEFAULT_MAX_BATCH_SIZE",
    "CoalescingEmbeddingModel",
]
