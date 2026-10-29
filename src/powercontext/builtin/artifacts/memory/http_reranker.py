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

"""Batch an HTTP cross-encoder score service into one global Memory rerank."""

from __future__ import annotations

import math
from typing import Any

import httpx

from powercontext.builtin.artifacts.memory.models import MemoryHit
from powercontext.builtin.artifacts.memory.reranking import MemoryRerankDecision
from powercontext.builtin.inference import InferenceUsage

DEFAULT_POLICY_ID = "http-cross-encoder-v1"


class HTTPMemoryReranker:
    """Score coarse candidates through one HTTP service and rank them globally."""

    def __init__(
        self,
        endpoint: str,
        *,
        client: httpx.AsyncClient,
        batch_size: int = 32,
        policy_id: str = DEFAULT_POLICY_ID,
    ) -> None:
        if not isinstance(endpoint, str) or not endpoint.strip():
            raise ValueError("endpoint must be a non-empty string")
        if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
            raise ValueError("batch_size must be a positive integer")
        if not isinstance(policy_id, str) or not policy_id.strip():
            raise ValueError("policy_id must be a non-empty string")
        if not callable(getattr(client, "post", None)):
            raise ValueError("client must provide an async post method")
        self._endpoint = endpoint
        self._client = client
        self._batch_size = batch_size
        self.policy_id = policy_id

    async def rerank(
        self,
        query: str,
        candidates: tuple[MemoryHit, ...],
        limit: int,
        /,
    ) -> MemoryRerankDecision:
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not candidates:
            raise ValueError("rerank requires at least one candidate")
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1 or limit > len(candidates):
            raise ValueError("rerank limit must be between one and the candidate count")

        scores: dict[int, float] = {}
        requests_made = 0
        for start in range(0, len(candidates), self._batch_size):
            batch = candidates[start : start + self._batch_size]
            payload = {
                "query": query,
                "candidates": [
                    {"rank": start + offset, "text": candidate.text}
                    for offset, candidate in enumerate(batch, start=1)
                ],
            }
            response = await self._client.post(self._endpoint, json=payload)
            response.raise_for_status()
            requests_made += 1
            expected = set(range(start + 1, start + 1 + len(batch)))
            scores.update(_parse_scores(response, expected))

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))[:limit]
        return MemoryRerankDecision(
            selected_ranks=tuple(rank for rank, _score in ranked),
            usage=InferenceUsage(requests=requests_made),
        )


def _parse_scores(response: httpx.Response, expected: set[int]) -> dict[int, float]:
    try:
        payload: Any = response.json()
    except ValueError as error:
        raise ValueError("reranker response must be valid JSON") from error
    if not isinstance(payload, dict) or set(payload) != {"scores"}:
        raise ValueError("reranker response must contain exactly one scores field")
    entries = payload["scores"]
    if not isinstance(entries, list):
        raise ValueError("reranker scores must be a list")

    parsed: dict[int, float] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"rank", "score"}:
            raise ValueError("each reranker score must contain exactly rank and score")
        rank = entry["rank"]
        score = entry["score"]
        if not isinstance(rank, int) or isinstance(rank, bool):
            raise ValueError("reranker ranks must be integers")
        if rank not in expected:
            raise ValueError("reranker scores must cover the requested batch exactly once")
        if rank in parsed:
            raise ValueError("reranker scores must cover the requested batch exactly once")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ValueError("reranker scores must be finite numbers")
        value = float(score)
        if not math.isfinite(value):
            raise ValueError("reranker scores must be finite numbers")
        parsed[rank] = value
    if set(parsed) != expected:
        raise ValueError("reranker scores must cover the requested batch exactly once")
    return parsed


__all__ = ["DEFAULT_POLICY_ID", "HTTPMemoryReranker"]
