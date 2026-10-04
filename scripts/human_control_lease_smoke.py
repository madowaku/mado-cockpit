from __future__ import annotations

import argparse
import json
from datetime import (
    datetime,
    timedelta,
    timezone,
)
from pathlib import Path

from mado_cockpit.action_gateway import (
    ActionCandidate,
    ActionInitiator,
    ActionPolicy,
    ActionPolicyGateway,
    ActionPolicyRefused,
    ActionRule,
)
from mado_cockpit.control_lease import (
    ControlLeaseManager,
    ControlScope,
)
from mado_cockpit.models import (
    Project,
)
from mado_cockpit.store import (
    CockpitStore,
)


SMOKE_VERSION = "MCC-M2.4"


class Clock:
    def __init__(self) -> None:
        self.value = datetime(
            2026,
            10,
            4,
            7,
            0,
            tzinfo=timezone.utc,
        )

    def now(self) -> datetime:
        return self.value

    def advance(
        self,
        seconds: int,
    ) -> None:
        self.value += timedelta(
            seconds=seconds
        )


def _policy() -> ActionPolicy:
    return ActionPolicy(
        allow=(
            ActionRule(
                id="allow:browser-input",
                predicate=lambda candidate: (
                    candidate.action
                    == "browser.click"
                ),
                reason=(
                    "Fixture permits browser click."
                ),
            ),
        ),
    )


def _automation(
    scope: ControlScope,
) -> ActionCandidate:
    return ActionCandidate(
        action="browser.click",
        effect="write",
        target_kind="browser_element",
        target={
            "session_id": (
                scope.resource_id
            ),
            "ref": "button-continue",
        },
        arguments={
            "button": "left",
        },
        actor="dot:scout",
        initiator=ActionInitiator(
            kind="chat",
            source="opendots:scout",
            context_id="thread-control",
        ),
        control_scope=scope,
    )


def _human(
    scope: ControlScope,
) -> ActionCandidate:
    return ActionCandidate(
        action="browser.click",
        effect="write",
        target_kind="browser_element",
        target={
            "session_id": (
                scope.resource_id
            ),
            "ref": "button-continue",
        },
        arguments={
            "button": "left",
        },
        actor="human:owner",
        initiator=ActionInitiator(
            kind="person",
            source="cockpit-control-ui",
            context_id="takeover-1",
        ),
        control_scope=scope,
    )


def run(
    root: Path,
) -> dict[str, object]:
    store = CockpitStore(root)
    store.init(
        Project(
            id="mcc-m2.4-control",
            name="MCC-M2.4 Control",
            root=str(root),
        )
    )
    clock = Clock()
    leases = ControlLeaseManager(
        store,
        now=clock.now,
    )
    gateway = ActionPolicyGateway(
        store,
        control_leases=leases,
    )
    scope = ControlScope(
        "browser",
        "browser-session-m2.4",
    )
    policy = _policy()
    dispatched: list[str] = []

    first = leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=60,
        reason=(
            "Person is completing an "
            "interactive login."
        ),
    )
    clock.advance(20)
    renewed = leases.heartbeat(
        first["id"],
        holder="human:owner",
        ttl_seconds=90,
    )

    agent = _automation(
        scope
    )
    try:
        gateway.execute(
            agent,
            policy=policy,
            dispatch=lambda current: (
                dispatched.append(
                    "agent-during-control"
                )
            ),
        )
    except ActionPolicyRefused as exc:
        fenced_receipt = (
            gateway.inspect(
                exc.receipt_id
            )
        )
    else:
        raise RuntimeError(
            "Automation dispatched while "
            "human control was active."
        )

    human_result = gateway.execute(
        _human(scope),
        policy=policy,
        dispatch=lambda current: (
            dispatched.append(
                "human-under-control"
            )
            or "human-ok"
        ),
    )
    if human_result != "human-ok":
        raise RuntimeError(
            "Lease holder human action failed."
        )

    released = leases.release(
        first["id"],
        holder="human:owner",
    )
    resumed_result = gateway.execute(
        agent,
        policy=policy,
        dispatch=lambda current: (
            dispatched.append(
                "agent-after-release"
            )
            or "resumed"
        ),
    )
    if resumed_result != "resumed":
        raise RuntimeError(
            "Automation did not resume "
            "after release."
        )

    second = leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=15,
        reason="Short takeover.",
    )
    try:
        gateway.execute(
            agent,
            policy=policy,
            dispatch=lambda current: (
                dispatched.append(
                    "agent-before-expiry"
                )
            ),
        )
    except ActionPolicyRefused as exc:
        expiry_fence_receipt = (
            gateway.inspect(
                exc.receipt_id
            )
        )
    else:
        raise RuntimeError(
            "Automation dispatched before "
            "lease expiry."
        )

    clock.advance(16)
    expired_result = gateway.execute(
        agent,
        policy=policy,
        dispatch=lambda current: (
            dispatched.append(
                "agent-after-expiry"
            )
            or "expired-resumed"
        ),
    )
    if (
        expired_result
        != "expired-resumed"
    ):
        raise RuntimeError(
            "Automation did not resume "
            "after expiry."
        )

    second_state = leases.inspect(
        second["id"]
    )
    if (
        second_state["status"]
        != "expired"
    ):
        raise RuntimeError(
            "Second lease did not expire."
        )

    if (
        fenced_receipt[
            "decision"
        ]["source"]
        != "human_control_fenced"
        or fenced_receipt[
            "control_lease"
        ]["id"]
        != first["id"]
    ):
        raise RuntimeError(
            "First automation refusal was "
            "not linked to Human Control."
        )
    if (
        expiry_fence_receipt[
            "decision"
        ]["source"]
        != "human_control_fenced"
        or expiry_fence_receipt[
            "control_lease"
        ]["id"]
        != second["id"]
    ):
        raise RuntimeError(
            "Expiry fence receipt mismatch."
        )

    if dispatched != [
        "human-under-control",
        "agent-after-release",
        "agent-after-expiry",
    ]:
        raise RuntimeError(
            "Unexpected dispatch sequence: "
            + repr(dispatched)
        )

    events = store.list_events(
        limit=500
    )
    event_types = [
        event["type"]
        for event in events
    ]
    required = {
        "control.lease.acquired",
        "control.lease.heartbeat",
        "control.lease.released",
        "control.lease.expired",
        "action.decision.recorded",
        "action.dispatched",
    }
    missing = (
        required
        - set(event_types)
    )
    if missing:
        raise RuntimeError(
            "Missing M2.4 events: "
            + ", ".join(
                sorted(missing)
            )
        )

    human_receipt = next(
        receipt
        for receipt in gateway.list()
        if (
            receipt["actor"]
            == "human:owner"
            and receipt[
                "dispatch_status"
            ]
            == "dispatched"
        )
    )

    return {
        "schema": (
            "mado.human-control-smoke.v1"
        ),
        "version": SMOKE_VERSION,
        "ok": True,
        "scope": scope.to_dict(),
        "first_lease": {
            "id": first["id"],
            "heartbeat_extended": (
                renewed["expires_at"]
                != first["expires_at"]
            ),
            "released_status": (
                released["status"]
            ),
        },
        "automation_fence": {
            "receipt_id": (
                fenced_receipt["id"]
            ),
            "source": (
                fenced_receipt[
                    "decision"
                ]["source"]
            ),
            "dispatch_status": (
                fenced_receipt[
                    "dispatch_status"
                ]
            ),
        },
        "human_under_control": {
            "receipt_id": (
                human_receipt["id"]
            ),
            "dispatch_status": (
                human_receipt[
                    "dispatch_status"
                ]
            ),
            "lease_id": (
                human_receipt[
                    "control_lease"
                ]["id"]
            ),
        },
        "after_release": {
            "automation_resumed": True,
        },
        "second_lease": {
            "id": second["id"],
            "expired_status": (
                second_state["status"]
            ),
            "fence_receipt_id": (
                expiry_fence_receipt[
                    "id"
                ]
            ),
        },
        "after_expiry": {
            "automation_resumed": True,
        },
        "dispatch_sequence": (
            dispatched
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        required=True,
    )
    args = parser.parse_args()
    root = Path(
        args.root
    ).resolve()
    root.mkdir(
        parents=True,
        exist_ok=True,
    )
    result = run(root)
    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
