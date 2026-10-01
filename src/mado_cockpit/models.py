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
class HandoffContract:
    id: str
    source_task_id: str
    source_result_id: str
    source_bundle_id: str
    source_worker_id: str
    source_workspace_id: str
    qa_worker_id: str
    qa_workspace_id: str
    qa_task_id: str
    snapshot_path: str
    snapshot_sha256: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class QAVerdict:
    id: str
    handoff_id: str
    qa_task_id: str
    qa_result_id: str
    qa_worker_id: str
    verdict: str
    summary: str
    source_snapshot_sha256: str
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityDescriptor:
    id: str
    kind: str
    name: str
    short_description: str
    availability: str
    full_description: str | None = None
    instructions_ref: str | None = None
    prerequisites: list[str] = field(default_factory=list)
    risk_tags: list[str] = field(default_factory=list)
    cost_class: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityRequest:
    id: str
    worker_id: str
    request: str
    trace_id: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilitySuggestion:
    suggested_capability: str | None
    confidence: float
    alternatives: list[str]
    reason_codes: list[str]
    advisory_only: bool
    wide_trace_id: str
    deep_trace_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityResolution:
    id: str
    request_id: str
    worker_id: str
    status: str
    selected_capability: str | None
    suggestion: CapabilitySuggestion
    policy_reasons: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CapabilityBinding:
    id: str
    worker_id: str
    capability_id: str
    resolution_id: str
    status: str = "bound"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperatorPlan:
    id: str
    mission_id: str
    objective: str
    builder_worker_id: str
    qa_worker_id: str
    builder_task_id: str
    provider: str
    required_evidence: list[str]
    base_ref: str = "HEAD"
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperatorState:
    operator_id: str
    status: str = "prepared"
    handoff_id: str | None = None
    builder_session_id: str | None = None
    qa_session_id: str | None = None
    last_action: str | None = None
    last_error: str | None = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

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
