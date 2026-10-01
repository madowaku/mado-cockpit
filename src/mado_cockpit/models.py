from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class Project:
    id: str
    name: str
    root: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Mission:
    id: str
    title: str
    status: str = "created"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Worker:
    id: str
    role: str
    mission_id: str | None = None
    provider: str = "unassigned"
    status: str = "created"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Workspace:
    id: str
    worker_id: str
    mission_id: str | None
    repo_root: str
    path: str
    branch: str
    base_ref: str
    kind: str = "git_worktree"
    status: str = "ready"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class AgentSession:
    id: str
    worker_id: str
    workspace_id: str
    provider: str
    model: str | None = None
    external_session_id: str | None = None
    status: str = "created"
    turn_count: int = 0
    last_exit_code: int | None = None
    last_message: str | None = None
    last_trace: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TaskContract:
    id: str
    worker_id: str
    workspace_id: str
    objective: str
    required_evidence: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    done_when: list[str] = field(default_factory=list)
    status: str = "assigned"
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceItem:
    id: str
    kind: str
    path: str
    sha256: str
    size_bytes: int
    source: str
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvidenceBundle:
    id: str
    task_id: str
    worker_id: str
    workspace_id: str
    status: str
    required_evidence: list[str]
    missing_evidence: list[str]
    items: list[EvidenceItem]
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ResultContract:
    id: str
    task_id: str
    worker_id: str
    workspace_id: str
    status: str
    summary: str
    evidence_bundle_id: str
    evidence_status: str
    readiness: str
    missing_evidence: list[str] = field(default_factory=list)
    changes: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    session_id: str | None = None
    submitted_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Event:
    type: str
    subject: dict[str, Any]
    mission_id: str | None = None
    actor: str = "human"
    id: str = field(default_factory=lambda: f"evt_{uuid4().hex[:12]}")
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
