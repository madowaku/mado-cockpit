from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .capabilities import (
    CapabilityManager,
    CapabilityPager,
    CapabilityPolicy,
)
from .evidence import EvidenceManager
from .gates import HumanQuestionGateManager
from .handoffs import HandoffManager
from .models import (
    Event,
    OperatorPlan,
    OperatorState,
    Worker,
    utc_now,
)
from .sessions import SessionManager
from .store import CockpitStore
from .worktrees import WorktreeManager


_TERMINAL_OPERATOR_STATES = {
    "completed",
    "blocked",
    "failed",
}


def _unique(values: Iterable[str]) -> list[str]:
    return list(
        dict.fromkeys(
            value.strip()
            for value in values
            if value and value.strip()
        )
    )


class OperatorManager:
    def __init__(
        self,
        store: CockpitStore,
    ) -> None:
        self.store = store
        self.evidence = EvidenceManager(store)
        self.handoffs = HandoffManager(store)
        self.capabilities = CapabilityManager(store)
        self.gates = HumanQuestionGateManager(store)
        self.worktrees = WorktreeManager(store)
        self.operators_dir = (
            store.base / "operators"
        )

    def start(
        self,
        mission_id: str,
        objective: str,
        *,
        required_evidence: Iterable[str],
        provider: str = "codex",
        base_ref: str = "HEAD",
    ) -> dict[str, Any]:
        mission = self.store.get_mission(
            mission_id
        )
        required = _unique(
            required_evidence
        )
        if not required:
            raise RuntimeError(
                "Operator requires at least one "
                "Builder evidence kind"
            )
        if not objective.strip():
            raise RuntimeError(
                "Operator objective must not be empty"
            )

        operator_id = (
            f"opr_{uuid4().hex[:12]}"
        )
        builder_worker_id = (
            f"{operator_id}-builder"
        )
        qa_worker_id = (
            f"{operator_id}-qa"
        )
        builder_task_id = (
            f"{operator_id}-build"
        )

        plan = OperatorPlan(
            id=operator_id,
            mission_id=mission_id,
            objective=objective.strip(),
            builder_worker_id=(
                builder_worker_id
            ),
            qa_worker_id=qa_worker_id,
            builder_task_id=(
                builder_task_id
            ),
            provider=provider,
            required_evidence=required,
            base_ref=base_ref,
        )
        state = OperatorState(
            operator_id=operator_id,
            status="provisioning",
            last_action="operator_created",
        )

        root = (
            self.operators_dir
            / operator_id
        )
        root.mkdir(
            parents=True,
            exist_ok=False,
        )
        self._write_json(
            root / "plan.json",
            plan.to_dict(),
        )
        self._write_json(
            root / "state.json",
            state.to_dict(),
        )

        self.store.append_event(
            Event(
                type="operator.created",
                mission_id=mission_id,
                actor="operator",
                subject={
                    "operator_id": operator_id,
                    "builder_worker_id": (
                        builder_worker_id
                    ),
                    "qa_worker_id": (
                        qa_worker_id
                    ),
                    "builder_task_id": (
                        builder_task_id
                    ),
                },
            )
        )

        try:
            self.store.save_worker(
                Worker(
                    id=builder_worker_id,
                    role="builder",
                    mission_id=mission_id,
                    provider=provider,
                )
            )
            self.store.save_worker(
                Worker(
                    id=qa_worker_id,
                    role="qa",
                    mission_id=mission_id,
                    provider=provider,
                )
            )

            self.worktrees.create(
                builder_worker_id,
                base_ref=base_ref,
            )
            self.worktrees.create(
                qa_worker_id,
                base_ref=base_ref,
            )

            self.evidence.create_task(
                builder_task_id,
                builder_worker_id,
                objective.strip(),
                required_evidence=required,
                constraints=[
                    (
                        "Work only inside the assigned "
                        "Builder workspace."
                    ),
                    (
                        "Do not claim completion without "
                        "the required evidence."
                    ),
                ],
                deliverables=[
                    "implementation",
                    "evidence",
                ],
                done_when=[
                    (
                        "Result status is completed and "
                        "required evidence validates."
                    ),
                ],
            )
        except Exception as exc:
            self._update_state(
                operator_id,
                status="failed",
                last_action="provision_failed",
                last_error=str(exc),
            )
            self.store.append_event(
                Event(
                    type="operator.failed",
                    mission_id=mission_id,
                    actor="operator",
                    subject={
                        "operator_id": operator_id,
                        "stage": "provisioning",
                        "error": str(exc),
                    },
                )
            )
            raise

        self._update_state(
            operator_id,
            status="awaiting_builder",
            last_action="builder_task_assigned",
            last_error=None,
        )
        self.store.append_event(
            Event(
                type="operator.ready",
                mission_id=mission_id,
                actor="operator",
                subject={
                    "operator_id": operator_id,
                    "mission_title": mission["title"],
                    "builder_task_id": (
                        builder_task_id
                    ),
                },
            )
        )
        return self.inspect(
            operator_id
        )

    def advance(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )

        if (
            state["status"]
            in _TERMINAL_OPERATOR_STATES
        ):
            return self.inspect(
                operator_id
            )

        if (
            state["status"]
            == "awaiting_human"
        ):
            gate_id = state.get(
                "current_gate_id"
            )
            if not gate_id:
                raise RuntimeError(
                    "Operator is awaiting_human "
                    "without a gate id"
                )
            gate = self.gates.inspect(
                str(gate_id)
            )
            if (
                gate["status"]["status"]
                == "open"
            ):
                return self.inspect(
                    operator_id
                )

            resume_status = (
                state.get(
                    "gate_resume_status"
                )
                or "awaiting_builder"
            )
            self._update_state(
                operator_id,
                status=str(
                    resume_status
                ),
                current_gate_id=None,
                gate_resume_status=None,
                last_action=(
                    "human_gate_resolved"
                ),
                last_error=None,
            )
            return self.advance(
                operator_id
            )

        builder_task = (
            self.evidence.get_task(
                str(
                    plan["builder_task_id"]
                )
            )
        )
        builder_status = str(
            builder_task["status"]
        )

        current_handoff = None
        if state.get("handoff_id"):
            current_handoff = (
                self.handoffs.inspect(
                    str(
                        state["handoff_id"]
                    )
                )
            )

        if (
            builder_status
            == "ready_for_qa"
        ):
            should_create = (
                current_handoff is None
                or current_handoff[
                    "status"
                ]["status"]
                in {
                    "needs_fix",
                    "blocked",
                }
            )
            if should_create:
                created = (
                    self.handoffs.create(
                        str(
                            plan[
                                "builder_task_id"
                            ]
                        ),
                        str(
                            plan[
                                "qa_worker_id"
                            ]
                        ),
                    )
                )
                handoff_id = str(
                    created["handoff"]["id"]
                )
                self._update_state(
                    operator_id,
                    status="awaiting_qa",
                    handoff_id=handoff_id,
                    last_action=(
                        "handoff_created"
                    ),
                    last_error=None,
                )
                self._event(
                    plan,
                    "operator.advanced",
                    {
                        "operator_id": (
                            operator_id
                        ),
                        "action": (
                            "handoff_created"
                        ),
                        "handoff_id": (
                            handoff_id
                        ),
                    },
                )
                return self.inspect(
                    operator_id
                )

        if current_handoff is not None:
            handoff_status = str(
                current_handoff[
                    "status"
                ]["status"]
            )

            if handoff_status == "pass":
                self._update_state(
                    operator_id,
                    status="completed",
                    last_action="qa_passed",
                    last_error=None,
                )
                self._event(
                    plan,
                    "operator.completed",
                    {
                        "operator_id": (
                            operator_id
                        ),
                        "handoff_id": (
                            state[
                                "handoff_id"
                            ]
                        ),
                    },
                )
                return self.inspect(
                    operator_id
                )

            if (
                handoff_status
                == "needs_fix"
            ):
                self._update_state(
                    operator_id,
                    status="needs_fix",
                    last_action=(
                        "builder_revision_required"
                    ),
                    last_error=None,
                )
                return self.inspect(
                    operator_id
                )

            if handoff_status == "blocked":
                self._update_state(
                    operator_id,
                    status="blocked",
                    last_action="qa_blocked",
                    last_error=None,
                )
                self._event(
                    plan,
                    "operator.blocked",
                    {
                        "operator_id": (
                            operator_id
                        ),
                        "handoff_id": (
                            state[
                                "handoff_id"
                            ]
                        ),
                    },
                )
                return self.inspect(
                    operator_id
                )

            qa_task = (
                self.evidence.get_task(
                    str(
                        current_handoff[
                            "handoff"
                        ]["qa_task_id"]
                    )
                )
            )
            qa_status = str(
                qa_task["status"]
            )
            if qa_status in {
                "ready_for_qa",
                "result_blocked",
            }:
                status = (
                    "awaiting_verdict"
                )
                action = (
                    "qa_result_ready"
                )
            elif qa_status in {
                "evidence_incomplete",
                "result_failed",
            }:
                status = (
                    "qa_attention"
                )
                action = (
                    "qa_result_needs_attention"
                )
            else:
                status = "awaiting_qa"
                action = "awaiting_qa_result"

            self._update_state(
                operator_id,
                status=status,
                last_action=action,
                last_error=None,
            )
            return self.inspect(
                operator_id
            )

        builder_state_map = {
            "assigned": (
                "awaiting_builder",
                "awaiting_builder_result",
            ),
            "evidence_incomplete": (
                "builder_attention",
                "builder_evidence_incomplete",
            ),
            "result_failed": (
                "builder_attention",
                "builder_result_failed",
            ),
            "result_blocked": (
                "blocked",
                "builder_blocked",
            ),
            "needs_fix": (
                "needs_fix",
                "builder_revision_required",
            ),
            "qa_blocked": (
                "blocked",
                "qa_blocked",
            ),
            "qa_passed": (
                "completed",
                "qa_passed",
            ),
            "qa_in_review": (
                "awaiting_qa",
                "qa_in_review",
            ),
        }
        status, action = (
            builder_state_map.get(
                builder_status,
                (
                    "builder_attention",
                    (
                        "unrecognized_builder_"
                        f"state:{builder_status}"
                    ),
                ),
            )
        )
        self._update_state(
            operator_id,
            status=status,
            last_action=action,
            last_error=None,
        )
        return self.inspect(
            operator_id
        )

    def launch(
        self,
        operator_id: str,
        role: str,
        *,
        sessions: SessionManager,
        model: str | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )
        if (
            state["status"]
            == "awaiting_human"
        ):
            raise RuntimeError(
                "Operator is waiting for "
                "Human Question Gate resolution"
            )

        role = self._normalize_role(
            role
        )

        if role == "builder":
            worker_id = str(
                plan["builder_worker_id"]
            )
            task_id = str(
                plan["builder_task_id"]
            )
            state_field = (
                "builder_session_id"
            )
        else:
            handoff = self._current_handoff(
                operator_id
            )
            worker_id = str(
                plan["qa_worker_id"]
            )
            task_id = str(
                handoff["handoff"][
                    "qa_task_id"
                ]
            )
            state_field = (
                "qa_session_id"
            )

        task = self.evidence.get_task(
            task_id
        )
        bound_capabilities = (
            self.capabilities.get_bound_capabilities(
                worker_id
            )
        )
        if (
            self.capabilities.list_capabilities()
            and not bound_capabilities
        ):
            raise RuntimeError(
                "Capability registry is active but "
                f"{role} worker has no capability binding. "
                "Resolve a capability before launch."
            )

        prompt = self._task_prompt(
            task,
            role=role,
            capabilities=bound_capabilities,
        )

        state = self._state(
            operator_id
        )
        existing_id = state.get(
            state_field
        )
        existing = (
            self._session_or_none(
                existing_id
            )
            if existing_id
            else None
        )

        if (
            existing is not None
            and existing["status"]
            == "active"
        ):
            session = sessions.send(
                str(existing["id"]),
                prompt,
            )
            event_type = (
                "operator.session.resumed"
            )
            action = (
                f"{role}_session_resumed"
            )
        else:
            session = sessions.start(
                worker_id,
                prompt,
                provider_name=str(
                    plan["provider"]
                ),
                model=model,
            )
            event_type = (
                "operator.session.started"
            )
            action = (
                f"{role}_session_started"
            )

        self._update_state(
            operator_id,
            **{
                state_field: str(
                    session["id"]
                ),
                "last_action": action,
                "last_error": None,
            },
        )
        self._event(
            plan,
            event_type,
            {
                "operator_id": (
                    operator_id
                ),
                "role": role,
                "session_id": (
                    session["id"]
                ),
                "task_id": task_id,
            },
        )
        return self.inspect(
            operator_id
        )

    def resolve_capability(
        self,
        operator_id: str,
        role: str,
        *,
        pager: CapabilityPager,
        policy: CapabilityPolicy | None = None,
        request_text: str | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        role = self._normalize_role(
            role
        )

        if role == "builder":
            worker_id = str(
                plan["builder_worker_id"]
            )
            task_id = str(
                plan["builder_task_id"]
            )
        else:
            handoff = self._current_handoff(
                operator_id
            )
            worker_id = str(
                plan["qa_worker_id"]
            )
            task_id = str(
                handoff["handoff"][
                    "qa_task_id"
                ]
            )

        task = self.evidence.get_task(
            task_id
        )
        request = (
            request_text.strip()
            if request_text
            and request_text.strip()
            else self._capability_request_text(
                task,
                role=role,
            )
        )
        resolved = self.capabilities.resolve(
            worker_id,
            request,
            pager=pager,
            policy=policy,
            metadata={
                "operator_id": operator_id,
                "role": role,
                "task_id": task_id,
                "mission_id": (
                    plan["mission_id"]
                ),
            },
        )
        self._update_state(
            operator_id,
            last_action=(
                f"{role}_capability_"
                f"{resolved['resolution']['status']}"
            ),
            last_error=None,
        )
        self._event(
            plan,
            "operator.capability.resolved",
            {
                "operator_id": operator_id,
                "role": role,
                "worker_id": worker_id,
                "task_id": task_id,
                "resolution_id": (
                    resolved[
                        "resolution"
                    ]["id"]
                ),
                "selected_capability": (
                    resolved[
                        "resolution"
                    ][
                        "selected_capability"
                    ]
                ),
                "status": (
                    resolved[
                        "resolution"
                    ]["status"]
                ),
            },
        )
        return {
            "capability": resolved,
            "operator": self.inspect(
                operator_id
            ),
        }

    def request_gate(
        self,
        operator_id: str,
        *,
        question: str,
        reason: str,
        materiality: str,
        choices: Iterable[str] = (),
        impacts: dict[str, str] | None = None,
        recommendation: str | None = None,
        safe_default: str | None = None,
        consent_required: bool = False,
        implementation_detail: bool = False,
        requested_technical_control: bool = False,
        can_infer_safely: bool = False,
        reversible_default_exists: bool = False,
        materially_changes_result: bool = True,
        user_has_context_to_answer: bool = True,
        recovery_attempts: Iterable[Any] = (),
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )
        if (
            state["status"]
            in _TERMINAL_OPERATOR_STATES
        ):
            raise RuntimeError(
                "Cannot open a Human Question "
                "Gate for a terminal Operator"
            )
        if (
            state["status"]
            == "awaiting_human"
        ):
            raise RuntimeError(
                "Operator already has an open "
                "Human Question Gate"
            )

        worker_id, task_id = (
            self._gate_subject(
                operator_id
            )
        )
        requested = self.gates.request(
            question=question,
            reason=reason,
            materiality=materiality,
            mission_id=str(
                plan["mission_id"]
            ),
            operator_id=operator_id,
            worker_id=worker_id,
            task_id=task_id,
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
            choices=choices,
            impacts=impacts,
            recommendation=(
                recommendation
            ),
            safe_default=safe_default,
            recovery_attempts=(
                recovery_attempts
            ),
        )

        if requested["ask"]:
            gate_id = str(
                requested["gate"]["id"]
            )
            self._update_state(
                operator_id,
                status="awaiting_human",
                current_gate_id=gate_id,
                gate_resume_status=str(
                    state["status"]
                ),
                last_action=(
                    "human_gate_requested"
                ),
                last_error=None,
            )
            self._event(
                plan,
                "operator.gate.requested",
                {
                    "operator_id": (
                        operator_id
                    ),
                    "gate_id": gate_id,
                    "resume_status": (
                        state["status"]
                    ),
                },
            )
        else:
            self._update_state(
                operator_id,
                last_action=(
                    "human_gate_suppressed:"
                    f"{requested['gate_reason']}"
                ),
                last_error=None,
            )

        return {
            "gate": requested,
            "operator": self.inspect(
                operator_id
            ),
        }

    def resolve_gate(
        self,
        operator_id: str,
        *,
        choice: str | None = None,
        choose_for_me: bool = False,
        note: str | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )
        gate_id = state.get(
            "current_gate_id"
        )
        if (
            state["status"]
            != "awaiting_human"
            or not gate_id
        ):
            raise RuntimeError(
                "Operator is not waiting on "
                "a Human Question Gate"
            )

        resolved = self.gates.resolve(
            str(gate_id),
            choice=choice,
            choose_for_me=(
                choose_for_me
            ),
            note=note,
        )
        resume_status = (
            state.get(
                "gate_resume_status"
            )
            or "awaiting_builder"
        )
        self._update_state(
            operator_id,
            status=str(
                resume_status
            ),
            current_gate_id=None,
            gate_resume_status=None,
            last_action=(
                "human_gate_resolved"
            ),
            last_error=None,
        )
        self._event(
            plan,
            "operator.gate.resolved",
            {
                "operator_id": operator_id,
                "gate_id": gate_id,
                "choice": (
                    resolved[
                        "resolution"
                    ]["choice"]
                ),
                "method": (
                    resolved[
                        "resolution"
                    ]["method"]
                ),
                "resume_status": (
                    resume_status
                ),
            },
        )
        return {
            "gate": resolved,
            "operator": self.advance(
                operator_id
            ),
        }

    def stop(
        self,
        operator_id: str,
        role: str,
        *,
        sessions: SessionManager,
    ) -> dict[str, Any]:
        state = self._state(
            operator_id
        )
        plan = self._plan(
            operator_id
        )
        role = self._normalize_role(
            role
        )
        field = (
            "builder_session_id"
            if role == "builder"
            else "qa_session_id"
        )
        session_id = state.get(field)
        if not session_id:
            raise RuntimeError(
                f"No {role} session recorded "
                f"for operator: {operator_id}"
            )

        sessions.stop(
            str(session_id)
        )
        self._update_state(
            operator_id,
            last_action=(
                f"{role}_session_stopped"
            ),
            last_error=None,
        )
        self._event(
            plan,
            "operator.session.stopped",
            {
                "operator_id": (
                    operator_id
                ),
                "role": role,
                "session_id": session_id,
            },
        )
        return self.inspect(
            operator_id
        )

    def submit_result(
        self,
        operator_id: str,
        role: str,
        *,
        status: str,
        summary: str,
        evidence_files: Iterable[
            tuple[str, str]
        ] = (),
        changes: Iterable[str] = (),
        risks: Iterable[str] = (),
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )
        role = self._normalize_role(
            role
        )

        if role == "builder":
            task_id = str(
                plan["builder_task_id"]
            )
            session_id = state.get(
                "builder_session_id"
            )
        else:
            handoff = self._current_handoff(
                operator_id
            )
            task_id = str(
                handoff["handoff"][
                    "qa_task_id"
                ]
            )
            session_id = state.get(
                "qa_session_id"
            )

        submitted = (
            self.evidence.submit_result(
                task_id,
                status=status,
                summary=summary,
                evidence_files=(
                    evidence_files
                ),
                changes=changes,
                risks=risks,
                session_id=(
                    str(session_id)
                    if session_id
                    else None
                ),
            )
        )
        self._update_state(
            operator_id,
            last_action=(
                f"{role}_result_submitted"
            ),
            last_error=None,
        )
        self._event(
            plan,
            "operator.result.submitted",
            {
                "operator_id": (
                    operator_id
                ),
                "role": role,
                "task_id": task_id,
                "result_id": (
                    submitted["result"]["id"]
                ),
                "readiness": (
                    submitted["result"][
                        "readiness"
                    ]
                ),
            },
        )
        return {
            "submission": submitted,
            "operator": self.advance(
                operator_id
            ),
        }

    def verdict(
        self,
        operator_id: str,
        *,
        verdict: str,
        summary: str,
        qa_result_id: str | None = None,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        handoff = self._current_handoff(
            operator_id
        )
        qa_task_id = str(
            handoff["handoff"][
                "qa_task_id"
            ]
        )

        result_id = (
            qa_result_id
            or self._latest_result_id(
                qa_task_id
            )
        )
        resolved = (
            self.handoffs.submit_verdict(
                str(
                    handoff["handoff"][
                        "id"
                    ]
                ),
                result_id,
                verdict=verdict,
                summary=summary,
            )
        )
        self._update_state(
            operator_id,
            last_action=(
                f"qa_verdict:{verdict}"
            ),
            last_error=None,
        )
        self._event(
            plan,
            "operator.verdict.submitted",
            {
                "operator_id": (
                    operator_id
                ),
                "handoff_id": (
                    handoff["handoff"]["id"]
                ),
                "qa_result_id": result_id,
                "verdict": verdict,
            },
        )
        return {
            "handoff": resolved,
            "operator": self.advance(
                operator_id
            ),
        }

    def inspect(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )
        builder_task = (
            self.evidence.get_task(
                str(
                    plan["builder_task_id"]
                )
            )
        )
        builder_workspace = (
            self.store.get_workspace_for_worker(
                str(
                    plan[
                        "builder_worker_id"
                    ]
                )
            )
        )
        qa_workspace = (
            self.store.get_workspace_for_worker(
                str(
                    plan["qa_worker_id"]
                )
            )
        )

        handoff = None
        qa_task = None
        if state.get("handoff_id"):
            handoff = self.handoffs.inspect(
                str(state["handoff_id"])
            )
            qa_task = self.evidence.get_task(
                str(
                    handoff["handoff"][
                        "qa_task_id"
                    ]
                )
            )

        return {
            "plan": plan,
            "state": state,
            "builder_task": builder_task,
            "builder_workspace": (
                builder_workspace
            ),
            "qa_workspace": qa_workspace,
            "builder_capabilities": [
                capability.to_dict()
                for capability
                in self.capabilities.get_bound_capabilities(
                    str(
                        plan[
                            "builder_worker_id"
                        ]
                    )
                )
            ],
            "qa_capabilities": [
                capability.to_dict()
                for capability
                in self.capabilities.get_bound_capabilities(
                    str(
                        plan[
                            "qa_worker_id"
                        ]
                    )
                )
            ],
            "builder_session": (
                self._session_or_none(
                    state.get(
                        "builder_session_id"
                    )
                )
            ),
            "qa_session": (
                self._session_or_none(
                    state.get(
                        "qa_session_id"
                    )
                )
            ),
            "handoff": handoff,
            "qa_task": qa_task,
            "human_gate": (
                self.gates.inspect(
                    str(
                        state[
                            "current_gate_id"
                        ]
                    )
                )
                if state.get(
                    "current_gate_id"
                )
                else None
            ),
            "next_action": self._next_action(
                state,
            ),
        }

    def list(
        self,
    ) -> list[dict[str, Any]]:
        if not self.operators_dir.exists():
            return []
        return [
            self.inspect(
                path.parent.name
            )
            for path in sorted(
                self.operators_dir.glob(
                    "*/plan.json"
                )
            )
        ]

    def summary(
        self,
    ) -> dict[str, int]:
        runs = self.list()
        return {
            "operator_count": len(runs),
            "active_operator_count": sum(
                1
                for run in runs
                if run["state"]["status"]
                not in {
                    "completed",
                    "blocked",
                    "failed",
                }
            ),
            "completed_operator_count": sum(
                1
                for run in runs
                if run["state"]["status"]
                == "completed"
            ),
        }

    def _current_handoff(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        state = self._state(
            operator_id
        )
        handoff_id = state.get(
            "handoff_id"
        )
        if not handoff_id:
            raise RuntimeError(
                "Operator has no QA handoff yet: "
                f"{operator_id}"
            )
        return self.handoffs.inspect(
            str(handoff_id)
        )

    def _latest_result_id(
        self,
        task_id: str,
    ) -> str:
        results = (
            self.evidence.list_results(
                task_id
            )
        )
        if not results:
            raise RuntimeError(
                "No result exists for task: "
                f"{task_id}"
            )
        result = max(
            results,
            key=lambda item: str(
                item.get(
                    "submitted_at",
                    "",
                )
            ),
        )
        return str(result["id"])

    def _session_or_none(
        self,
        session_id: object,
    ) -> dict[str, Any] | None:
        if not session_id:
            return None
        try:
            return self.store.get_session(
                str(session_id)
            )
        except RuntimeError:
            return None

    def _gate_subject(
        self,
        operator_id: str,
    ) -> tuple[str | None, str | None]:
        plan = self._plan(
            operator_id
        )
        state = self._state(
            operator_id
        )

        if state.get(
            "handoff_id"
        ):
            handoff = self.handoffs.inspect(
                str(
                    state["handoff_id"]
                )
            )
            if (
                state["status"]
                in {
                    "awaiting_qa",
                    "qa_attention",
                    "awaiting_verdict",
                }
            ):
                return (
                    str(
                        plan[
                            "qa_worker_id"
                        ]
                    ),
                    str(
                        handoff[
                            "handoff"
                        ][
                            "qa_task_id"
                        ]
                    ),
                )

        return (
            str(
                plan[
                    "builder_worker_id"
                ]
            ),
            str(
                plan[
                    "builder_task_id"
                ]
            ),
        )

    @staticmethod
    def _normalize_role(
        role: str,
    ) -> str:
        normalized = role.strip().lower()
        if normalized not in {
            "builder",
            "qa",
        }:
            raise RuntimeError(
                "Operator role must be "
                "builder or qa"
            )
        return normalized

    @staticmethod
    def _task_prompt(
        task: dict[str, Any],
        *,
        role: str,
        capabilities: list[Any],
    ) -> str:
        def section(
            title: str,
            values: list[str],
        ) -> str:
            if not values:
                return (
                    f"{title}:\n- none"
                )
            lines = "\n".join(
                f"- {value}"
                for value in values
            )
            return f"{title}:\n{lines}"

        capability_lines = []
        for capability in capabilities:
            line = (
                f"[{capability.id}] "
                f"{capability.name} "
                f"(kind={capability.kind}, "
                f"cost={capability.cost_class or 'unknown'})"
            )
            if capability.instructions_ref:
                line += (
                    " instructions="
                    f"{capability.instructions_ref}"
                )
            capability_lines.append(
                line
            )

        return "\n\n".join(
            [
                (
                    "MADO Cockpit assigned you "
                    f"the {role} task "
                    f"{task['id']}."
                ),
                (
                    "Objective:\n"
                    f"{task['objective']}"
                ),
                section(
                    "Bound capabilities",
                    capability_lines,
                ),
                section(
                    "Required evidence",
                    list(
                        task[
                            "required_evidence"
                        ]
                    ),
                ),
                section(
                    "Constraints",
                    list(
                        task["constraints"]
                    ),
                ),
                section(
                    "Deliverables",
                    list(
                        task["deliverables"]
                    ),
                ),
                section(
                    "Done when",
                    list(
                        task["done_when"]
                    ),
                ),
                (
                    "Work only inside your assigned "
                    "workspace. Use only capabilities "
                    "that Cockpit bound to this worker. "
                    "Leave evidence files inside that "
                    "workspace. Do not claim success "
                    "without evidence."
                ),
            ]
        )

    @staticmethod
    def _capability_request_text(
        task: dict[str, Any],
        *,
        role: str,
    ) -> str:
        return "\n".join(
            [
                f"Role: {role}",
                (
                    "Objective: "
                    f"{task['objective']}"
                ),
                (
                    "Required evidence: "
                    + ", ".join(
                        task[
                            "required_evidence"
                        ]
                    )
                ),
                (
                    "Deliverables: "
                    + ", ".join(
                        task["deliverables"]
                    )
                ),
            ]
        )

    @staticmethod
    def _next_action(
        state: dict[str, Any],
    ) -> str:
        mapping = {
            "provisioning": (
                "finish_provisioning"
            ),
            "awaiting_builder": (
                "launch_or_wait_for_builder"
            ),
            "builder_attention": (
                "inspect_builder_result_and_retry"
            ),
            "awaiting_qa": (
                "launch_or_wait_for_qa"
            ),
            "qa_attention": (
                "inspect_qa_result_and_retry"
            ),
            "awaiting_verdict": (
                "submit_qa_verdict"
            ),
            "awaiting_human": (
                "resolve_human_question_gate"
            ),
            "needs_fix": (
                "revise_builder_task"
            ),
            "completed": "done",
            "blocked": (
                "resolve_blocker"
            ),
            "failed": (
                "inspect_operator_error"
            ),
        }
        return mapping.get(
            str(state["status"]),
            "inspect_operator_state",
        )

    def _plan(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        path = (
            self.operators_dir
            / operator_id
            / "plan.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Operator run not found: "
                f"{operator_id}"
            )
        return self._read_json(path)

    def _state(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        path = (
            self.operators_dir
            / operator_id
            / "state.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Operator state not found: "
                f"{operator_id}"
            )
        return self._read_json(path)

    def _update_state(
        self,
        operator_id: str,
        **changes: Any,
    ) -> dict[str, Any]:
        state = self._state(
            operator_id
        )
        state.update(changes)
        state["updated_at"] = utc_now()
        self._write_json(
            self.operators_dir
            / operator_id
            / "state.json",
            state,
        )
        return state

    def _event(
        self,
        plan: dict[str, Any],
        event_type: str,
        subject: dict[str, Any],
    ) -> None:
        self.store.append_event(
            Event(
                type=event_type,
                mission_id=str(
                    plan["mission_id"]
                ),
                actor="operator",
                subject=subject,
            )
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
            path.read_text(
                encoding="utf-8"
            )
        )
