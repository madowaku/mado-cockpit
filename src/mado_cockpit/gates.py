from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .models import (
    Event,
    GateResolution,
    HumanQuestionGate,
    RecoveryAttempt,
    utc_now,
)
from .store import CockpitStore


_MATERIALITIES = {
    "privacy",
    "cost",
    "destructive",
    "external_action",
    "core_meaning",
    "other",
}
_HUMAN_OWNED = {
    "privacy",
    "cost",
    "destructive",
    "external_action",
    "core_meaning",
}
_REQUIRED_RECOVERY = (
    "retry",
    "alternative_capability",
    "alternative_worker",
    "evidence_search",
)
_EXHAUSTED_ATTEMPT_STATUSES = {
    "failed",
    "unavailable",
    "no_match",
    "exhausted",
}
_TECHNICAL_JARGON = re.compile(
    r"\b("
    r"postgres(?:ql)?|sqlite|mysql|orm|ssr|csr|"
    r"framework|schema migration|docker|kubernetes|"
    r"npm|pnpm|yarn|node\.js|vercel|cloudflare|"
    r"supabase|firebase|api key|environment variable|"
    r"env var|oauth|jwt"
    r")\b",
    re.IGNORECASE,
)


def _unique(values: Iterable[str]) -> list[str]:
    return list(
        dict.fromkeys(
            value.strip()
            for value in values
            if value and value.strip()
        )
    )


class HumanQuestionGateManager:
    def __init__(
        self,
        store: CockpitStore,
    ) -> None:
        self.store = store
        self.gates_dir = (
            store.base / "gates"
        )

    def evaluate_candidate(
        self,
        *,
        question: str,
        reason: str,
        materiality: str = "other",
        implementation_detail: bool = False,
        requested_technical_control: bool = False,
        can_infer_safely: bool = False,
        reversible_default_exists: bool = False,
        materially_changes_result: bool = False,
        user_has_context_to_answer: bool = True,
        consent_required: bool = False,
        choices: Iterable[str] = (),
        safe_default: str | None = None,
        recovery_attempts: Iterable[
            RecoveryAttempt
        ] = (),
    ) -> dict[str, Any]:
        self._validate_materiality(
            materiality
        )
        normalized_choices = _unique(
            choices
        )
        attempts = list(
            recovery_attempts
        )

        if (
            implementation_detail
            and not requested_technical_control
        ):
            return self._suppressed(
                reason="implementation_detail",
                materiality=materiality,
                resolution=safe_default,
            )

        if consent_required:
            self._validate_question(
                question,
                allow_technical=(
                    requested_technical_control
                ),
            )
            return self._ask(
                reason="consent_required",
                materiality=materiality,
                choices=normalized_choices,
                safe_default=safe_default,
            )

        if not materially_changes_result:
            return self._suppressed(
                reason="not_material",
                materiality=materiality,
                resolution=safe_default,
            )

        if (
            can_infer_safely
            and reversible_default_exists
        ):
            return self._suppressed(
                reason="safe_reversible_default",
                materiality=materiality,
                resolution=safe_default,
            )

        if not user_has_context_to_answer:
            return self._suppressed(
                reason="system_should_resolve_first",
                materiality=materiality,
                resolution=None,
            )

        if materiality not in _HUMAN_OWNED:
            missing = self._missing_recovery(
                attempts
            )
            if missing:
                return {
                    **self._suppressed(
                        reason="recovery_required",
                        materiality=materiality,
                        resolution=None,
                    ),
                    "missing_recovery": missing,
                }

        self._validate_question(
            question,
            allow_technical=(
                requested_technical_control
            ),
        )
        return self._ask(
            reason="material_unresolved_decision",
            materiality=materiality,
            choices=normalized_choices,
            safe_default=safe_default,
        )

    def request(
        self,
        *,
        question: str,
        reason: str,
        materiality: str,
        mission_id: str | None = None,
        operator_id: str | None = None,
        worker_id: str | None = None,
        task_id: str | None = None,
        implementation_detail: bool = False,
        requested_technical_control: bool = False,
        can_infer_safely: bool = False,
        reversible_default_exists: bool = False,
        materially_changes_result: bool = True,
        user_has_context_to_answer: bool = True,
        consent_required: bool = False,
        choices: Iterable[str] = (),
        impacts: dict[str, str] | None = None,
        recommendation: str | None = None,
        safe_default: str | None = None,
        recovery_attempts: Iterable[
            RecoveryAttempt
        ] = (),
    ) -> dict[str, Any]:
        normalized_choices = _unique(
            choices
        )
        attempts = list(
            recovery_attempts
        )
        evaluation = self.evaluate_candidate(
            question=question,
            reason=reason,
            materiality=materiality,
            implementation_detail=(
                implementation_detail
            ),
            requested_technical_control=(
                requested_technical_control
            ),
            can_infer_safely=(
                can_infer_safely
            ),
            reversible_default_exists=(
                reversible_default_exists
            ),
            materially_changes_result=(
                materially_changes_result
            ),
            user_has_context_to_answer=(
                user_has_context_to_answer
            ),
            consent_required=(
                consent_required
            ),
            choices=normalized_choices,
            safe_default=safe_default,
            recovery_attempts=attempts,
        )

        if not evaluation["ask"]:
            self.store.append_event(
                Event(
                    type="gate.suppressed",
                    mission_id=mission_id,
                    actor="cockpit",
                    subject={
                        "operator_id": operator_id,
                        "worker_id": worker_id,
                        "task_id": task_id,
                        "gate_reason": (
                            evaluation[
                                "gate_reason"
                            ]
                        ),
                        "materiality": materiality,
                        "resolution": (
                            evaluation.get(
                                "resolution"
                            )
                        ),
                        "missing_recovery": (
                            evaluation.get(
                                "missing_recovery",
                                [],
                            )
                        ),
                    },
                )
            )
            return evaluation

        self._validate_choices(
            normalized_choices,
            impacts=(
                impacts or {}
            ),
            recommendation=recommendation,
            safe_default=safe_default,
        )

        gate_id = (
            f"gate_{uuid4().hex[:12]}"
        )
        gate = HumanQuestionGate(
            id=gate_id,
            mission_id=mission_id,
            question=question.strip(),
            reason=reason.strip(),
            materiality=materiality,
            status="open",
            choices=normalized_choices,
            impacts=dict(
                impacts or {}
            ),
            recommendation=recommendation,
            safe_default=safe_default,
            allow_choose_for_me=(
                safe_default is not None
            ),
            consent_required=(
                consent_required
            ),
            operator_id=operator_id,
            worker_id=worker_id,
            task_id=task_id,
            recovery_attempts=attempts,
        )

        root = (
            self.gates_dir / gate_id
        )
        root.mkdir(
            parents=True,
            exist_ok=False,
        )
        self._write_json(
            root / "gate.json",
            gate.to_dict(),
        )
        self._write_json(
            root / "status.json",
            {
                "gate_id": gate_id,
                "status": "open",
                "updated_at": utc_now(),
                "resolution_id": None,
            },
        )

        self.store.append_event(
            Event(
                type="gate.requested",
                mission_id=mission_id,
                actor="cockpit",
                subject={
                    "gate_id": gate_id,
                    "operator_id": (
                        operator_id
                    ),
                    "worker_id": worker_id,
                    "task_id": task_id,
                    "materiality": materiality,
                    "gate_reason": (
                        evaluation[
                            "gate_reason"
                        ]
                    ),
                    "consent_required": (
                        consent_required
                    ),
                },
            )
        )
        return {
            "ask": True,
            "gate_reason": (
                evaluation["gate_reason"]
            ),
            **self.inspect(gate_id),
        }

    def resolve(
        self,
        gate_id: str,
        *,
        choice: str | None = None,
        choose_for_me: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        current = self.inspect(
            gate_id
        )
        gate = current["gate"]
        status = current["status"]

        if status["status"] != "open":
            raise RuntimeError(
                "Gate is already resolved: "
                f"{gate_id}"
            )

        if choose_for_me:
            if not gate[
                "allow_choose_for_me"
            ]:
                raise RuntimeError(
                    "Gate does not allow "
                    "choose-for-me"
                )
            safe_default = gate.get(
                "safe_default"
            )
            if not safe_default:
                raise RuntimeError(
                    "Gate has no safe default"
                )
            selected = str(
                safe_default
            )
            method = "safe_default"
        else:
            if choice is None or not choice.strip():
                raise RuntimeError(
                    "Gate resolution requires "
                    "a human choice"
                )
            selected = choice.strip()
            method = "human"

        choices = list(
            gate.get(
                "choices",
                [],
            )
        )
        if (
            choices
            and selected not in choices
        ):
            raise RuntimeError(
                "Gate choice must be one of: "
                + ", ".join(choices)
            )

        resolution = GateResolution(
            id=(
                f"gateres_"
                f"{uuid4().hex[:12]}"
            ),
            gate_id=gate_id,
            choice=selected,
            method=method,
            note=(
                note.strip()
                if note
                and note.strip()
                else None
            ),
        )
        root = (
            self.gates_dir / gate_id
        )
        self._write_json(
            root / "resolution.json",
            resolution.to_dict(),
        )
        self._write_json(
            root / "status.json",
            {
                "gate_id": gate_id,
                "status": "resolved",
                "updated_at": utc_now(),
                "resolution_id": (
                    resolution.id
                ),
            },
        )

        self.store.append_event(
            Event(
                type="gate.resolved",
                mission_id=(
                    gate.get(
                        "mission_id"
                    )
                ),
                actor="human",
                subject={
                    "gate_id": gate_id,
                    "operator_id": (
                        gate.get(
                            "operator_id"
                        )
                    ),
                    "choice": selected,
                    "method": method,
                    "materiality": (
                        gate[
                            "materiality"
                        ]
                    ),
                },
            )
        )
        return self.inspect(
            gate_id
        )

    def inspect(
        self,
        gate_id: str,
    ) -> dict[str, Any]:
        root = (
            self.gates_dir / gate_id
        )
        gate_path = root / "gate.json"
        status_path = (
            root / "status.json"
        )
        if (
            not gate_path.exists()
            or not status_path.exists()
        ):
            raise RuntimeError(
                f"Gate not found: {gate_id}"
            )

        resolution_path = (
            root / "resolution.json"
        )
        return {
            "gate": self._read_json(
                gate_path
            ),
            "status": self._read_json(
                status_path
            ),
            "resolution": (
                self._read_json(
                    resolution_path
                )
                if resolution_path.exists()
                else None
            ),
        }

    def list(
        self,
        *,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        if not self.gates_dir.exists():
            return []
        gates = [
            self.inspect(
                path.parent.name
            )
            for path in sorted(
                self.gates_dir.glob(
                    "*/gate.json"
                )
            )
        ]
        if status is None:
            return gates
        return [
            gate
            for gate in gates
            if gate["status"]["status"]
            == status
        ]

    def summary(
        self,
    ) -> dict[str, int]:
        gates = self.list()
        return {
            "gate_count": len(gates),
            "open_gate_count": sum(
                1
                for gate in gates
                if gate["status"][
                    "status"
                ]
                == "open"
            ),
            "resolved_gate_count": sum(
                1
                for gate in gates
                if gate["status"][
                    "status"
                ]
                == "resolved"
            ),
        }

    @staticmethod
    def _missing_recovery(
        attempts: list[
            RecoveryAttempt
        ],
    ) -> list[str]:
        exhausted = {
            attempt.strategy
            for attempt in attempts
            if attempt.status
            in _EXHAUSTED_ATTEMPT_STATUSES
        }
        return [
            strategy
            for strategy
            in _REQUIRED_RECOVERY
            if strategy not in exhausted
        ]

    @staticmethod
    def _validate_materiality(
        materiality: str,
    ) -> None:
        if materiality not in _MATERIALITIES:
            raise RuntimeError(
                "Unsupported gate materiality: "
                f"{materiality}"
            )

    @staticmethod
    def _validate_question(
        question: str,
        *,
        allow_technical: bool,
    ) -> None:
        if not question.strip():
            raise RuntimeError(
                "Human question must not be empty"
            )
        if (
            not allow_technical
            and _TECHNICAL_JARGON.search(
                question
            )
        ):
            raise RuntimeError(
                "Human question contains "
                "avoidable implementation jargon"
            )

    @staticmethod
    def _validate_choices(
        choices: list[str],
        *,
        impacts: dict[str, str],
        recommendation: str | None,
        safe_default: str | None,
    ) -> None:
        if safe_default is not None:
            if (
                choices
                and safe_default
                not in choices
            ):
                raise RuntimeError(
                    "safe_default must be one "
                    "of gate choices"
                )
        if recommendation is not None:
            if (
                choices
                and recommendation
                not in choices
            ):
                raise RuntimeError(
                    "recommendation must be one "
                    "of gate choices"
                )
        unknown_impacts = (
            set(impacts)
            - set(choices)
        )
        if unknown_impacts:
            raise RuntimeError(
                "Impact keys must match gate "
                "choices: "
                + ", ".join(
                    sorted(
                        unknown_impacts
                    )
                )
            )

    @staticmethod
    def _ask(
        *,
        reason: str,
        materiality: str,
        choices: list[str],
        safe_default: str | None,
    ) -> dict[str, Any]:
        return {
            "ask": True,
            "gate_reason": reason,
            "materiality": materiality,
            "choices": choices,
            "allow_choose_for_me": (
                safe_default is not None
            ),
            "default_choice": (
                safe_default
            ),
            "resolution": None,
        }

    @staticmethod
    def _suppressed(
        *,
        reason: str,
        materiality: str,
        resolution: str | None,
    ) -> dict[str, Any]:
        return {
            "ask": False,
            "gate_reason": reason,
            "materiality": materiality,
            "choices": [],
            "allow_choose_for_me": False,
            "default_choice": None,
            "resolution": resolution,
        }

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
            path.read_text(
                encoding="utf-8"
            )
        )
