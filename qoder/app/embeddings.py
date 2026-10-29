"""Offline, deterministic embeddings used by the demo corpus.

The competition requires a real vector column and vector search, not a specific
model vendor. This module produces a 768-dimensional signed feature-hash vector
from Chinese character n-grams and English words. It is intentionally
dependency-free and deterministic so a reviewer can rebuild the index offline.

A deployment can replace ``embed_text`` with a model-backed implementation; the
dimension and the rest of the retrieval pipeline stay unchanged.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Iterable, List, Sequence, Tuple

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_WORD = re.compile(r"[a-zA-Z][a-zA-Z0-9_+#.-]*")
_STOP_CJK = set("的了与和是在为及并要把被对中上下来去以等这那有个我们你他她它之其而也就都还又很更最可将会能需要对从到")
_STOP_EN = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "for",
    "with",
    "in",
    "on",
    "is",
    "are",
    "be",
    "as",
    "by",
    "this",
    "that",
    "we",
    "study",
    "paper",
}

DIMENSION = 768
_HASHES = 4


def tokenize(text: str) -> List[Tuple[str, float]]:
    """Return weighted lexical features.

    Chinese is represented as character uni/bi/trigrams; English as words.
    N-grams are kept within a contiguous CJK run so a space does not create a
    meaningless cross-boundary feature.
    """

    lowered = text.lower()
    features: List[Tuple[str, float]] = []
    for word in _WORD.findall(lowered):
        if len(word) > 1 and word not in _STOP_EN:
            features.append(("w:" + word, 1.35))
    for run in _CJK_RUN.findall(lowered):
        chars = [char for char in run if char not in _STOP_CJK]
        features.extend(("c:" + char, 0.45) for char in chars)
        features.extend(("b:" + a + b, 1.0) for a, b in zip(chars, chars[1:]))
        features.extend(("t:" + a + b + c, 1.15) for a, b, c in zip(chars, chars[1:], chars[2:]))
    return features


def embed_text(text: str, dimension: int = DIMENSION) -> List[float]:
    counts: dict[str, List[float]] = {}
    for token, weight in tokenize(text):
        bucket = counts.setdefault(token, [0.0, weight])
        bucket[0] += 1.0
    vector = [0.0] * dimension
    for token, (count, weight) in counts.items():
        strength = (1.0 + math.log(count)) * weight
        for probe in range(_HASHES):
            digest = hashlib.blake2b(
                (token + "#" + str(probe)).encode("utf-8"), digest_size=8
            ).digest()
            index = int.from_bytes(digest[:4], "big") % dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign * strength / math.sqrt(_HASHES)
    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return vector
    return [value / norm for value in vector]


def embed_document(title: str, tags: str, section: str, content: str) -> List[float]:
    # Repeating title and tags gives metadata a modest, explicit weight.
    text = " ".join([title, title, tags, tags, section, content])
    return embed_text(text)


def embed_query(query: str, focus_tags: Iterable[str] = ()) -> List[float]:
    tags = " ".join(focus_tags)
    return embed_text(query + " " + tags)


def to_sql_vector(vector: Sequence[float]) -> str:
    return "[" + ",".join(f"{float(value):.8f}" for value in vector) + "]"


def cosine(left: Sequence[float], right: Sequence[float]) -> float:
    return sum(float(a) * float(b) for a, b in zip(left, right))


def describe() -> dict:
    return {
        "provider": "local-signed-feature-hash",
        "dimension": DIMENSION,
        "tokenizer": "cjk-char-uni-bi-tri + english-word",
        "hashes_per_token": _HASHES,
        "offline": True,
    }
