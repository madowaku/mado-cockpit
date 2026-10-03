from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .evidence import EvidenceManager
from .models import Event, Mission, utc_now
from .operator import OperatorManager
from .store import CockpitStore


MISSION_SCHEMA = "mado.mission-envelope.v1"
OUTCOME_SCHEMA = "mado.outcome-envelope.v1"

_REQUIRED_POLICY_KEYS = (
    "allow_paid",
    "allow_publish",
    "allow_delete",
    "allow_external_message",
)


def _non_empty(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{label} must be a non-empty string")
    return value.strip()


def _string_list(value: Any, *, label: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise RuntimeError(f"{label} must be a list")
    result: list[str] = []
    for item in value:
        result.append(_non_empty(item, label=label))
    return list(dict.fromkeys(result))


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class MissionEnvelope:
    schema_version: str
    mission_id: str
    title: str
    objective: str
    source: dict[str, Any]
    priority: str
    constraints: list[str]
    deliverables: list[str]
    required_evidence: list[str]
    human_decisions: list[Any]
    execution_policy: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "MissionEnvelope":
        if not isinstance(payload, Mapping):
            raise RuntimeError(
                "Mission Envelope must be a JSON object"
            )

        schema_version = _non_empty(
            payload.get("schema_version"),
            label="schema_version",
        )
        if schema_version != MISSION_SCHEMA:
            raise RuntimeError(
                "Unsupported Mission Envelope schema: "
                f"{schema_version}"
            )

        source_value = payload.get("source")
        if not isinstance(source_value, Mapping):
            raise RuntimeError("source must be an object")
        source = dict(source_value)
        source["kind"] = _non_empty(
            source.get("kind"),
            label="source.kind",
        )
        if source.get("revision") is not None:
            source["revision"] = str(
                source["revision"]
            ).strip() or None

        policy_value = payload.get(
            "execution_policy"
        )
        if not isinstance(policy_value, Mapping):
            raise RuntimeError(
                "execution_policy must be an object"
            )
        execution_policy = dict(policy_value)
        for key in _REQUIRED_POLICY_KEYS:
            if key not in execution_policy:
                raise RuntimeError(
                    "execution_policy must explicitly "
                    f"declare {key}"
                )
            if not isinstance(
                execution_policy[key],
                bool,
            ):
                raise RuntimeError(
                    f"execution_policy.{key} must be boolean"
                )

        metadata_value = payload.get(
            "metadata",
            {},
        )
        if not isinstance(metadata_value, Mapping):
            raise RuntimeError("metadata must be an object")
        metadata = dict(metadata_value)

        known = {
            "schema_version",
            "mission_id",
            "title",
            "objective",
            "source",
            "priority",
            "constraints",
            "deliverables",
            "required_evidence",
            "human_decisions",
            "execution_policy",
            "metadata",
        }
        for key, value in payload.items():
            if key not in known:
                metadata.setdefault(key, value)

        human_decisions = payload.get(
            "human_decisions",
            [],
        )
        if not isinstance(human_decisions, list):
            raise RuntimeError(
                "human_decisions must be a list"
            )

        required_evidence = _string_list(
            payload.get("required_evidence"),
            label="required_evidence",
        )
        if not required_evidence:
            raise RuntimeError(
                "Mission Envelope requires at least "
                "one evidence kind"
            )

        return cls(
            schema_version=schema_version,
            mission_id=_non_empty(
                payload.get("mission_id"),
                label="mission_id",
            ),
            title=_non_empty(
                payload.get("title"),
                label="title",
            ),
            objective=_non_empty(
                payload.get("objective"),
                label="objective",
            ),
            source=source,
            priority=_non_empty(
                payload.get("priority", "normal"),
                label="priority",
            ),
            constraints=_string_list(
                payload.get("constraints", []),
                label="constraints",
            ),
            deliverables=_string_list(
                payload.get("deliverables", []),
                label="deliverables",
            ),
            required_evidence=required_evidence,
            human_decisions=list(human_decisions),
            execution_policy=execution_policy,
            metadata=metadata,
        )

    @property
    def revision(self) -> str | None:
        value = self.source.get("revision")
        if value is None:
            return None
        return str(value)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def digest(self) -> str:
        return _canonical_digest(self.to_dict())


@dataclass(slots=True)
class OutcomeEnvelope:
    schema_version: str
    envelope_id: str
    mission_id: str
    status: str
    summary: str
    next_action: str | None
    human_attention: dict[str, Any] | None
    evidence: dict[str, Any]
    qa: dict[str, Any]
    implementation: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ControlPlaneBridge:
    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.control_dir = store.base / "control"
        self.inbox_dir = self.control_dir / "inbox"
        self.outbox_dir = self.control_dir / "outbox"
        self.evidence = EvidenceManager(store)
        self.operators = OperatorManager(store)

    def receive(
        self,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._require_initialized()

        try:
            envelope = MissionEnvelope.from_dict(
                payload
            )
            self._validate_authority(envelope)
        except Exception as exc:
            mission_id = (
                payload.get("mission_id")
                if isinstance(payload, Mapping)
                else None
            )
            self.store.append_event(
                Event(
                    type="control.mission.rejected",
                    mission_id=(
                        mission_id
                        if isinstance(mission_id, str)
                        else None
                    ),
                    actor="control-plane",
                    subject={"error": str(exc)},
                )
            )
            raise

        digest = envelope.digest()
        envelope_id = f"ctl_{digest[:16]}"
        path = self.inbox_dir / envelope_id

        self.store.append_event(
            Event(
                type="control.mission.received",
                mission_id=envelope.mission_id,
                actor="control-plane",
                subject={
                    "envelope_id": envelope_id,
                    "digest": digest,
                    "revision": envelope.revision,
                },
            )
        )

        if path.exists():
            return self.inspect(envelope_id)

        self._validate_revision(envelope, digest)

        path.mkdir(parents=True, exist_ok=False)
        self._write_json(
            path / "mission.json",
            envelope.to_dict(),
        )
        self._write_json(
            path / "status.json",
            {
                "envelope_id": envelope_id,
                "mission_id": envelope.mission_id,
                "revision": envelope.revision,
                "digest": digest,
                "status": "accepted",
                "operator_id": None,
                "received_at": utc_now(),
                "started_at": None,
                "outcome_at": None,
                "outcome_status": None,
                "human_attention_gate_id": None,
            },
        )
        self.store.append_event(
            Event(
                type="control.mission.accepted",
                mission_id=envelope.mission_id,
                actor="cockpit",
                subject={
                    "envelope_id": envelope_id,
                    "digest": digest,
                    "revision": envelope.revision,
                },
            )
        )
        return self.inspect(envelope_id)

    def inspect(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        root = self._inbox_root(envelope_id)
        outcome_path = (
            self.outbox_dir
            / envelope_id
            / "outcome.json"
        )
        return {
            "envelope": self._read_json(
                root / "mission.json"
            ),
            "status": self._read_json(
                root / "status.json"
            ),
            "outcome": (
                self._read_json(outcome_path)
                if outcome_path.exists()
                else None
            ),
        }

    def start(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        root = self._inbox_root(envelope_id)
        envelope = MissionEnvelope.from_dict(
            self._read_json(root / "mission.json")
        )
        status = self._read_json(
            root / "status.json"
        )

        operator_id = status.get("operator_id")
        if operator_id:
            return {
                **self.inspect(envelope_id),
                "operator": self.operators.inspect(
                    str(operator_id)
                ),
            }

        try:
            self.store.get_mission(
                envelope.mission_id
            )
        except RuntimeError as exc:
            if "Mission not found:" not in str(exc):
                raise
            self.store.save_mission(
                Mission(
                    id=envelope.mission_id,
                    title=envelope.title,
                )
            )

        run = self.operators.start(
            envelope.mission_id,
            envelope.objective,
            required_evidence=(
                envelope.required_evidence
            ),
            constraints=envelope.constraints,
            deliverables=envelope.deliverables,
        )
        operator_id = str(run["plan"]["id"])
        status.update(
            {
                "status": "started",
                "operator_id": operator_id,
                "started_at": utc_now(),
            }
        )
        self._write_json(
            root / "status.json",
            status,
        )
        return {
            **self.inspect(envelope_id),
            "operator": run,
        }

    def outcome(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        root = self._inbox_root(envelope_id)
        envelope = MissionEnvelope.from_dict(
            self._read_json(root / "mission.json")
        )
        status = self._read_json(
            root / "status.json"
        )
        operator_id = status.get("operator_id")
        if not operator_id:
            raise RuntimeError(
                "Mission Envelope has not started"
            )

        run = self.operators.inspect(
            str(operator_id)
        )
        outcome = self._compile_outcome(
            envelope_id,
            envelope,
            run,
        )
        outbox = (
            self.outbox_dir / envelope_id
        )
        outbox.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._write_json(
            outbox / "outcome.json",
            outcome.to_dict(),
        )

        previous_gate = status.get(
            "human_attention_gate_id"
        )
        current_gate = (
            outcome.human_attention or {}
        ).get("gate_id")
        if current_gate and current_gate != previous_gate:
            self.store.append_event(
                Event(
                    type=(
                        "control.human_attention."
                        "requested"
                    ),
                    mission_id=envelope.mission_id,
                    actor="cockpit",
                    subject={
                        "envelope_id": envelope_id,
                        "gate_id": current_gate,
                    },
                )
            )
        if previous_gate and not current_gate:
            self.store.append_event(
                Event(
                    type=(
                        "control.human_attention."
                        "resolved"
                    ),
                    mission_id=envelope.mission_id,
                    actor="cockpit",
                    subject={
                        "envelope_id": envelope_id,
                        "gate_id": previous_gate,
                    },
                )
            )

        status.update(
            {
                "outcome_at": utc_now(),
                "outcome_status": outcome.status,
                "human_attention_gate_id": (
                    current_gate
                ),
            }
        )
        self._write_json(
            root / "status.json",
            status,
        )
        self.store.append_event(
            Event(
                type="control.outcome.compiled",
                mission_id=envelope.mission_id,
                actor="cockpit",
                subject={
                    "envelope_id": envelope_id,
                    "digest": status["digest"],
                    "status": outcome.status,
                },
            )
        )
        return outcome.to_dict()

    def _compile_outcome(
        self,
        envelope_id: str,
        envelope: MissionEnvelope,
        run: dict[str, Any],
    ) -> OutcomeEnvelope:
        state = run["state"]
        handoff = run.get("handoff")
        verdict = (
            handoff.get("verdict")
            if handoff
            else None
        )
        gate = run.get("human_gate")

        evidence = self._evidence_projection(run)
        human_attention = None
        if gate:
            gate_payload = gate.get(
                "gate",
                gate,
            )
            human_attention = {
                "gate_id": gate_payload.get("id"),
                "question": gate_payload.get("question"),
                "reason": gate_payload.get("reason"),
                "materiality": gate_payload.get(
                    "materiality"
                ),
                "choices": gate_payload.get(
                    "choices",
                    [],
                ),
                "impacts": gate_payload.get(
                    "impacts",
                    {},
                ),
                "safe_default": gate_payload.get(
                    "safe_default"
                ),
            }

        status = str(state["status"])
        if verdict and verdict.get("summary"):
            summary = str(verdict["summary"])
        elif status == "completed":
            summary = (
                "Mission completed with independent "
                "QA validation."
            )
        elif human_attention:
            summary = (
                "Execution is waiting for a human "
                "decision."
            )
        else:
            summary = (
                f"Mission execution status: {status}."
            )

        builder_workspace = run[
            "builder_workspace"
        ]
        return OutcomeEnvelope(
            schema_version=OUTCOME_SCHEMA,
            envelope_id=envelope_id,
            mission_id=envelope.mission_id,
            status=status,
            summary=summary,
            next_action=run.get("next_action"),
            human_attention=human_attention,
            evidence=evidence,
            qa={
                "verdict": (
                    verdict.get("verdict")
                    if verdict
                    else None
                ),
            },
            implementation={
                "branch": builder_workspace.get(
                    "branch"
                ),
                "workspace_kind": (
                    builder_workspace.get("kind")
                ),
            },
        )

    def _evidence_projection(
        self,
        run: dict[str, Any],
    ) -> dict[str, Any]:
        task_ids = [
            str(run["builder_task"]["id"])
        ]
        if run.get("qa_task"):
            task_ids.append(
                str(run["qa_task"]["id"])
            )

        bundle_ids: list[str] = []
        kinds: list[str] = []
        for task_id in task_ids:
            results = self.evidence.list_results(
                task_id
            )
            if not results:
                continue
            latest = max(
                results,
                key=lambda item: str(
                    item.get("submitted_at", "")
                ),
            )
            bundle_id = str(
                latest["evidence_bundle_id"]
            )
            bundle_ids.append(bundle_id)
            manifest = (
                self.evidence.inspect_bundle(
                    bundle_id
                )
            )
            for item in manifest.get("items", []):
                kind = item.get("kind")
                if (
                    isinstance(kind, str)
                    and kind not in kinds
                ):
                    kinds.append(kind)

        return {
            "bundle_ids": bundle_ids,
            "kinds": kinds,
        }

    def _validate_authority(
        self,
        envelope: MissionEnvelope,
    ) -> None:
        escalations = [
            key
            for key in _REQUIRED_POLICY_KEYS
            if envelope.execution_policy[key]
        ]
        if escalations:
            raise RuntimeError(
                "M0.9 does not grant elevated execution "
                "authority from a Mission Envelope: "
                + ", ".join(escalations)
            )

    def _validate_revision(
        self,
        envelope: MissionEnvelope,
        digest: str,
    ) -> None:
        if not self.inbox_dir.exists():
            return

        for mission_path in self.inbox_dir.glob(
            "*/mission.json"
        ):
            existing = MissionEnvelope.from_dict(
                self._read_json(mission_path)
            )
            if (
                existing.mission_id
                != envelope.mission_id
            ):
                continue
            existing_digest = existing.digest()
            if existing_digest == digest:
                return
            if not envelope.revision:
                raise RuntimeError(
                    "Changed content for an existing "
                    "mission_id requires source.revision"
                )
            if (
                existing.revision
                and existing.revision
                == envelope.revision
            ):
                raise RuntimeError(
                    "Mission revision already exists with "
                    "different content"
                )

    def _inbox_root(
        self,
        envelope_id: str,
    ) -> Path:
        if (
            not envelope_id
            or "/" in envelope_id
            or "\\" in envelope_id
            or ".." in envelope_id
        ):
            raise RuntimeError(
                "Invalid envelope id"
            )
        path = self.inbox_dir / envelope_id
        if not (
            path / "mission.json"
        ).exists():
            raise RuntimeError(
                "Mission Envelope not found: "
                f"{envelope_id}"
            )
        return path

    def _require_initialized(self) -> None:
        if not self.store.project_file.exists():
            raise RuntimeError(
                "Cockpit is not initialized. "
                "Run: mado-cockpit init"
            )

    @staticmethod
    def _write_json(
        path: Path,
        payload: dict[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _read_json(
        path: Path,
    ) -> dict[str, Any]:
        return json.loads(
            path.read_text(encoding="utf-8")
        )
