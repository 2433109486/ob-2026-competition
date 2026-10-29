"""文本向量化。

默认使用零依赖的确定性哈希向量（feature hashing）：
把中文单字、双字组合与英文词映射到固定维度，L2 归一化后用 seekdb 的
l2_distance 排序（等价于余弦相似度）。它不需要任何外部 Embedding 服务，
保证评审在离线环境也能复现。

配置 EMBEDDING_BACKEND=openai 时改用 OpenAI 兼容的 /embeddings 接口，
需要同时把 EMBEDDING_DIM 调整为模型维度并重建索引（见 README）。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
import urllib.request

_CJK = re.compile(r"[\u4e00-\u9fff]")
_TOKEN = re.compile(r"[a-zA-Z0-9_]+")


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKC", text).lower()
    tokens: list[str] = []
    runs = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9_]+", text)
    for run in runs:
        if _CJK.match(run):
            tokens.extend(run)
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
        else:
            tokens.append(run)
    return tokens or [text[:8] or "empty"]


def hash_embed(text: str, dim: int) -> list[float]:
    counts: dict[str, int] = {}
    for token in _tokens(text):
        counts[token] = counts.get(token, 0) + 1
    vector = [0.0] * dim
    for token, count in counts.items():
        digest = hashlib.md5(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] % 2 == 0 else -1.0
        vector[index] += sign * (1.0 + math.log(count))
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def openai_embed(texts: list[str], base_url: str, api_key: str, model: str, timeout: float = 20) -> list[list[float]]:
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    request = urllib.request.Request(
        base_url.rstrip("/") + "/embeddings",
        data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]


def to_sql_vector(vector: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in vector) + "]"


class Embedder:
    def __init__(self, backend: str, dim: int, base_url: str = "", api_key: str = "", model: str = "") -> None:
        self.backend = backend
        self.dim = dim
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.backend == "openai":
            return openai_embed(texts, self.base_url, self.api_key, self.model)
        if self.backend != "hash":
            raise ValueError(f"unknown EMBEDDING_BACKEND: {self.backend}")
        return [hash_embed(t, self.dim) for t in texts]

    def embed_one(self, text: str) -> list[float]:
        return self.embed([text])[0]
