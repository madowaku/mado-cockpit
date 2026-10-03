import json

import pytest

from mado_cockpit.models import Project
from mado_cockpit.opendots import (
    ADAPTER_VERSION,
    SCHEMA,
    OpenDotsAdapterError,
    OpenDotsRuntimeAdapter,
)
from mado_cockpit.store import CockpitStore


class FakeRuntime:
    def __init__(self):
        self.calls = []

    def inspect(self, operator_id):
        self.calls.append(("inspect", operator_id))
        return {
            "operator_id": operator_id,
            "state": {"status": "awaiting_builder"},
        }

    def advance(self, operator_id):
        self.calls.append(("advance", operator_id))
        return {
            "operator_id": operator_id,
            "state": {"status": "awaiting_qa"},
        }

    def resolve_gate(
        self,
        operator_id,
        *,
        choice=None,
        choose_for_me=False,
        note=None,
    ):
        self.calls.append(
            (
                "resolve_gate",
                operator_id,
                choice,
                choose_for_me,
                note,
            )
        )
        return {
            "operator_id": operator_id,
            "resolution": choice or "safe_default",
        }


def _adapter(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    runtime = FakeRuntime()
    return (
        OpenDotsRuntimeAdapter(
            store,
            runtime=runtime,
        ),
        runtime,
        store,
    )


def _request(
    *,
    request_id="od_req_001",
    action="operator.status",
    payload=None,
):
    return {
        "schema": SCHEMA,
        "request_id": request_id,
        "action": action,
        "source": {
            "dot_id": "scout",
            "space_id": "space-alpha",
            "thread_id": "thread-1",
        },
        "target": {
            "operator_id": "opr_fixture",
        },
        "payload": payload or {},
    }


def test_status_request_returns_versioned_response(tmp_path):
    adapter, runtime, store = _adapter(tmp_path)

    response = adapter.handle(_request())

    assert response["status"] == "ok"
    assert response["adapter_version"] == ADAPTER_VERSION
    assert response["data"]["operator_id"] == "opr_fixture"
    assert runtime.calls == [("inspect", "opr_fixture")]

    receipts = list(
        (
            store.base
            / "integrations"
            / "opendots"
            / "receipts"
        ).glob("*.json")
    )
    assert len(receipts) == 1


def test_same_request_id_replays_without_second_side_effect(tmp_path):
    adapter, runtime, _ = _adapter(tmp_path)
    request = _request(action="operator.advance")

    first = adapter.handle(request)
    second = adapter.handle(request)

    assert second == first
    assert runtime.calls == [
        ("advance", "opr_fixture")
    ]


def test_same_request_id_with_different_content_is_rejected(tmp_path):
    adapter, _, _ = _adapter(tmp_path)
    adapter.handle(_request())

    with pytest.raises(
        OpenDotsAdapterError,
        match="already used",
    ):
        adapter.handle(
            _request(
                action="operator.advance",
            )
        )


def test_model_launch_is_not_exposed(tmp_path):
    adapter, runtime, _ = _adapter(tmp_path)

    with pytest.raises(
        OpenDotsAdapterError,
        match="not allowed",
    ):
        adapter.handle(
            _request(
                action="operator.launch",
            )
        )

    assert runtime.calls == []


def test_gate_resolution_requires_one_resolution_mode(tmp_path):
    adapter, runtime, _ = _adapter(tmp_path)

    response = adapter.handle(
        _request(
            action="gate.resolve",
            payload={
                "choice": "stay_free",
                "note": "Keep the zero-cost path.",
            },
        )
    )

    assert response["status"] == "ok"
    assert runtime.calls == [
        (
            "resolve_gate",
            "opr_fixture",
            "stay_free",
            False,
            "Keep the zero-cost path.",
        )
    ]

    with pytest.raises(
        OpenDotsAdapterError,
        match="exactly one",
    ):
        adapter.handle(
            _request(
                request_id="od_req_002",
                action="gate.resolve",
                payload={
                    "choice": "stay_free",
                    "choose_for_me": True,
                },
            )
        )


def test_runtime_error_becomes_stable_error_receipt(tmp_path):
    class BrokenRuntime(FakeRuntime):
        def inspect(self, operator_id):
            self.calls.append(("inspect", operator_id))
            raise RuntimeError("operator missing")

    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    runtime = BrokenRuntime()
    adapter = OpenDotsRuntimeAdapter(
        store,
        runtime=runtime,
    )

    first = adapter.handle(_request())
    second = adapter.handle(_request())

    assert first["status"] == "error"
    assert first["error"]["code"] == "cockpit_runtime_error"
    assert second == first
    assert runtime.calls == [
        ("inspect", "opr_fixture")
    ]


def test_receipt_does_not_log_transport_credentials(tmp_path):
    adapter, _, store = _adapter(tmp_path)

    with pytest.raises(
        OpenDotsAdapterError,
        match="unsupported fields",
    ):
        adapter.handle(
            {
                **_request(),
                "authorization": "secret",
            }
        )

    receipts_dir = (
        store.base
        / "integrations"
        / "opendots"
        / "receipts"
    )
    assert not receipts_dir.exists()


def test_completed_event_contains_metadata_not_payload(tmp_path):
    adapter, _, store = _adapter(tmp_path)
    adapter.handle(
        _request(
            action="gate.resolve",
            payload={
                "choice": "stay_free",
                "note": "private-ish note",
            },
        )
    )

    events = store.list_events()
    event = events[-1]
    assert event["type"] == "opendots.request.completed"
    assert event["actor"] == "opendots"
    assert event["subject"]["dot_id"] == "scout"
    assert "private-ish note" not in json.dumps(
        event["subject"]
    )
