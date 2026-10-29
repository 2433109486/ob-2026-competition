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

"""Capture the complete raw event history of one selected Pi session branch."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from pydantic import BaseModel, Field, JsonValue

from powercontext.limits import MAX_SOURCE_ID_LENGTH
from powercontext.sources.connectors import ConnectorRunCompletion, ConnectorRunStatus, ConnectorRunSession
from powercontext.sources.definitions import AdapterSourceDefinition
from powercontext.sources.models import Source, SourceMaterialization
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY, TextEvidence

PI_EVENT_SOURCE_NAME = "pi-event"
PI_EVENT_SOURCE_VERSION = "1"
PI_SESSION_CONNECTOR_NAME = "pi-session-history"
PI_SESSION_CONNECTOR_VERSION = "1"
_CHECKPOINT_SCHEMA = "powercontext.pi-session-history.v1"

_CONTROL_TYPES = frozenset(
    {
        "session",
        "model_change",
        "thinking_level_change",
        "label",
        "custom",
        "metadata",
    }
)


class PiSessionInput(BaseModel):
    """One complete Pi v3 JSONL archive plus the selected leaf node."""

    content: bytes
    leaf_id: str | None = None


class PiEventInput(BaseModel):
    """One visible event of a selected Pi branch with its complete raw record."""

    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue] = Field(default_factory=dict)


class PiEventSource(Source):
    """A captured, immutable Pi event."""

    source_id: str
    session_id: str
    event_id: str
    parent_id: str | None = None
    event_type: str
    role: str
    content: str
    record: dict[str, JsonValue]


def _decode_jsonl(content: bytes) -> list[dict[str, Any]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("Pi session content must be valid UTF-8") from error
    records: list[dict[str, Any]] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError("Pi session content must be valid JSONL") from error
        if not isinstance(record, dict):
            raise ValueError("Pi session records must be JSON objects")
        records.append(record)
    return records


def _text_body(content: object) -> str:
    """Render message content blocks as visible text, dropping thinking and images."""

    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                parts.append(text)
        elif block_type == "toolCall":
            name = block.get("name") if isinstance(block.get("name"), str) else "unknown"
            call_id = block.get("id") if isinstance(block.get("id"), str) else "unknown"
            arguments = block.get("arguments")
            rendered = json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            parts.append(f"[tool_call {name} {call_id}] {rendered}")
    return "\n".join(parts)


def _event_body(record: dict[str, Any]) -> tuple[str, str] | None:
    """Return ``(role, body)`` for a visible record, or ``None`` for a control node."""

    record_type = record.get("type")
    if record_type == "message":
        message = record.get("message")
        if not isinstance(message, dict):
            return None
        role = message.get("role")
        if not isinstance(role, str):
            return None
        if role == "toolResult":
            tool_name = message.get("toolName")
            call_id = message.get("toolCallId")
            text = _text_body(message.get("content"))
            return role, f"[tool_result {tool_name if isinstance(tool_name, str) else 'unknown'} {call_id if isinstance(call_id, str) else 'unknown'}] {text}"
        if role == "bashExecution":
            command = message.get("command")
            output = message.get("output")
            body = f"$ {command if isinstance(command, str) else ''}\n{output if isinstance(output, str) else ''}"
            return role, body
        body = _text_body(message.get("content"))
        return (role, body) if body else None
    if record_type in ("compaction", "branch_summary"):
        summary = record.get("summary")
        body = summary if isinstance(summary, str) else ""
        return (record_type, body) if body else None
    if record_type == "custom_message":
        body = _text_body(record.get("content"))
        return ("custom", body) if body else None
    return None


def _event_digest(event: PiEventInput) -> str:
    payload = json.dumps(
        {
            "session_id": event.session_id,
            "event_id": event.event_id,
            "parent_id": event.parent_id,
            "event_type": event.event_type,
            "role": event.role,
            "content": event.content,
            "record": event.record,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_pi_session(value: PiSessionInput) -> tuple[PiEventInput, ...]:
    """Parse the full ancestor chain of the selected Pi session leaf."""

    records = _decode_jsonl(value.content)
    if not records:
        raise ValueError("Pi session archive must start with a session header")
    header = records[0]
    if header.get("type") != "session":
        raise ValueError("Pi session archive must start with a session record")
    if header.get("version") != 3:
        raise ValueError("Pi session version must be 3")
    session_id = header.get("id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("Pi session header must declare a non-empty id")

    nodes: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    parents: dict[str, str | None] = {}
    for record in records[1:]:
        event_id = record.get("id")
        if not isinstance(event_id, str) or not event_id.strip():
            raise ValueError("Pi session records must declare a non-empty id")
        if event_id in nodes:
            raise ValueError("Pi session record ids must be unique")
        parent_id = record.get("parentId")
        if parent_id is not None:
            if not isinstance(parent_id, str) or parent_id not in nodes:
                raise ValueError("Pi session parentId must reference an earlier record")
        nodes[event_id] = record
        parents[event_id] = parent_id
        order.append(event_id)

    if not order:
        raise ValueError("Pi session archive must contain at least one node")

    leaf_id = value.leaf_id if value.leaf_id is not None else order[-1]
    if leaf_id not in nodes:
        raise ValueError("Pi session leaf id does not exist")

    chain: list[str] = []
    current: str | None = leaf_id
    while current is not None:
        chain.append(current)
        current = parents[current]
    chain.reverse()

    events: list[PiEventInput] = []
    for event_id in chain:
        record = nodes[event_id]
        rendered = _event_body(record)
        if rendered is None:
            continue
        role, body = rendered
        events.append(
            PiEventInput(
                session_id=session_id,
                event_id=event_id,
                parent_id=parents[event_id],
                event_type=str(record.get("type")),
                role=role,
                content=f"{role}: {body}",
                record=record,
            )
        )
    return tuple(events)


def pi_event_source_id(session_id: str, event_id: str) -> str:
    """Build the stable Source identity of one Pi session event."""

    source_id = "pi:{session}:{event}".format(
        session=quote(session_id, safe=""),
        event=quote(event_id, safe=""),
    )
    if len(source_id) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"Pi event Source identity must not exceed {MAX_SOURCE_ID_LENGTH} characters")
    return source_id


class PiEventSourceAdapter:
    """Resolve and read one Pi event Source."""

    input_class = PiEventInput
    name = PI_EVENT_SOURCE_NAME
    source_class = PiEventSource

    async def resolve(self, value: PiEventInput, /) -> PiEventSource:
        source_id = pi_event_source_id(value.session_id, value.event_id)
        return PiEventSource(
            name=source_id,
            source_id=source_id,
            definition_version=PI_EVENT_SOURCE_VERSION,
            materialization=SourceMaterialization.CAPTURED,
            session_id=value.session_id,
            event_id=value.event_id,
            parent_id=value.parent_id,
            event_type=value.event_type,
            role=value.role,
            content=value.content,
            record=value.record,
        )

    async def read(self, source: PiEventSource, /) -> PiEventInput:
        return PiEventInput(
            session_id=source.session_id,
            event_id=source.event_id,
            parent_id=source.parent_id,
            event_type=source.event_type,
            role=source.role,
            content=source.content,
            record=source.record,
        )


class PiEventTextEvidenceProjection:
    """Project one Pi event as the standard textual evidence shape."""

    name = TEXT_EVIDENCE_PROJECTION_KEY.name
    version = TEXT_EVIDENCE_PROJECTION_KEY.version
    source_class = PiEventSource
    output_class: type[BaseModel] = TextEvidence

    def project(self, source: PiEventSource, /) -> TextEvidence:
        return TextEvidence(
            source_type=PI_EVENT_SOURCE_NAME,
            source_id=source.name,
            content=source.content,
            metadata={
                "session_id": source.session_id,
                "event_id": source.event_id,
                "parent_id": source.parent_id,
                "event_type": source.event_type,
                "role": source.role,
            },
        )


PI_EVENT_SOURCE_ADAPTER = PiEventSourceAdapter()
PI_EVENT_SOURCE_DEFINITION = AdapterSourceDefinition(
    PI_EVENT_SOURCE_ADAPTER,
    version=PI_EVENT_SOURCE_VERSION,
    projections=(PiEventTextEvidenceProjection(),),
)


class PiSessionConnector:
    """Incrementally capture the visible events of one selected Pi branch."""

    name = PI_SESSION_CONNECTOR_NAME
    version = PI_SESSION_CONNECTOR_VERSION
    source_definitions = frozenset({PI_EVENT_SOURCE_NAME})

    def __init__(self, path: str | Path, leaf_id: str | None = None) -> None:
        self.path = Path(path)
        self.leaf_id = leaf_id

    def _load(self) -> tuple[PiEventInput, ...]:
        return parse_pi_session(PiSessionInput(content=self.path.read_bytes(), leaf_id=self.leaf_id))

    def _split_checkpoint(
        self, checkpoint: JsonValue | None
    ) -> tuple[str | None, dict[str, str]]:
        if checkpoint is None:
            return None, {}
        if not isinstance(checkpoint, dict):
            raise ValueError("Pi session checkpoint must be an object")
        session_id = checkpoint.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("Pi session checkpoint must record the session id")
        entries = checkpoint.get("events")
        if not isinstance(entries, list):
            raise ValueError("Pi session checkpoint must record imported events")
        imported: dict[str, str] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Pi session checkpoint entries must be objects")
            event_id = entry.get("event_id")
            digest = entry.get("digest")
            if not isinstance(event_id, str) or not isinstance(digest, str):
                raise ValueError("Pi session checkpoint entries must record identity and digest")
            imported[event_id] = digest
        return session_id, imported

    async def run(self, session: ConnectorRunSession, /) -> ConnectorRunCompletion:
        events = self._load()
        session_id = events[0].session_id if events else None
        imported_session, imported = self._split_checkpoint(session.checkpoint)
        if imported_session is not None and session_id is not None and imported_session != session_id:
            raise ValueError("Pi session checkpoint belongs to a different session")

        digests = {event.event_id: _event_digest(event) for event in events}
        for event_id, digest in digests.items():
            recorded = imported.get(event_id)
            if recorded is not None and recorded != digest:
                raise ValueError("Pi session event was rewritten after it was captured")

        appended = 0
        for event in events:
            if event.event_id in imported:
                continue
            await session.submit(event.event_id, PI_EVENT_SOURCE_NAME, event)
            appended += 1

        merged = dict(imported)
        merged.update(digests)
        checkpoint = {
            "schema": _CHECKPOINT_SCHEMA,
            "session_id": session_id,
            "events": [
                {"event_id": event_id, "digest": digest} for event_id, digest in merged.items()
            ],
        }
        return ConnectorRunCompletion(
            status=ConnectorRunStatus.COMPLETE,
            checkpoint=checkpoint,
        )


__all__ = [
    "PI_EVENT_SOURCE_ADAPTER",
    "PI_EVENT_SOURCE_DEFINITION",
    "PI_EVENT_SOURCE_NAME",
    "PI_SESSION_CONNECTOR_NAME",
    "PI_SESSION_CONNECTOR_VERSION",
    "PiEventInput",
    "PiEventSource",
    "PiEventSourceAdapter",
    "PiEventTextEvidenceProjection",
    "PiSessionConnector",
    "PiSessionInput",
    "parse_pi_session",
    "pi_event_source_id",
]
