from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Literal, Mapping, TypeVar
from uuid import uuid4

from .control_lease import (
    ControlLeaseManager,
    ControlScope,
)
from .models import Event, utc_now
from .store import CockpitStore


ACTION_GATEWAY_VERSION = "MCC-M2.4"
ActionEffect = Literal["read", "write"]
InitiatorKind = Literal[
    "person",
    "chat",
    "routine",
    "replay",
    "system",
]
DecisionSource = Literal[
    "deny",
    "allow",
    "default",
    "policy_error",
    "revalidation_error",
    "approval_changed",
    "equivalent_fenced",
    "human_control_fenced",
]
ShadowDelta = Literal[
    "same",
    "would_allow",
    "would_deny",
]

T = TypeVar("T")


def _stable(value: Any) -> Any:
    if value is None or isinstance(
        value,
        (str, int, float, bool),
    ):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): _stable(item)
            for key, item in sorted(
                value.items(),
                key=lambda pair: str(
                    pair[0]
                ),
            )
        }
    if isinstance(value, (list, tuple)):
        return [
            _stable(item)
            for item in value
        ]
    return str(value)


def _digest(payload: Any) -> str:
    encoded = json.dumps(
        _stable(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(
        encoded
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class ActionInitiator:
    kind: InitiatorKind = "system"
    source: str = "cockpit"
    context_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {
            "person",
            "chat",
            "routine",
            "replay",
            "system",
        }:
            raise RuntimeError(
                "Unsupported action initiator kind"
            )
        if not self.source.strip():
            raise RuntimeError(
                "Action initiator source must not be empty"
            )
        if (
            self.context_id is not None
            and not self.context_id.strip()
        ):
            raise RuntimeError(
                "Action initiator context_id must not be empty"
            )

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "context_id": self.context_id,
        }

    @property
    def fence_scope(
        self,
    ) -> str | None:
        if self.context_id is None:
            return None
        return (
            f"{self.kind}:"
            f"{self.source}:"
            f"{self.context_id}"
        )


@dataclass(frozen=True, slots=True)
class ActionCandidate:
    action: str
    effect: ActionEffect
    target_kind: str
    target: Mapping[str, Any]
    arguments: Mapping[str, Any] = field(
        default_factory=dict
    )
    actor: str = "cockpit"
    initiator: ActionInitiator = field(
        default_factory=ActionInitiator
    )
    control_scope: ControlScope | None = None
    capability: str | None = None
    mission_id: str | None = None

    def __post_init__(self) -> None:
        if not self.action.strip():
            raise RuntimeError(
                "Action name must not be empty"
            )
        if self.effect not in {
            "read",
            "write",
        }:
            raise RuntimeError(
                "Action effect must be read or write"
            )
        if not self.target_kind.strip():
            raise RuntimeError(
                "Action target_kind must not be empty"
            )
        if not self.actor.strip():
            raise RuntimeError(
                "Action actor must not be empty"
            )
        if not isinstance(
            self.initiator,
            ActionInitiator,
        ):
            raise RuntimeError(
                "Action initiator must be ActionInitiator"
            )
        if (
            self.control_scope is not None
            and not isinstance(
                self.control_scope,
                ControlScope,
            )
        ):
            raise RuntimeError(
                "Action control_scope must be ControlScope"
            )

    @property
    def arguments_digest(self) -> str:
        return _digest(
            self.arguments
        )

    @property
    def equivalence_digest(
        self,
    ) -> str:
        return _digest(
            {
                "action": self.action,
                "effect": self.effect,
                "target_kind": (
                    self.target_kind
                ),
                "target": self.target,
                "arguments": (
                    self.arguments
                ),
                "actor": self.actor,
                "control_scope": (
                    self.control_scope.to_dict()
                    if self.control_scope is not None
                    else None
                ),
                "capability": (
                    self.capability
                ),
                "mission_id": (
                    self.mission_id
                ),
            }
        )

    @property
    def digest(self) -> str:
        return _digest(
            {
                "equivalence_digest": (
                    self.equivalence_digest
                ),
                "initiator": (
                    self.initiator.to_dict()
                ),
                "control_scope": (
                    self.control_scope.to_dict()
                    if self.control_scope is not None
                    else None
                ),
            }
        )

    @property
    def fence_scope(
        self,
    ) -> str | None:
        return self.initiator.fence_scope

    def with_target(
        self,
        target: Mapping[str, Any],
    ) -> ActionCandidate:
        return replace(
            self,
            target=dict(target),
        )


RulePredicate = Callable[
    [ActionCandidate],
    bool,
]


@dataclass(frozen=True, slots=True)
class ActionRule:
    id: str
    predicate: RulePredicate
    reason: str

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise RuntimeError(
                "Action rule id must not be empty"
            )
        if not self.reason.strip():
            raise RuntimeError(
                "Action rule reason must not be empty"
            )


@dataclass(frozen=True, slots=True)
class ActionPolicy:
    deny: tuple[
        ActionRule,
        ...,
    ] = ()
    allow: tuple[
        ActionRule,
        ...,
    ] = ()


@dataclass(frozen=True, slots=True)
class ActionDecision:
    allowed: bool
    source: DecisionSource
    rule_id: str | None
    reason: str

    def to_dict(
        self,
    ) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "source": self.source,
            "rule_id": self.rule_id,
            "reason": self.reason,
        }


class ActionPolicyRefused(
    RuntimeError
):
    def __init__(
        self,
        message: str,
        *,
        receipt_id: str,
    ) -> None:
        super().__init__(message)
        self.receipt_id = receipt_id


def _rule_matches(
    rule: ActionRule,
    candidate: ActionCandidate,
) -> bool:
    result = rule.predicate(
        candidate
    )
    if type(result) is not bool:
        raise RuntimeError(
            "Action policy rule must return boolean"
        )
    return result


def evaluate_action_policy(
    policy: ActionPolicy | None,
    candidate: ActionCandidate,
) -> ActionDecision:
    if policy is None:
        return ActionDecision(
            allowed=False,
            source="default",
            rule_id=None,
            reason=(
                "No execution-time action policy "
                "was configured."
            ),
        )

    for rule in policy.deny:
        try:
            matched = _rule_matches(
                rule,
                candidate,
            )
        except Exception as exc:
            return ActionDecision(
                allowed=False,
                source="policy_error",
                rule_id=rule.id,
                reason=(
                    "Deny policy evaluation failed "
                    f"closed: {exc}"
                ),
            )
        if matched:
            return ActionDecision(
                allowed=False,
                source="deny",
                rule_id=rule.id,
                reason=rule.reason,
            )

    for rule in policy.allow:
        try:
            matched = _rule_matches(
                rule,
                candidate,
            )
        except Exception as exc:
            return ActionDecision(
                allowed=False,
                source="policy_error",
                rule_id=rule.id,
                reason=(
                    "Allow policy evaluation failed "
                    f"closed: {exc}"
                ),
            )
        if matched:
            return ActionDecision(
                allowed=True,
                source="allow",
                rule_id=rule.id,
                reason=rule.reason,
            )

    return ActionDecision(
        allowed=False,
        source="default",
        rule_id=None,
        reason=(
            "No execution-time rule permits "
            "this action."
        ),
    )


def compare_shadow_decision(
    live: ActionDecision,
    shadow: ActionDecision | None,
) -> ShadowDelta | None:
    if shadow is None:
        return None
    if live.allowed == shadow.allowed:
        return "same"
    if live.allowed:
        return "would_deny"
    return "would_allow"


def classify_external_mcp_effect(
    annotations: Mapping[
        str,
        Any,
    ]
    | None,
) -> ActionEffect:
    if not annotations:
        return "write"
    if (
        annotations.get(
            "destructiveHint"
        )
        is True
    ):
        return "write"
    if (
        annotations.get(
            "readOnlyHint"
        )
        is True
    ):
        return "read"
    return "write"


def mado_internal_action_policy(
) -> ActionPolicy:
    return ActionPolicy(
        allow=(
            ActionRule(
                id=(
                    "allow:mado_advance_mission"
                ),
                predicate=lambda candidate: (
                    candidate.action
                    == "mado_advance_mission"
                    and candidate.effect
                    == "write"
                    and candidate.target_kind
                    == "operator"
                ),
                reason=(
                    "MADO permits its bounded "
                    "deterministic Operator advance."
                ),
            ),
            ActionRule(
                id=(
                    "allow:mado_answer_human_gate"
                ),
                predicate=lambda candidate: (
                    candidate.action
                    == "mado_answer_human_gate"
                    and candidate.effect
                    == "write"
                    and candidate.target_kind
                    == "human_gate"
                ),
                reason=(
                    "MADO permits resolution of "
                    "the current Human Question Gate."
                ),
            ),
        ),
    )


class ActionPolicyGateway:
    def __init__(
        self,
        store: CockpitStore,
        *,
        control_leases: ControlLeaseManager | None = None,
    ) -> None:
        self.store = store
        self.receipts_dir = (
            store.base
            / "action_decisions"
        )
        self.control_leases = (
            control_leases
            or ControlLeaseManager(store)
        )

    def execute(
        self,
        candidate: ActionCandidate,
        *,
        policy: ActionPolicy | None,
        dispatch: Callable[
            [ActionCandidate],
            T,
        ],
        revalidate: Callable[
            [ActionCandidate],
            ActionCandidate,
        ]
        | None = None,
        approved_digest: str
        | None = None,
        shadow_policy: ActionPolicy
        | None = None,
        fence_equivalent: bool = True,
    ) -> T:
        current = candidate
        revalidation_error: str | None = (
            None
        )

        if revalidate is not None:
            try:
                current = revalidate(
                    candidate
                )
                if not isinstance(
                    current,
                    ActionCandidate,
                ):
                    raise RuntimeError(
                        "Action revalidation must "
                        "return ActionCandidate"
                    )
            except Exception as exc:
                revalidation_error = str(
                    exc
                )

        if revalidation_error is not None:
            decision = ActionDecision(
                allowed=False,
                source=(
                    "revalidation_error"
                ),
                rule_id=None,
                reason=(
                    "Action revalidation failed "
                    f"closed: {revalidation_error}"
                ),
            )
            receipt = self._record_decision(
                candidate=candidate,
                current=None,
                decision=decision,
                approved_digest=(
                    approved_digest
                ),
                shadow_decision=None,
                equivalent_to_receipt_id=None,
                control_lease=None,
            )
            raise ActionPolicyRefused(
                decision.reason,
                receipt_id=receipt["id"],
            )

        if (
            approved_digest is not None
            and current.digest
            != approved_digest
        ):
            decision = ActionDecision(
                allowed=False,
                source="approval_changed",
                rule_id=None,
                reason=(
                    "The approved action changed "
                    "during execution-time "
                    "revalidation."
                ),
            )
            receipt = self._record_decision(
                candidate=candidate,
                current=current,
                decision=decision,
                approved_digest=(
                    approved_digest
                ),
                shadow_decision=None,
                equivalent_to_receipt_id=None,
                control_lease=None,
            )
            raise ActionPolicyRefused(
                decision.reason,
                receipt_id=receipt["id"],
            )

        active_control = (
            self.control_leases.current(
                current.control_scope
            )
            if current.control_scope
            is not None
            else None
        )
        if (
            active_control is not None
            and not (
                current.initiator.kind
                == "person"
                and current.actor
                == active_control[
                    "holder"
                ]
            )
        ):
            decision = ActionDecision(
                allowed=False,
                source=(
                    "human_control_fenced"
                ),
                rule_id=None,
                reason=(
                    "Human control is active for "
                    "this resource under lease "
                    f"{active_control['id']}."
                ),
            )
            receipt = self._record_decision(
                candidate=candidate,
                current=current,
                decision=decision,
                approved_digest=(
                    approved_digest
                ),
                shadow_decision=None,
                equivalent_to_receipt_id=None,
                control_lease=(
                    active_control
                ),
            )
            raise ActionPolicyRefused(
                decision.reason,
                receipt_id=receipt["id"],
            )

        shadow_decision = (
            evaluate_action_policy(
                shadow_policy,
                current,
            )
            if shadow_policy is not None
            else None
        )

        equivalent = (
            self._find_equivalent_fence(
                current
            )
            if fence_equivalent
            else None
        )
        if equivalent is not None:
            decision = ActionDecision(
                allowed=False,
                source="equivalent_fenced",
                rule_id=None,
                reason=(
                    "An equivalent action is already "
                    "pending or was refused in this "
                    "initiator context."
                ),
            )
            receipt = self._record_decision(
                candidate=candidate,
                current=current,
                decision=decision,
                approved_digest=(
                    approved_digest
                ),
                shadow_decision=(
                    shadow_decision
                ),
                equivalent_to_receipt_id=(
                    str(
                        equivalent["id"]
                    )
                ),
                control_lease=(
                    active_control
                ),
            )
            raise ActionPolicyRefused(
                decision.reason,
                receipt_id=receipt["id"],
            )

        decision = (
            evaluate_action_policy(
                policy,
                current,
            )
        )
        receipt = self._record_decision(
            candidate=candidate,
            current=current,
            decision=decision,
            approved_digest=(
                approved_digest
            ),
            shadow_decision=(
                shadow_decision
            ),
            equivalent_to_receipt_id=None,
            control_lease=(
                active_control
            ),
        )

        if not decision.allowed:
            raise ActionPolicyRefused(
                decision.reason,
                receipt_id=receipt["id"],
            )

        try:
            result = dispatch(
                current
            )
        except Exception as exc:
            self._mark_dispatch(
                receipt["id"],
                status="failed",
                error=str(exc),
            )
            raise

        self._mark_dispatch(
            receipt["id"],
            status="dispatched",
            error=None,
        )
        return result

    def inspect(
        self,
        receipt_id: str,
    ) -> dict[str, Any]:
        path = (
            self.receipts_dir
            / f"{receipt_id}.json"
        )
        if not path.exists():
            raise RuntimeError(
                "Action decision receipt not "
                f"found: {receipt_id}"
            )
        return json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    def list(
        self,
    ) -> list[dict[str, Any]]:
        if not self.receipts_dir.exists():
            return []
        return [
            json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
            for path in sorted(
                self.receipts_dir.glob(
                    "*.json"
                )
            )
        ]

    def _find_equivalent_fence(
        self,
        candidate: ActionCandidate,
    ) -> dict[str, Any] | None:
        scope = candidate.fence_scope
        if scope is None:
            return None

        receipts = sorted(
            self.list(),
            key=lambda item: str(
                item.get(
                    "recorded_at",
                    "",
                )
            ),
            reverse=True,
        )
        for receipt in receipts:
            if (
                receipt.get(
                    "equivalence_digest"
                )
                != candidate.equivalence_digest
            ):
                continue
            if (
                receipt.get(
                    "fence_scope"
                )
                != scope
            ):
                continue
            if (
                receipt.get("status")
                == "refused"
                or receipt.get(
                    "dispatch_status"
                )
                == "pending"
            ):
                return receipt
        return None

    def _record_decision(
        self,
        *,
        candidate: ActionCandidate,
        current: ActionCandidate
        | None,
        decision: ActionDecision,
        approved_digest: str
        | None,
        shadow_decision: ActionDecision
        | None,
        equivalent_to_receipt_id: str
        | None,
        control_lease: Mapping[str, Any]
        | None,
    ) -> dict[str, Any]:
        receipt_id = (
            "actdec_"
            f"{uuid4().hex[:12]}"
        )
        authoritative = (
            current or candidate
        )
        shadow_delta = (
            compare_shadow_decision(
                decision,
                shadow_decision,
            )
        )
        payload = {
            "schema": (
                "mado.action-decision.v1"
            ),
            "version": (
                ACTION_GATEWAY_VERSION
            ),
            "id": receipt_id,
            "recorded_at": utc_now(),
            "status": (
                "approved"
                if decision.allowed
                else "refused"
            ),
            "dispatch_status": (
                "pending"
                if decision.allowed
                else "not_dispatched"
            ),
            "action": (
                authoritative.action
            ),
            "effect": (
                authoritative.effect
            ),
            "actor": (
                authoritative.actor
            ),
            "initiator": (
                authoritative.initiator.to_dict()
            ),
            "control_scope": (
                authoritative.control_scope.to_dict()
                if authoritative.control_scope
                is not None
                else None
            ),
            "control_lease": (
                {
                    "id": control_lease["id"],
                    "holder": control_lease[
                        "holder"
                    ],
                    "expires_at": (
                        control_lease[
                            "expires_at"
                        ]
                    ),
                }
                if control_lease is not None
                else None
            ),
            "capability": (
                authoritative.capability
            ),
            "mission_id": (
                authoritative.mission_id
            ),
            "target_kind": (
                authoritative.target_kind
            ),
            "target": _stable(
                authoritative.target
            ),
            "arguments_digest": (
                authoritative.arguments_digest
            ),
            "equivalence_digest": (
                authoritative.equivalence_digest
            ),
            "fence_scope": (
                authoritative.fence_scope
            ),
            "candidate_digest": (
                candidate.digest
            ),
            "authoritative_digest": (
                current.digest
                if current is not None
                else None
            ),
            "approved_digest": (
                approved_digest
            ),
            "equivalent_to_receipt_id": (
                equivalent_to_receipt_id
            ),
            "decision": (
                decision.to_dict()
            ),
            "shadow_decision": (
                shadow_decision.to_dict()
                if shadow_decision is not None
                else None
            ),
            "shadow_delta": (
                shadow_delta
            ),
            "dispatched_at": None,
            "error": None,
        }
        self._write_receipt(
            receipt_id,
            payload,
        )
        if shadow_decision is not None:
            self.store.append_event(
                Event(
                    type=(
                        "action.shadow.evaluated"
                    ),
                    mission_id=(
                        authoritative.mission_id
                    ),
                    actor="policy_gateway",
                    subject={
                        "receipt_id": (
                            receipt_id
                        ),
                        "action": (
                            authoritative.action
                        ),
                        "live_allowed": (
                            decision.allowed
                        ),
                        "shadow_allowed": (
                            shadow_decision.allowed
                        ),
                        "shadow_source": (
                            shadow_decision.source
                        ),
                        "shadow_delta": (
                            shadow_delta
                        ),
                    },
                )
            )
        self.store.append_event(
            Event(
                type=(
                    "action.decision.recorded"
                ),
                mission_id=(
                    authoritative.mission_id
                ),
                actor="policy_gateway",
                subject={
                    "receipt_id": (
                        receipt_id
                    ),
                    "action": (
                        authoritative.action
                    ),
                    "effect": (
                        authoritative.effect
                    ),
                    "target_kind": (
                        authoritative.target_kind
                    ),
                    "allowed": (
                        decision.allowed
                    ),
                    "source": (
                        decision.source
                    ),
                    "rule_id": (
                        decision.rule_id
                    ),
                    "initiator_kind": (
                        authoritative.initiator.kind
                    ),
                    "equivalence_digest": (
                        authoritative.equivalence_digest
                    ),
                    "equivalent_to_receipt_id": (
                        equivalent_to_receipt_id
                    ),
                    "control_lease_id": (
                        control_lease["id"]
                        if control_lease
                        is not None
                        else None
                    ),
                },
            )
        )
        return payload

    def _mark_dispatch(
        self,
        receipt_id: str,
        *,
        status: Literal[
            "dispatched",
            "failed",
        ],
        error: str | None,
    ) -> None:
        payload = self.inspect(
            receipt_id
        )
        payload["dispatch_status"] = (
            status
        )
        payload["dispatched_at"] = (
            utc_now()
        )
        payload["error"] = error
        self._write_receipt(
            receipt_id,
            payload,
        )
        self.store.append_event(
            Event(
                type=(
                    "action.dispatched"
                    if status
                    == "dispatched"
                    else (
                        "action.dispatch.failed"
                    )
                ),
                mission_id=(
                    payload.get(
                        "mission_id"
                    )
                ),
                actor="policy_gateway",
                subject={
                    "receipt_id": (
                        receipt_id
                    ),
                    "action": (
                        payload["action"]
                    ),
                    "status": status,
                },
            )
        )

    def _write_receipt(
        self,
        receipt_id: str,
        payload: Mapping[
            str,
            Any,
        ],
    ) -> None:
        self.receipts_dir.mkdir(
            parents=True,
            exist_ok=True,
        )
        path = (
            self.receipts_dir
            / f"{receipt_id}.json"
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
