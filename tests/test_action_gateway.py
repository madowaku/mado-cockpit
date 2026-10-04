import json

import pytest

from mado_cockpit.action_gateway import (
    ActionCandidate,
    ActionPolicy,
    ActionPolicyGateway,
    ActionPolicyRefused,
    ActionRule,
    classify_external_mcp_effect,
    evaluate_action_policy,
    mado_internal_action_policy,
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
