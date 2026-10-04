import json

import pytest

from mado_cockpit.action_gateway import (
    ActionCandidate,
    ActionInitiator,
    ActionPolicy,
    ActionPolicyGateway,
    ActionPolicyRefused,
    ActionRule,
    classify_external_mcp_effect,
    compare_shadow_decision,
    evaluate_action_policy,
    mado_internal_action_policy,
)
from mado_cockpit.control_lease import (
    ControlLeaseManager,
    ControlScope,
)
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


def _store(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="m2.2-fixture",
            name="M2.2 Fixture",
            root=str(tmp_path),
        )
    )
    return store


def _candidate(**changes):
    base = {
        "action": "external_write",
        "effect": "write",
        "target_kind": "mcp_tool",
        "target": {
            "server": "example",
            "tool": "update",
        },
        "arguments": {
            "id": "123",
        },
        "actor": "agent",
    }
    base.update(changes)
    return ActionCandidate(**base)


def test_default_policy_denies():
    decision = evaluate_action_policy(
        None,
        _candidate(),
    )

    assert decision.allowed is False
    assert decision.source == "default"


def test_deny_precedes_allow():
    policy = ActionPolicy(
        deny=(
            ActionRule(
                id="deny-write",
                predicate=lambda candidate: (
                    candidate.effect
                    == "write"
                ),
                reason="Writes are denied.",
            ),
        ),
        allow=(
            ActionRule(
                id="allow-all",
                predicate=lambda candidate: True,
                reason="Broad allow.",
            ),
        ),
    )

    decision = evaluate_action_policy(
        policy,
        _candidate(),
    )

    assert decision.allowed is False
    assert decision.source == "deny"
    assert decision.rule_id == "deny-write"


def test_broken_deny_rule_fails_closed():
    def broken(candidate):
        raise ValueError(
            "bad expression"
        )

    policy = ActionPolicy(
        deny=(
            ActionRule(
                id="broken-deny",
                predicate=broken,
                reason="Never reached.",
            ),
        ),
        allow=(
            ActionRule(
                id="allow-all",
                predicate=lambda candidate: True,
                reason="Broad allow.",
            ),
        ),
    )

    decision = evaluate_action_policy(
        policy,
        _candidate(),
    )

    assert decision.allowed is False
    assert (
        decision.source
        == "policy_error"
    )
    assert (
        decision.rule_id
        == "broken-deny"
    )


def test_broken_allow_rule_fails_closed():
    policy = ActionPolicy(
        allow=(
            ActionRule(
                id="broken-allow",
                predicate=lambda candidate: (
                    "not-a-bool"
                ),
                reason="Broken.",
            ),
        ),
    )

    decision = evaluate_action_policy(
        policy,
        _candidate(),
    )

    assert decision.allowed is False
    assert (
        decision.source
        == "policy_error"
    )


def test_unknown_external_mcp_is_write():
    assert (
        classify_external_mcp_effect(
            None
        )
        == "write"
    )
    assert (
        classify_external_mcp_effect(
            {}
        )
        == "write"
    )
    assert (
        classify_external_mcp_effect(
            {
                "readOnlyHint": False,
            }
        )
        == "write"
    )
    assert (
        classify_external_mcp_effect(
            {
                "readOnlyHint": True,
                "destructiveHint": True,
            }
        )
        == "write"
    )
    assert (
        classify_external_mcp_effect(
            {
                "readOnlyHint": True,
            }
        )
        == "read"
    )


def test_decision_receipt_exists_before_dispatch(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    seen = {}

    def dispatch(candidate):
        receipts = gateway.list()
        assert len(receipts) == 1
        receipt = receipts[0]
        assert (
            receipt["status"]
            == "approved"
        )
        assert (
            receipt["dispatch_status"]
            == "pending"
        )
        seen["receipt_id"] = (
            receipt["id"]
        )
        return "done"

    result = gateway.execute(
        _candidate(
            action=(
                "mado_advance_mission"
            ),
            target_kind="operator",
            target={
                "operator_id": "opr_1",
            },
        ),
        policy=(
            mado_internal_action_policy()
        ),
        dispatch=dispatch,
    )

    assert result == "done"
    receipt = gateway.inspect(
        seen["receipt_id"]
    )
    assert (
        receipt["dispatch_status"]
        == "dispatched"
    )
    events = store.list_events()
    decision_index = next(
        index
        for index, event
        in enumerate(events)
        if event["type"]
        == "action.decision.recorded"
    )
    dispatch_index = next(
        index
        for index, event
        in enumerate(events)
        if event["type"]
        == "action.dispatched"
    )
    assert decision_index < dispatch_index


def test_refused_action_never_dispatches(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    called = False

    def dispatch(candidate):
        nonlocal called
        called = True
        return "impossible"

    with pytest.raises(
        ActionPolicyRefused,
    ):
        gateway.execute(
            _candidate(),
            policy=ActionPolicy(),
            dispatch=dispatch,
        )

    assert called is False
    receipt = gateway.list()[0]
    assert (
        receipt["dispatch_status"]
        == "not_dispatched"
    )


def test_approved_action_is_revalidated_before_dispatch(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    approved = _candidate(
        target={
            "server": "example",
            "tool": "update",
            "object": "A",
        },
    )
    called = False

    def dispatch(candidate):
        nonlocal called
        called = True
        return "impossible"

    def revalidate(candidate):
        return candidate.with_target(
            {
                "server": "example",
                "tool": "update",
                "object": "B",
            }
        )

    with pytest.raises(
        ActionPolicyRefused,
        match="changed",
    ):
        gateway.execute(
            approved,
            policy=ActionPolicy(
                allow=(
                    ActionRule(
                        id="allow",
                        predicate=lambda candidate: True,
                        reason="Allowed.",
                    ),
                )
            ),
            revalidate=revalidate,
            approved_digest=(
                approved.digest
            ),
            dispatch=dispatch,
        )

    assert called is False
    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["source"]
        == "approval_changed"
    )


def test_revalidation_error_is_durable_refusal(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )

    def revalidate(candidate):
        raise RuntimeError(
            "current target disappeared"
        )

    with pytest.raises(
        ActionPolicyRefused,
        match="current target disappeared",
    ):
        gateway.execute(
            _candidate(),
            policy=ActionPolicy(
                allow=(
                    ActionRule(
                        id="allow",
                        predicate=lambda candidate: True,
                        reason="Allowed.",
                    ),
                )
            ),
            revalidate=revalidate,
            dispatch=lambda candidate: None,
        )

    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["source"]
        == "revalidation_error"
    )
    assert (
        receipt["dispatch_status"]
        == "not_dispatched"
    )


def test_receipt_stores_digest_not_raw_arguments(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    candidate = _candidate(
        arguments={
            "token": "secret-value",
        }
    )

    with pytest.raises(
        ActionPolicyRefused,
    ):
        gateway.execute(
            candidate,
            policy=ActionPolicy(),
            dispatch=lambda candidate: None,
        )

    raw = (
        gateway.receipts_dir
        .glob("*.json")
    )
    path = next(raw)
    text = path.read_text(
        encoding="utf-8"
    )
    payload = json.loads(text)
    assert "secret-value" not in text
    assert (
        payload["arguments_digest"]
        == candidate.arguments_digest
    )



def _allow_all_policy():
    return ActionPolicy(
        allow=(
            ActionRule(
                id="allow-all",
                predicate=lambda candidate: True,
                reason="Allow fixture action.",
            ),
        ),
    )


def _chat_candidate(
    *,
    context_id="thread-1",
    **changes,
):
    return _candidate(
        initiator=ActionInitiator(
            kind="chat",
            source="opendots:scout",
            context_id=context_id,
        ),
        **changes,
    )


def test_initiator_changes_full_digest_not_equivalence_digest():
    first = _chat_candidate(
        context_id="thread-1",
    )
    second = _chat_candidate(
        context_id="thread-2",
    )

    assert first.digest != second.digest
    assert (
        first.equivalence_digest
        == second.equivalence_digest
    )
    assert (
        first.fence_scope
        != second.fence_scope
    )


def test_shadow_deny_is_observed_but_does_not_block_live_allow(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    dispatched = []

    result = gateway.execute(
        _chat_candidate(),
        policy=_allow_all_policy(),
        shadow_policy=ActionPolicy(
            deny=(
                ActionRule(
                    id="shadow-deny",
                    predicate=lambda candidate: True,
                    reason="Shadow would deny.",
                ),
            ),
        ),
        dispatch=lambda candidate: (
            dispatched.append(
                candidate.action
            )
            or "done"
        ),
    )

    assert result == "done"
    assert dispatched == [
        "external_write"
    ]
    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["allowed"]
        is True
    )
    assert (
        receipt["shadow_decision"][
            "allowed"
        ]
        is False
    )
    assert (
        receipt["shadow_delta"]
        == "would_deny"
    )
    events = store.list_events()
    assert any(
        event["type"]
        == "action.shadow.evaluated"
        and event["subject"][
            "shadow_delta"
        ]
        == "would_deny"
        for event in events
    )


def test_shadow_allow_does_not_rescue_live_deny(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    called = False

    def dispatch(candidate):
        nonlocal called
        called = True

    with pytest.raises(
        ActionPolicyRefused,
    ):
        gateway.execute(
            _chat_candidate(),
            policy=ActionPolicy(),
            shadow_policy=(
                _allow_all_policy()
            ),
            dispatch=dispatch,
        )

    assert called is False
    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["allowed"]
        is False
    )
    assert (
        receipt["shadow_decision"][
            "allowed"
        ]
        is True
    )
    assert (
        receipt["shadow_delta"]
        == "would_allow"
    )


def test_shadow_policy_error_is_observed_only(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )

    def broken(candidate):
        raise RuntimeError(
            "shadow syntax error"
        )

    result = gateway.execute(
        _chat_candidate(),
        policy=_allow_all_policy(),
        shadow_policy=ActionPolicy(
            deny=(
                ActionRule(
                    id="broken-shadow",
                    predicate=broken,
                    reason="Broken shadow.",
                ),
            ),
        ),
        dispatch=lambda candidate: "done",
    )

    assert result == "done"
    receipt = gateway.list()[0]
    assert (
        receipt["shadow_decision"][
            "source"
        ]
        == "policy_error"
    )
    assert (
        receipt["shadow_delta"]
        == "would_deny"
    )


def test_refused_equivalent_action_is_fenced_in_same_context(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    candidate = _chat_candidate()
    called = False

    with pytest.raises(
        ActionPolicyRefused,
    ):
        gateway.execute(
            candidate,
            policy=ActionPolicy(),
            dispatch=lambda current: None,
        )

    def dispatch(current):
        nonlocal called
        called = True

    with pytest.raises(
        ActionPolicyRefused,
        match="equivalent action",
    ):
        gateway.execute(
            candidate,
            policy=_allow_all_policy(),
            dispatch=dispatch,
        )

    assert called is False
    receipts = sorted(
        gateway.list(),
        key=lambda item: item[
            "recorded_at"
        ],
    )
    assert len(receipts) == 2
    assert (
        receipts[1]["decision"][
            "source"
        ]
        == "equivalent_fenced"
    )
    assert (
        receipts[1][
            "equivalent_to_receipt_id"
        ]
        == receipts[0]["id"]
    )


def test_pending_equivalent_action_is_fenced_before_second_dispatch(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    candidate = _chat_candidate()
    nested_called = False

    def outer_dispatch(current):
        nonlocal nested_called

        def nested_dispatch(nested):
            nonlocal nested_called
            nested_called = True

        with pytest.raises(
            ActionPolicyRefused,
            match="equivalent action",
        ):
            gateway.execute(
                candidate,
                policy=_allow_all_policy(),
                dispatch=nested_dispatch,
            )
        return "outer-done"

    result = gateway.execute(
        candidate,
        policy=_allow_all_policy(),
        dispatch=outer_dispatch,
    )

    assert result == "outer-done"
    assert nested_called is False
    receipts = gateway.list()
    fenced = next(
        item
        for item in receipts
        if item["decision"]["source"]
        == "equivalent_fenced"
    )
    original = next(
        item
        for item in receipts
        if item["id"]
        == fenced[
            "equivalent_to_receipt_id"
        ]
    )
    assert (
        original["dispatch_status"]
        == "dispatched"
    )


def test_new_initiator_context_can_intentionally_retry_equivalent_action(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )

    with pytest.raises(
        ActionPolicyRefused,
    ):
        gateway.execute(
            _chat_candidate(
                context_id="thread-1"
            ),
            policy=ActionPolicy(),
            dispatch=lambda current: None,
        )

    result = gateway.execute(
        _chat_candidate(
            context_id="thread-2"
        ),
        policy=_allow_all_policy(),
        dispatch=lambda current: "retried",
    )

    assert result == "retried"
    receipts = gateway.list()
    assert any(
        item["dispatch_status"]
        == "dispatched"
        for item in receipts
    )


def test_receipt_separates_actor_and_initiator(
    tmp_path,
):
    store = _store(tmp_path)
    gateway = ActionPolicyGateway(
        store
    )
    candidate = _chat_candidate()

    gateway.execute(
        candidate,
        policy=_allow_all_policy(),
        dispatch=lambda current: None,
    )

    receipt = gateway.list()[0]
    assert receipt["actor"] == "agent"
    assert receipt["initiator"] == {
        "kind": "chat",
        "source": "opendots:scout",
        "context_id": "thread-1",
    }
    assert (
        receipt["equivalence_digest"]
        == candidate.equivalence_digest
    )
    assert (
        receipt["fence_scope"]
        == candidate.fence_scope
    )


def test_compare_shadow_decision_reports_same():
    live = evaluate_action_policy(
        _allow_all_policy(),
        _chat_candidate(),
    )
    shadow = evaluate_action_policy(
        _allow_all_policy(),
        _chat_candidate(),
    )

    assert (
        compare_shadow_decision(
            live,
            shadow,
        )
        == "same"
    )



def test_active_human_control_fences_automation_even_when_policy_allows(
    tmp_path,
):
    store = _store(tmp_path)
    leases = ControlLeaseManager(
        store
    )
    scope = ControlScope(
        "browser",
        "session-1",
    )
    lease = leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=120,
        reason="Interactive takeover.",
    )
    gateway = ActionPolicyGateway(
        store,
        control_leases=leases,
    )
    candidate = _chat_candidate(
        control_scope=scope,
    )
    called = False

    def dispatch(current):
        nonlocal called
        called = True

    with pytest.raises(
        ActionPolicyRefused,
        match="Human control is active",
    ):
        gateway.execute(
            candidate,
            policy=_allow_all_policy(),
            dispatch=dispatch,
        )

    assert called is False
    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["source"]
        == "human_control_fenced"
    )
    assert (
        receipt["control_lease"]["id"]
        == lease["id"]
    )
    assert (
        receipt["dispatch_status"]
        == "not_dispatched"
    )


def test_control_lease_holder_person_can_act_under_live_policy(
    tmp_path,
):
    store = _store(tmp_path)
    leases = ControlLeaseManager(
        store
    )
    scope = ControlScope(
        "computer",
        "computer-1",
    )
    lease = leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=120,
    )
    gateway = ActionPolicyGateway(
        store,
        control_leases=leases,
    )
    candidate = _candidate(
        actor="human:owner",
        initiator=ActionInitiator(
            kind="person",
            source="cockpit-ui",
            context_id="takeover-1",
        ),
        control_scope=scope,
    )

    result = gateway.execute(
        candidate,
        policy=_allow_all_policy(),
        dispatch=lambda current: "human-drove",
    )

    assert result == "human-drove"
    receipt = gateway.list()[0]
    assert (
        receipt["dispatch_status"]
        == "dispatched"
    )
    assert (
        receipt["control_lease"]["id"]
        == lease["id"]
    )


def test_different_person_cannot_act_under_someone_elses_control_lease(
    tmp_path,
):
    store = _store(tmp_path)
    leases = ControlLeaseManager(
        store
    )
    scope = ControlScope(
        "computer",
        "computer-1",
    )
    leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=120,
    )
    gateway = ActionPolicyGateway(
        store,
        control_leases=leases,
    )
    candidate = _candidate(
        actor="human:other",
        initiator=ActionInitiator(
            kind="person",
            source="cockpit-ui",
            context_id="takeover-2",
        ),
        control_scope=scope,
    )

    with pytest.raises(
        ActionPolicyRefused,
        match="Human control is active",
    ):
        gateway.execute(
            candidate,
            policy=_allow_all_policy(),
            dispatch=lambda current: None,
        )

    receipt = gateway.list()[0]
    assert (
        receipt["decision"]["source"]
        == "human_control_fenced"
    )


def test_release_removes_automation_fence(
    tmp_path,
):
    store = _store(tmp_path)
    leases = ControlLeaseManager(
        store
    )
    scope = ControlScope(
        "browser",
        "session-1",
    )
    lease = leases.acquire(
        scope,
        holder="human:owner",
        ttl_seconds=120,
    )
    leases.release(
        lease["id"],
        holder="human:owner",
    )
    gateway = ActionPolicyGateway(
        store,
        control_leases=leases,
    )

    result = gateway.execute(
        _chat_candidate(
            control_scope=scope,
        ),
        policy=_allow_all_policy(),
        dispatch=lambda current: "automation-resumed",
    )

    assert result == "automation-resumed"
    receipt = gateway.list()[0]
    assert (
        receipt["control_lease"]
        is None
    )


def test_control_scope_changes_equivalence_identity():
    first = _chat_candidate(
        control_scope=ControlScope(
            "browser",
            "session-1",
        )
    )
    second = _chat_candidate(
        control_scope=ControlScope(
            "browser",
            "session-2",
        )
    )

    assert (
        first.equivalence_digest
        != second.equivalence_digest
    )
    assert first.digest != second.digest
