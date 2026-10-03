from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Mapping

from .control import ControlPlaneBridge
from .models import utc_now
from .store import CockpitStore


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_id(value: str, *, label: str) -> str:
    value = value.strip()
    if (
        not value
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        raise RuntimeError(f"Invalid {label}")
    return value


class SpaceTransportAdapter:
    """Transport-safe projection over the M0.9 control bridge.

    The adapter is intentionally unaware of ChatGPT Space internals.
    It exposes the stable operations a Space-facing MCP server needs
    while preserving Cockpit as the final execution-policy authority.
    """

    transport_name = "space-mcp"

    def __init__(self, store: CockpitStore) -> None:
        self.store = store
        self.control = ControlPlaneBridge(store)
        self.transport_dir = (
            store.base
            / "control"
            / "transports"
            / self.transport_name
        )
        self.requests_dir = (
            self.transport_dir / "requests"
        )
        self.acks_dir = (
            self.transport_dir / "acks"
        )

    def submit_mission(
        self,
        mission: Mapping[str, Any],
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._idempotent(
            "submit_mission",
            request_id,
            {"mission": dict(mission)},
            lambda: self._submit_mission(mission),
        )

    def list_missions(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.control.inbox_dir.exists():
            return []

        items: list[dict[str, Any]] = []
        for path in sorted(
            self.control.inbox_dir.glob(
                "*/status.json"
            )
        ):
            envelope_id = path.parent.name
            view = self.inspect_mission(
                envelope_id
            )
            if (
                status is None
                or view["status"] == status
                or view.get("outcome_status")
                == status
            ):
                items.append(
                    {
                        "envelope_id": envelope_id,
                        "mission_id": view["mission_id"],
                        "title": view["title"],
                        "revision": view["revision"],
                        "status": view["status"],
                        "outcome_status": view[
                            "outcome_status"
                        ],
                        "next_action": view[
                            "next_action"
                        ],
                        "needs_human_attention": (
                            view[
                                "human_attention"
                            ]
                            is not None
                        ),
                    }
                )
        return items

    def inspect_mission(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        raw = self.control.inspect(
            _safe_id(
                envelope_id,
                label="envelope id",
            )
        )
        envelope = raw["envelope"]
        control_status = raw["status"]
        outcome = raw.get("outcome")
        return {
            "envelope_id": control_status[
                "envelope_id"
            ],
            "mission_id": envelope["mission_id"],
            "title": envelope["title"],
            "objective": envelope["objective"],
            "revision": control_status.get(
                "revision"
            ),
            "digest": control_status["digest"],
            "status": control_status["status"],
            "outcome_status": (
                outcome.get("status")
                if outcome
                else control_status.get(
                    "outcome_status"
                )
            ),
            "next_action": (
                outcome.get("next_action")
                if outcome
                else None
            ),
            "human_attention": (
                outcome.get("human_attention")
                if outcome
                else None
            ),
            "outcome": outcome,
        }

    def start_mission(
        self,
        envelope_id: str,
        *,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        safe_envelope_id = _safe_id(
            envelope_id,
            label="envelope id",
        )
        return self._idempotent(
            "start_mission",
            request_id,
            {"envelope_id": safe_envelope_id},
            lambda: self._start_mission(
                safe_envelope_id
            ),
        )

    def refresh_outcome(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        safe_envelope_id = _safe_id(
            envelope_id,
            label="envelope id",
        )
        return self.control.outcome(
            safe_envelope_id
        )

    def resolve_human_attention(
        self,
        envelope_id: str,
        *,
        choice: str | None = None,
        choose_for_me: bool = False,
        note: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        safe_envelope_id = _safe_id(
            envelope_id,
            label="envelope id",
        )
        if bool(choice) == bool(choose_for_me):
            raise RuntimeError(
                "Provide exactly one of choice or "
                "choose_for_me"
            )

        payload = {
            "envelope_id": safe_envelope_id,
            "choice": choice,
            "choose_for_me": choose_for_me,
            "note": note,
        }
        return self._idempotent(
            "resolve_human_attention",
            request_id,
            payload,
            lambda: self._resolve_human_attention(
                safe_envelope_id,
                choice=choice,
                choose_for_me=choose_for_me,
                note=note,
            ),
        )

    def acknowledge_outcome(
        self,
        envelope_id: str,
        *,
        outcome_digest: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        safe_envelope_id = _safe_id(
            envelope_id,
            label="envelope id",
        )
        digest = _safe_id(
            outcome_digest,
            label="outcome digest",
        )
        return self._idempotent(
            "acknowledge_outcome",
            request_id,
            {
                "envelope_id": safe_envelope_id,
                "outcome_digest": digest,
            },
            lambda: self._acknowledge_outcome(
                safe_envelope_id,
                digest,
            ),
        )

    @staticmethod
    def outcome_digest(
        outcome: Mapping[str, Any],
    ) -> str:
        return _canonical_digest(outcome)

    def _submit_mission(
        self,
        mission: Mapping[str, Any],
    ) -> dict[str, Any]:
        accepted = self.control.receive(
            mission
        )
        status = accepted["status"]
        envelope = accepted["envelope"]
        return {
            "envelope_id": status["envelope_id"],
            "mission_id": envelope["mission_id"],
            "title": envelope["title"],
            "revision": status.get("revision"),
            "digest": status["digest"],
            "status": status["status"],
        }

    def _start_mission(
        self,
        envelope_id: str,
    ) -> dict[str, Any]:
        started = self.control.start(
            envelope_id
        )
        operator = started["operator"]
        status = started["status"]
        envelope = started["envelope"]
        return {
            "envelope_id": envelope_id,
            "mission_id": envelope["mission_id"],
            "status": status["status"],
            "operator_status": operator[
                "state"
            ]["status"],
            "next_action": operator[
                "next_action"
            ],
        }

    def _resolve_human_attention(
        self,
        envelope_id: str,
        *,
        choice: str | None,
        choose_for_me: bool,
        note: str | None,
    ) -> dict[str, Any]:
        raw = self.control.inspect(envelope_id)
        operator_id = raw["status"].get(
            "operator_id"
        )
        if not operator_id:
            raise RuntimeError(
                "Mission Envelope has not started"
            )

        run = self.control.operators.inspect(
            str(operator_id)
        )
        if run["state"]["status"] != (
            "awaiting_human"
        ):
            raise RuntimeError(
                "Mission is not waiting for human "
                "attention"
            )

        self.control.operators.resolve_gate(
            str(operator_id),
            choice=choice,
            choose_for_me=choose_for_me,
            note=note,
        )
        return self.control.outcome(
            envelope_id
        )

    def _acknowledge_outcome(
        self,
        envelope_id: str,
        expected_digest: str,
    ) -> dict[str, Any]:
        inspected = self.control.inspect(
            envelope_id
        )
        outcome = inspected.get("outcome")
        if not outcome:
            raise RuntimeError(
                "No compiled Outcome Envelope to "
                "acknowledge"
            )

        actual_digest = self.outcome_digest(
            outcome
        )
        if actual_digest != expected_digest:
            raise RuntimeError(
                "Outcome digest mismatch; refresh the "
                "Outcome Envelope before acknowledging"
            )

        ack_path = (
            self.acks_dir
            / envelope_id
            / f"{actual_digest}.json"
        )
        if ack_path.exists():
            return self._read_json(ack_path)

        payload = {
            "transport": self.transport_name,
            "envelope_id": envelope_id,
            "mission_id": outcome["mission_id"],
            "outcome_digest": actual_digest,
            "outcome_status": outcome["status"],
            "acknowledged_at": utc_now(),
        }
        self._write_json(
            ack_path,
            payload,
        )
        return payload

    def _idempotent(
        self,
        operation: str,
        request_id: str | None,
        payload: Mapping[str, Any],
        action: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        if request_id is None:
            return action()

        safe_request_id = _safe_id(
            request_id,
            label="request id",
        )
        digest = _canonical_digest(payload)
        path = (
            self.requests_dir
            / f"{safe_request_id}.json"
        )
        if path.exists():
            recorded = self._read_json(path)
            if (
                recorded["operation"] != operation
                or recorded["input_digest"]
                != digest
            ):
                raise RuntimeError(
                    "Transport request_id was already "
                    "used with different input"
                )
            return dict(recorded["result"])

        result = action()
        self._write_json(
            path,
            {
                "transport": self.transport_name,
                "request_id": safe_request_id,
                "operation": operation,
                "input_digest": digest,
                "result": result,
                "completed_at": utc_now(),
            },
        )
        return result

    @staticmethod
    def _write_json(
        path: Path,
        payload: Mapping[str, Any],
    ) -> None:
        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            json.dumps(
                dict(payload),
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
