"""Source lifecycle propagation over one Scope's evidence dependency DAG.

A caller registers Sources, the Memory entries and Topic Memory Artifacts derived
from them, and the support policy for each derived node. Availability changes
then propagate from a Source to every descendant: unsupported Memory entries are
deactivated (their bodies stay readable through the original citation) and
unsupported Topic Memory artifacts leave the native Topic search. Restoring a
Source reactivates exactly the nodes that regain support.

The graph is persisted next to the Runtime's other relational state so a restart
re-derives the same availability, and every write is idempotent so replaying a
successful event never adds a Memory revision while retrying an interrupted one
finishes the propagation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, insert, select

from powercontext.artifacts import ArtifactRef, MemoryCitation
from powercontext.builtin.artifacts.memory import MemoryService
from powercontext.builtin.artifacts.topic_memory import TopicMemory
from powercontext.builtin.persistence.artifact_governance import (
    ArtifactGovernanceRepository,
    ArtifactLifecycleState,
)
from powercontext.builtin.persistence.tables import SOURCE_LIFECYCLE_NODE_TABLE
from powercontext.builtin.sources import validate_scope_id
from powercontext.sources import SourceRef

if TYPE_CHECKING:  # pragma: no cover - typing only, keeps the Runtime import graph acyclic
    from powercontext.builtin.persistence.database import AsyncDatabase
    from powercontext.builtin.runtime.application import BuiltinRuntime

MAX_LIFECYCLE_NODE_ID_LENGTH = 128
PURPOSES = frozenset({"generation", "audit"})
POLICIES = frozenset({"all", "any"})
DERIVED_KINDS = frozenset({"memory", "topic"})

_REFERENCE_TYPES: dict[str, type[BaseModel]] = {
    "source": SourceRef,
    "memory": MemoryCitation,
    "topic": ArtifactRef,
}


class SourceLifecycleError(ValueError):
    """Raised when a lifecycle registration, event, or query breaks the contract."""


class SourceLifecycleEvent(BaseModel):
    """One authoritative availability change for a registered Source."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str
    reason: str
    revision: int = Field(gt=0, strict=True)
    sequence: int = Field(gt=0, strict=True)
    available: bool = Field(strict=True)

    @field_validator("node_id", "reason")
    @classmethod
    def _require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")  # noqa: TRY003
        return value


@dataclass(frozen=True)
class _Node:
    """One persisted graph node, before availability is derived."""

    node_id: str
    kind: str
    reference: BaseModel
    parents: tuple[str, ...]
    policy: str
    revision: int | None = None
    sequence: int | None = None
    available: bool | None = None
    reason: str | None = None
    digest: str | None = None


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _event_digest(revision: int, sequence: int, available: bool, reason: str) -> str:
    return hashlib.sha256(_canonical_json([revision, sequence, available, reason])).hexdigest()


def _decode_reference(kind: str, payload: bytes) -> BaseModel:
    return _REFERENCE_TYPES[kind].model_validate(json.loads(payload.decode("utf-8")))


def _propagate(nodes: dict[str, _Node], /) -> set[str]:
    """Return the node ids supported by the recorded Source states."""

    # A Source is available from registration until an event says otherwise, so an
    # absent availability (no event applied yet) counts as supported.
    active = {node.node_id for node in nodes.values() if node.kind == "source" and node.available is not False}
    pending = [node for node in nodes.values() if node.kind in DERIVED_KINDS]
    changed = True
    while changed:
        changed = False
        for node in pending:
            if node.node_id in active:
                continue
            support = [parent in active for parent in node.parents]
            if all(support) if node.policy == "all" else any(support):
                active.add(node.node_id)
                changed = True
    return active


class ScopedSourceLifecycle:
    """Register dependency evidence and propagate Source availability in one Scope."""

    def __init__(self, application: SourceLifecycleApplication, scope_id: str) -> None:
        self._application = application
        self.scope_id = validate_scope_id(scope_id)

    async def register_source(self, node_id: str, source_ref: SourceRef, *, revision: int) -> None:
        """Register one Source at the lifecycle revision its events must match."""

        self._require_node_id(node_id)
        if not isinstance(source_ref, SourceRef):
            raise SourceLifecycleError("source_ref must be a captured SourceRef")
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
            raise SourceLifecycleError("revision must be a positive integer")
        records = self._application.runtime.records.for_scope(self.scope_id)
        try:
            await records.get_source(source_ref.source_type, source_ref.source_id)
        except Exception as error:
            raise SourceLifecycleError(f"source {source_ref.source_id!r} is not readable") from error
        await self._register(
            _Node(
                node_id=node_id,
                kind="source",
                reference=source_ref,
                parents=(),
                policy="all",
                revision=revision,
            )
        )

    async def register_memory(
        self,
        node_id: str,
        citation: MemoryCitation,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        """Register one Memory entry derived from already registered nodes."""

        self._require_node_id(node_id)
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("citation must be a MemoryCitation")
        resolved_parents = self._require_parents(node_id, parents)
        resolved_policy = self._require_policy(policy)
        async with self._application.runtime._context(self.scope_id) as context:
            try:
                await context.artifacts.memory.validate_citation(citation)
            except Exception as error:
                raise SourceLifecycleError("memory citation is not readable") from error
        await self._register(
            _Node(
                node_id=node_id,
                kind="memory",
                reference=citation,
                parents=resolved_parents,
                policy=resolved_policy,
            )
        )

    async def register_topic(
        self,
        node_id: str,
        artifact: ArtifactRef,
        *,
        parents: tuple[str, ...],
        policy: str,
    ) -> None:
        """Register one Topic Memory artifact derived from already registered nodes."""

        self._require_node_id(node_id)
        if not isinstance(artifact, ArtifactRef):
            raise SourceLifecycleError("artifact must be an ArtifactRef")
        if artifact.family != TopicMemory.family:
            raise SourceLifecycleError("artifact must belong to the topic-memory family")
        resolved_parents = self._require_parents(node_id, parents)
        resolved_policy = self._require_policy(policy)
        records = self._application.runtime.records.for_scope(self.scope_id)
        try:
            await records.get_artifact_revision(artifact.family, artifact.artifact_id, artifact.revision)
        except Exception as error:
            raise SourceLifecycleError("topic artifact revision is not readable") from error
        await self._register(
            _Node(
                node_id=node_id,
                kind="topic",
                reference=artifact,
                parents=resolved_parents,
                policy=resolved_policy,
            )
        )

    async def apply(self, event: SourceLifecycleEvent, /) -> list[str]:
        """Persist one Source event, propagate it, and return the sorted active nodes."""

        if not isinstance(event, SourceLifecycleEvent):
            raise SourceLifecycleError("event must be a SourceLifecycleEvent")
        runtime = self._application.runtime
        async with runtime._context(self.scope_id) as context, runtime._locked(self.scope_id):
            nodes = await self._load()
            node = nodes.get(event.node_id)
            if node is None or node.kind != "source":
                raise SourceLifecycleError(f"unknown Source {event.node_id!r}")
            if node.revision != event.revision:
                raise SourceLifecycleError(
                    f"revision {event.revision} does not match the registered revision {node.revision}"
                )
            digest = _event_digest(event.revision, event.sequence, event.available, event.reason)
            replay = False
            if node.sequence is not None:
                if event.sequence < node.sequence:
                    raise SourceLifecycleError(
                        f"sequence {event.sequence} is older than the recorded sequence {node.sequence}"
                    )
                if event.sequence == node.sequence:
                    if node.digest != digest:
                        raise SourceLifecycleError(
                            f"sequence {event.sequence} was already recorded with different content"
                        )
                    replay = True
            if not replay:
                updated = _Node(
                    node_id=node.node_id,
                    kind=node.kind,
                    reference=node.reference,
                    parents=node.parents,
                    policy=node.policy,
                    revision=node.revision,
                    sequence=event.sequence,
                    available=event.available,
                    reason=event.reason,
                    digest=digest,
                )
                await self._store(updated)
                nodes[node.node_id] = updated
            active = _propagate(nodes)
            # A replay still reconciles: a failed native write may have interrupted
            # the first attempt, and every step is a no-op when already settled.
            await self._reconcile(context, nodes, active)
        return sorted(active)

    async def resolve(self, node_id: str, /, *, purpose: str) -> BaseModel:
        """Return the registered reference, or refuse generation of unsupported nodes."""

        if purpose not in PURPOSES:
            raise SourceLifecycleError(f"unknown purpose {purpose!r}")
        nodes = await self._load()
        node = nodes.get(node_id)
        if node is None:
            raise SourceLifecycleError(f"unknown node {node_id!r}")
        if purpose == "generation" and node_id not in _propagate(nodes):
            raise SourceLifecycleError(f"node {node_id!r} has no current support")
        return node.reference

    async def _register(self, node: _Node) -> None:
        runtime = self._application.runtime
        async with runtime._context(self.scope_id) as context, runtime._locked(self.scope_id):
            nodes = await self._load()
            existing = nodes.get(node.node_id)
            if existing is not None:
                if not _same_binding(existing, node):
                    raise SourceLifecycleError(f"node {node.node_id!r} is already registered differently")
                return
            for parent in node.parents:
                if parent not in nodes:
                    raise SourceLifecycleError(f"parent {parent!r} is not registered yet")
            await self._store(node)
            nodes[node.node_id] = node
            # Registration must publish the derived state immediately instead of
            # leaving the node usable until an unrelated event arrives.
            active = _propagate(nodes)
            await self._reconcile(context, nodes, active)

    async def _load(self) -> dict[str, _Node]:
        database: AsyncDatabase = self._application.database
        async with database.transaction() as connection:
            rows = (
                await connection.execute(
                    select(SOURCE_LIFECYCLE_NODE_TABLE).where(
                        SOURCE_LIFECYCLE_NODE_TABLE.c.scope_id == self.scope_id
                    )
                )
            ).mappings()
            return {str(row["node_id"]): _node_from_row(row) for row in rows}

    async def _store(self, node: _Node) -> None:
        database: AsyncDatabase = self._application.database
        async with database.transaction() as connection:
            await connection.execute(
                delete(SOURCE_LIFECYCLE_NODE_TABLE).where(
                    SOURCE_LIFECYCLE_NODE_TABLE.c.scope_id == self.scope_id,
                    SOURCE_LIFECYCLE_NODE_TABLE.c.node_id == node.node_id,
                )
            )
            await connection.execute(
                insert(SOURCE_LIFECYCLE_NODE_TABLE).values(
                    scope_id=self.scope_id,
                    node_id=node.node_id,
                    kind=node.kind,
                    reference=_canonical_json(node.reference.model_dump(mode="json")),
                    parents=_canonical_json(list(node.parents)),
                    policy=node.policy,
                    revision=node.revision,
                    sequence=node.sequence,
                    available=node.available,
                    reason=node.reason,
                    digest=node.digest,
                )
            )

    async def _reconcile(self, context: Any, nodes: dict[str, _Node], active: set[str]) -> None:
        derived = [node for node in nodes.values() if node.kind in DERIVED_KINDS]
        if not derived:
            return
        memory = context.artifacts.memory
        for node in derived:
            supported = node.node_id in active
            if node.kind == "memory":
                await self._reconcile_memory(memory, node, supported)
            else:
                await self._reconcile_topic(node, supported)

    async def _reconcile_memory(self, memory: MemoryService, node: _Node, supported: bool) -> None:
        citation = node.reference
        if not isinstance(citation, MemoryCitation):
            raise SourceLifecycleError("registered memory node lost its citation")
        current = await memory.head(citation.memory_ref.artifact_id)
        states = {item.entry_id: item.state for item in current.content.manifest.entries}
        state = states.get(citation.entry_id)
        if state is None:
            raise SourceLifecycleError(f"memory entry {citation.entry_id!r} is no longer present")
        target = "active" if supported else "inactive"
        if state == target:
            return
        entry = await memory.validate_citation(citation)
        if supported:
            await memory.reactivate(current, entries=(entry,), reason=node.node_id)
        else:
            await memory.forget(current, entries=(entry,), reason=node.node_id)

    async def _reconcile_topic(self, node: _Node, supported: bool) -> None:
        artifact = node.reference
        if not isinstance(artifact, ArtifactRef):
            raise SourceLifecycleError("registered topic node lost its artifact reference")
        target = ArtifactLifecycleState.ACTIVE if supported else ArtifactLifecycleState.DEPRECATED
        database: AsyncDatabase = self._application.database
        governance: ArtifactGovernanceRepository = self._application.governance
        async with database.transaction() as connection:
            current = await governance.get(connection, self.scope_id, TopicMemory.family, artifact.artifact_id)
            if current.lifecycle_state is target:
                return
            await governance.transition(
                connection,
                self.scope_id,
                TopicMemory.family,
                artifact.artifact_id,
                current.governance_generation,
                target,
                None,
            )

    @staticmethod
    def _require_node_id(node_id: str) -> None:
        if not isinstance(node_id, str) or not node_id.strip():
            raise SourceLifecycleError("node_id must be a non-blank string")
        if len(node_id) > MAX_LIFECYCLE_NODE_ID_LENGTH:
            raise SourceLifecycleError(f"node_id must not exceed {MAX_LIFECYCLE_NODE_ID_LENGTH} characters")

    @staticmethod
    def _require_parents(node_id: str, parents: tuple[str, ...]) -> tuple[str, ...]:
        if isinstance(parents, str) or not isinstance(parents, (tuple, list)):
            raise SourceLifecycleError("parents must be a sequence of node ids")
        resolved = tuple(parents)
        if not resolved:
            raise SourceLifecycleError("a derived node needs at least one parent")
        if any(not isinstance(parent, str) or not parent.strip() for parent in resolved):
            raise SourceLifecycleError("parents must be non-blank strings")
        if node_id in resolved:
            raise SourceLifecycleError("a node cannot depend on itself")
        if len(set(resolved)) != len(resolved):
            raise SourceLifecycleError("parents must not repeat")
        return resolved

    @staticmethod
    def _require_policy(policy: str) -> str:
        if policy not in POLICIES:
            raise SourceLifecycleError("policy must be 'all' or 'any'")
        return policy


class SourceLifecycleApplication:
    """Select the scoped Source lifecycle service."""

    def __init__(
        self,
        runtime: BuiltinRuntime,
        database: AsyncDatabase,
        governance: ArtifactGovernanceRepository,
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.governance = governance

    def for_scope(self, scope_id: str, /) -> ScopedSourceLifecycle:
        return ScopedSourceLifecycle(self, scope_id)


def _same_binding(left: _Node, right: _Node) -> bool:
    return (
        left.kind == right.kind
        and left.policy == right.policy
        and left.parents == right.parents
        and left.revision == right.revision
        and left.reference.model_dump(mode="json") == right.reference.model_dump(mode="json")
    )


def _node_from_row(row: Any) -> _Node:
    kind = str(row["kind"])
    return _Node(
        node_id=str(row["node_id"]),
        kind=kind,
        reference=_decode_reference(kind, bytes(row["reference"])),
        parents=tuple(json.loads(bytes(row["parents"]).decode("utf-8"))),
        policy=str(row["policy"]),
        revision=None if row["revision"] is None else int(row["revision"]),
        sequence=None if row["sequence"] is None else int(row["sequence"]),
        available=None if row["available"] is None else bool(row["available"]),
        reason=None if row["reason"] is None else str(row["reason"]),
        digest=None if row["digest"] is None else str(row["digest"]),
    )


__all__ = [
    "ScopedSourceLifecycle",
    "SourceLifecycleApplication",
    "SourceLifecycleError",
    "SourceLifecycleEvent",
]
