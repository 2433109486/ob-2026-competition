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

"""Incremental Context Pack transport that reuses a stable chunk prefix."""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass

CONTEXT_PACK_SCHEMA = "powercontext.context-pack.v1"
CONTEXT_PACK_DELTA_SCHEMA = "powercontext.context-pack-delta.v1"
_DEFAULT_CHUNK_BYTES = 512


class ContextPackError(ValueError):
    """Raised when a Context Pack or delta violates the wire contract."""


def _canonical(payload: object) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _encode_items(items: tuple[bytes, ...]) -> list[str]:
    return [base64.b64encode(item).decode("ascii") for item in items]


def _decode_items(values: object) -> tuple[bytes, ...]:
    if not isinstance(values, list):
        raise ContextPackError("items must be a list of Base64 strings")
    decoded: list[bytes] = []
    for value in values:
        if not isinstance(value, str):
            raise ContextPackError("items must be a list of Base64 strings")
        try:
            decoded.append(base64.b64decode(value.encode("ascii"), validate=True))
        except (binascii.Error, UnicodeEncodeError) as error:
            raise ContextPackError("items must be valid Base64 strings") from error
    return tuple(decoded)


def _looks_like_digest(value: object) -> bool:
    if not isinstance(value, str) or not value.startswith("sha256:"):
        return False
    suffix = value[len("sha256:") :]
    return len(suffix) == 64 and all(character in "0123456789abcdef" for character in suffix)


def _pack_digest(items: tuple[bytes, ...]) -> str:
    unsigned = {"schema": CONTEXT_PACK_SCHEMA, "items": _encode_items(items)}
    return "sha256:" + hashlib.sha256(_canonical(unsigned)).hexdigest()


def _pack_bytes(items: tuple[bytes, ...], digest: str, byte_count: int) -> bytes:
    return _canonical(
        {
            "schema": CONTEXT_PACK_SCHEMA,
            "items": _encode_items(items),
            "digest": digest,
            "byte_count": byte_count,
        }
    )


@dataclass(frozen=True, slots=True)
class ContextPack:
    """A complete context body split into ordered, UTF-8 safe chunks."""

    items: tuple[bytes, ...]
    digest: str
    byte_count: int

    @classmethod
    def build(cls, items: tuple[bytes, ...], /) -> ContextPack:
        chunks = tuple(bytes(item) for item in items)
        digest = _pack_digest(chunks)
        size = 0
        for _ in range(16):
            rendered = _pack_bytes(chunks, digest, size)
            if len(rendered) == size:
                return cls(items=chunks, digest=digest, byte_count=size)
            size = len(rendered)
        raise ContextPackError("context pack byte_count did not converge")

    @classmethod
    def from_content(cls, content: str | bytes, *, chunk_bytes: int = _DEFAULT_CHUNK_BYTES) -> ContextPack:
        if not isinstance(chunk_bytes, int) or isinstance(chunk_bytes, bool) or chunk_bytes < 1:
            raise ContextPackError("chunk_bytes must be a positive integer")
        if isinstance(content, str):
            raw = content.encode("utf-8")
        elif isinstance(content, bytes):
            raw = content
        else:
            raise ContextPackError("content must be text or bytes")
        return cls.build(_chunk_utf8(raw, chunk_bytes))

    def to_bytes(self) -> bytes:
        return _pack_bytes(self.items, self.digest, self.byte_count)

    @classmethod
    def from_bytes(cls, data: bytes, /) -> ContextPack:
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ContextPackError("context pack must be valid JSON") from error
        if not isinstance(payload, dict) or set(payload) != {"schema", "items", "digest", "byte_count"}:
            raise ContextPackError("context pack must contain exactly schema, items, digest and byte_count")
        if payload["schema"] != CONTEXT_PACK_SCHEMA:
            raise ContextPackError("context pack schema mismatch")
        items = _decode_items(payload["items"])
        digest = payload["digest"]
        if not _looks_like_digest(digest) or _pack_digest(items) != digest:
            raise ContextPackError("context pack digest mismatch")
        byte_count = payload["byte_count"]
        if not isinstance(byte_count, int) or isinstance(byte_count, bool):
            raise ContextPackError("context pack byte_count must be an integer")
        if byte_count != len(data):
            raise ContextPackError("context pack byte_count mismatch")
        return cls(items=items, digest=digest, byte_count=byte_count)


def _chunk_utf8(raw: bytes, chunk_bytes: int) -> tuple[bytes, ...]:
    if not raw:
        return ()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ContextPackError("content must be valid UTF-8") from error
    chunks: list[bytes] = []
    current = bytearray()
    for character in text:
        encoded = character.encode("utf-8")
        if len(encoded) > chunk_bytes:
            raise ContextPackError("a single character exceeds the chunk byte limit")
        if len(current) + len(encoded) > chunk_bytes:
            chunks.append(bytes(current))
            current = bytearray()
        current.extend(encoded)
    if current:
        chunks.append(bytes(current))
    return tuple(chunks)


def _delta_bytes(delta: "ContextPackDelta") -> bytes:
    return _canonical(
        {
            "schema": CONTEXT_PACK_DELTA_SCHEMA,
            "base_digest": delta.base_digest,
            "target_digest": delta.target_digest,
            "prefix_items": delta.prefix_items,
            "appended": _encode_items(delta.appended),
        }
    )


@dataclass(frozen=True, slots=True)
class ContextPackDelta:
    """A prefix reuse plus the target suffix that rebuilds one Context Pack."""

    base_digest: str
    target_digest: str
    prefix_items: int
    appended: tuple[bytes, ...]

    @property
    def byte_count(self) -> int:
        return len(_delta_bytes(self))

    @classmethod
    def between(cls, base: ContextPack, target: ContextPack, /) -> ContextPackDelta:
        limit = min(len(base.items), len(target.items))
        prefix = 0
        while prefix < limit and base.items[prefix] == target.items[prefix]:
            prefix += 1
        return cls(
            base_digest=base.digest,
            target_digest=target.digest,
            prefix_items=prefix,
            appended=target.items[prefix:],
        )

    def to_bytes(self) -> bytes:
        return _delta_bytes(self)

    @classmethod
    def from_bytes(cls, data: bytes, /) -> ContextPackDelta:
        try:
            payload = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ContextPackError("context pack delta must be valid JSON") from error
        if not isinstance(payload, dict) or set(payload) != {
            "schema",
            "base_digest",
            "target_digest",
            "prefix_items",
            "appended",
        }:
            raise ContextPackError("context pack delta must contain exactly the documented fields")
        if payload["schema"] != CONTEXT_PACK_DELTA_SCHEMA:
            raise ContextPackError("context pack delta schema mismatch")
        base_digest = payload["base_digest"]
        target_digest = payload["target_digest"]
        if not _looks_like_digest(base_digest) or not _looks_like_digest(target_digest):
            raise ContextPackError("context pack delta digests must be sha256 digests")
        prefix_items = payload["prefix_items"]
        if not isinstance(prefix_items, int) or isinstance(prefix_items, bool) or prefix_items < 0:
            raise ContextPackError("prefix_items must be a non-negative integer")
        appended = _decode_items(payload["appended"])
        return cls(
            base_digest=base_digest,
            target_digest=target_digest,
            prefix_items=prefix_items,
            appended=appended,
        )


def apply_context_pack_delta(base: ContextPack, delta: ContextPackDelta, /) -> ContextPack:
    """Validate one delta against its base pack and rebuild the target pack."""

    if not isinstance(base, ContextPack) or not isinstance(delta, ContextPackDelta):
        raise ContextPackError("apply requires a ContextPack and a ContextPackDelta")
    if base.digest != delta.base_digest:
        raise ContextPackError("delta base digest does not match the base pack")
    if delta.prefix_items > len(base.items):
        raise ContextPackError("delta prefix exceeds the base chunk count")
    rebuilt = ContextPack.build((*base.items[: delta.prefix_items], *delta.appended))
    if rebuilt.digest != delta.target_digest:
        raise ContextPackError("delta target digest does not match the rebuilt pack")
    return rebuilt


__all__ = [
    "CONTEXT_PACK_DELTA_SCHEMA",
    "CONTEXT_PACK_SCHEMA",
    "ContextPack",
    "ContextPackDelta",
    "ContextPackError",
    "apply_context_pack_delta",
]
