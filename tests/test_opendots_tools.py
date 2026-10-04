import json

import pytest

from mado_cockpit.models import Project
from mado_cockpit.opendots import OpenDotsRuntimeAdapter
from mado_cockpit.opendots_tools import (
    TOOL_CALL_SCHEMA,
    TOOL_RESULT_SCHEMA,
    TOOL_SURFACE_VERSION,
    OpenDotsToolError,
    OpenDotsToolSurface,
    tool_catalog,
)
from mado_cockpit.store import CockpitStore


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.status = "awaiting_builder"

    def inspect(self, operator_id):
        self.calls.append(("inspect", operator_id))
        return operator_view(
            operator_id,
            status=self.status,
        )

    def advance(self, operator_id):
        self.calls.append(("advance", operator_id))
        self.status = "awaiting_qa"
        return operator_view(
            operator_id,
            status=self.status,
            qa=True,
        )

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
        self.status = "awaiting_builder"
        return {
            "gate": {
                "resolution": {
                    "gate_id": "gate_1",
                    "choice": (
                        choice
                        or "stay_free"
                    ),
                    "method": (
                        "safe_default"
                        if choose_for_me
                        else "human"
                    ),
                    "resolved_at": "now",
                }
            },
            "operator": operator_view(
                operator_id,
                status=self.status,
            ),
        }


class FakeOperator:
    def __init__(self, view):
        self.view = view

    def inspect(self, operator_id):
        assert operator_id == self.view["plan"]["id"]
        return self.view


class FakeEvidence:
    def __init__(
        self,
        *,
        bundles=None,
        results=None,
    ):
        self.bundles = bundles or {}
        self.results = results or {}

    def list_bundles(self, task_id):
        return self.bundles.get(
            task_id,
            [],
        )

    def list_results(self, task_id):
        return self.results.get(
            task_id,
            [],
        )


def operator_view(
    operator_id="opr_fixture",
    *,
    status="awaiting_builder",
    qa=False,
    gate=None,
    handoff=None,
):
    return {
        "plan": {
            "id": operator_id,
            "mission_id": "MCC-DEMO",
            "objective": "Build safely",
        },
        "state": {
            "status": status,
        },
        "builder_task": {
            "id": "task_builder",
            "status": "assigned",
            "required_evidence": [
                "git_diff",
                "test_result",
            ],
        },
        "builder_workspace": {
            "path": "/secret/worktree",
        },
        "qa_workspace": {
            "path": "/secret/qa",
        },
        "builder_session": {
            "last_trace": ".mado/private.jsonl",
        },
        "qa_session": None,
        "builder_capabilities": [],
        "qa_capabilities": [],
        "qa_task": (
            {
                "id": "task_qa",
                "status": "assigned",
                "required_evidence": [
                    "qa_report"
                ],
            }
            if qa
            else None
        ),
        "handoff": handoff,
        "human_gate": gate,
        "next_action": (
            "launch_qa"
            if qa
            else "launch_builder"
        ),
    }


def gate_view():
    return {
        "gate": {
            "id": "gate_1",
            "question": "Enable paid path?",
            "reason": "May create charges.",
            "materiality": "cost",
            "choices": [
                "enable_paid",
                "stay_free",
            ],
            "impacts": {
                "stay_free": "No charge.",
            },
            "recommendation": "stay_free",
            "safe_default": "stay_free",
            "allow_choose_for_me": True,
        },
        "status": {
            "status": "open",
        },
        "resolution": None,
    }


def call(
    tool_name,
    arguments,
    *,
    tool_call_id="call-1",
):
    return {
        "schema": TOOL_CALL_SCHEMA,
        "tool_call_id": tool_call_id,
        "tool_name": tool_name,
        "context": {
            "dot_id": "scout",
            "space_id": "space-1",
            "thread_id": "thread-1",
        },
        "arguments": arguments,
    }


def setup_surface(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    runtime = FakeRuntime()
    adapter = OpenDotsRuntimeAdapter(
        store,
        runtime=runtime,
    )
    return (
        OpenDotsToolSurface(
            store,
            runtime_adapter=adapter,
        ),
        runtime,
        store,
    )


def test_catalog_exposes_five_bounded_tools():
    tools = tool_catalog()

    assert [tool["name"] for tool in tools] == [
        "mado_check_mission",
        "mado_advance_mission",
        "mado_answer_human_gate",
        "mado_show_evidence",
        "mado_show_qa_result",
    ]
    assert tools[0]["read_only"] is True
    assert tools[1]["read_only"] is False
    assert (
        tools[2][
            "requires_explicit_user_choice"
        ]
        is True
    )


def test_check_mission_returns_sanitized_agui_projection(tmp_path):
    surface, runtime, _ = setup_surface(tmp_path)

    result = surface.handle(
        call(
            "mado_check_mission",
            {"operator_id": "opr_fixture"},
        )
    )

    assert result["schema"] == TOOL_RESULT_SCHEMA
    assert result["surface_version"] == TOOL_SURFACE_VERSION
    assert result["ok"] is True
    assert result["presentation"]["kind"] == "mission_status"
    assert result["data"]["status"] == "awaiting_builder"
    assert runtime.calls == [
        ("inspect", "opr_fixture")
    ]
    serialized = json.dumps(result)
    assert "/secret/worktree" not in serialized
    assert ".mado/private.jsonl" not in serialized


def test_advance_replays_same_tool_call_without_duplicate_effect(tmp_path):
    surface, runtime, _ = setup_surface(tmp_path)
    request = call(
        "mado_advance_mission",
        {"operator_id": "opr_fixture"},
        tool_call_id="agui-call-77",
    )

    first = surface.handle(request)
    second = surface.handle(request)

    assert first == second
    assert runtime.calls == [
        ("advance", "opr_fixture")
    ]
    assert first["data"]["status"] == "awaiting_qa"


def test_human_gate_maps_explicit_choice_to_runtime(tmp_path):
    surface, runtime, _ = setup_surface(tmp_path)

    result = surface.handle(
        call(
            "mado_answer_human_gate",
            {
                "operator_id": "opr_fixture",
                "choice": "stay_free",
                "note": "Use the free path.",
            },
        )
    )

    assert result["ok"] is True
    assert (
        result["presentation"]["kind"]
        == "human_gate_resolved"
    )
    assert result["data"]["resolution"]["choice"] == "stay_free"
    assert runtime.calls == [
        (
            "resolve_gate",
            "opr_fixture",
            "stay_free",
            False,
            "Use the free path.",
        )
    ]


def test_human_gate_requires_exactly_one_resolution_mode(tmp_path):
    surface, _, _ = setup_surface(tmp_path)

    with pytest.raises(
        OpenDotsToolError,
        match="exactly one",
    ):
        surface.handle(
            call(
                "mado_answer_human_gate",
                {
                    "operator_id": "opr_fixture",
                    "choice": "stay_free",
                    "choose_for_me": True,
                },
            )
        )


def test_evidence_view_omits_internal_paths(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    view = operator_view()
    evidence = FakeEvidence(
        bundles={
            "task_builder": [
                {
                    "id": "evb_1",
                    "task_id": "task_builder",
                    "status": "validated",
                    "required_evidence": [
                        "test_result"
                    ],
                    "missing_evidence": [],
                    "items": [
                        {
                            "id": "evi_1",
                            "kind": "test_result",
                            "path": (
                                ".mado/cockpit/evidence/"
                                "private/tests.txt"
                            ),
                            "sha256": "abc",
                            "size_bytes": 42,
                            "source": "workspace_file",
                            "description": "tests",
                        }
                    ],
                    "created_at": "now",
                }
            ]
        },
        results={
            "task_builder": [
                {
                    "id": "res_1",
                    "task_id": "task_builder",
                    "status": "completed",
                    "summary": "Tests passed.",
                    "evidence_bundle_id": "evb_1",
                    "evidence_status": "validated",
                    "readiness": "ready_for_qa",
                    "missing_evidence": [],
                    "risks": [],
                    "changes": [
                        "secret/file.py"
                    ],
                    "submitted_at": "now",
                }
            ]
        },
    )
    surface = OpenDotsToolSurface(
        store,
        operator=FakeOperator(view),
        evidence=evidence,
    )

    result = surface.handle(
        call(
            "mado_show_evidence",
            {
                "operator_id": "opr_fixture",
                "scope": "builder",
            },
        )
    )

    assert result["ok"] is True
    assert (
        result["presentation"]["status"]
        == "validated"
    )
    serialized = json.dumps(result)
    assert "private/tests.txt" not in serialized
    assert "secret/file.py" not in serialized
    assert '"sha256": "abc"' in serialized


def test_qa_result_projects_latest_result_and_verdict(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    handoff = {
        "handoff": {
            "id": "hnd_1",
            "source_task_id": "task_builder",
            "source_result_id": "res_builder",
            "source_bundle_id": "evb_builder",
            "qa_task_id": "task_qa",
            "snapshot_path": (
                ".mado/private/snapshot"
            ),
            "created_at": "now",
        },
        "status": {
            "status": "pass",
        },
        "verdict": {
            "id": "qav_1",
            "handoff_id": "hnd_1",
            "qa_result_id": "res_qa",
            "verdict": "pass",
            "summary": "Independent QA passed.",
            "source_snapshot_sha256": "secret",
            "created_at": "later",
        },
    }
    view = operator_view(
        status="completed",
        qa=True,
        handoff=handoff,
    )
    evidence = FakeEvidence(
        results={
            "task_qa": [
                {
                    "id": "res_qa",
                    "task_id": "task_qa",
                    "status": "completed",
                    "summary": "QA checks complete.",
                    "evidence_bundle_id": "evb_qa",
                    "evidence_status": "validated",
                    "readiness": "ready_for_qa",
                    "missing_evidence": [],
                    "risks": [],
                    "submitted_at": "later",
                }
            ]
        }
    )
    surface = OpenDotsToolSurface(
        store,
        operator=FakeOperator(view),
        evidence=evidence,
    )

    result = surface.handle(
        call(
            "mado_show_qa_result",
            {"operator_id": "opr_fixture"},
        )
    )

    assert result["data"]["verdict"]["verdict"] == "pass"
    assert (
        result["presentation"]["summary"]
        == "Independent QA passed."
    )
    serialized = json.dumps(result)
    assert "snapshot_path" not in serialized
    assert "source_snapshot_sha256" not in serialized


def test_status_projection_includes_open_human_gate(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    runtime = FakeRuntime()
    runtime.inspect = lambda operator_id: operator_view(
        operator_id,
        status="awaiting_human",
        gate=gate_view(),
    )
    surface = OpenDotsToolSurface(
        store,
        runtime_adapter=OpenDotsRuntimeAdapter(
            store,
            runtime=runtime,
        ),
    )

    result = surface.handle(
        call(
            "mado_check_mission",
            {"operator_id": "opr_fixture"},
        )
    )

    gate = result["data"]["human_gate"]
    assert gate["question"] == "Enable paid path?"
    assert gate["safe_default"] == "stay_free"
    assert (
        result["presentation"]["human_gate"]["choices"]
        == ["enable_paid", "stay_free"]
    )


def test_unknown_tool_is_rejected_before_cockpit_execution(tmp_path):
    surface, runtime, _ = setup_surface(tmp_path)

    with pytest.raises(
        OpenDotsToolError,
        match="unsupported tool",
    ):
        surface.handle(
            {
                **call(
                    "mado_check_mission",
                    {
                        "operator_id": (
                            "opr_fixture"
                        )
                    },
                ),
                "tool_name": "mado_launch_agent",
            }
        )

    assert runtime.calls == []



def test_advance_write_records_policy_receipt(tmp_path):
    surface, runtime, store = setup_surface(tmp_path)

    result = surface.handle(
        call(
            "mado_advance_mission",
            {"operator_id": "opr_fixture"},
        )
    )

    assert result["ok"] is True
    receipts = sorted(
        (
            store.base
            / "action_decisions"
        ).glob("*.json")
    )
    assert len(receipts) == 1
    receipt = json.loads(
        receipts[0].read_text(
            encoding="utf-8"
        )
    )
    assert (
        receipt["action"]
        == "mado_advance_mission"
    )
    assert receipt["effect"] == "write"
    assert (
        receipt["decision"]["allowed"]
        is True
    )
    assert (
        receipt["dispatch_status"]
        == "dispatched"
    )
    assert runtime.calls == [
        ("advance", "opr_fixture")
    ]


def test_bound_human_gate_revalidates_before_resolution(tmp_path):
    surface, runtime, store = setup_surface(tmp_path)
    runtime.inspect = lambda operator_id: operator_view(
        operator_id,
        status="awaiting_human",
        gate=gate_view(),
    )

    result = surface.handle(
        call(
            "mado_answer_human_gate",
            {
                "operator_id": "opr_fixture",
                "gate_id": "gate_1",
                "choice": "stay_free",
            },
        )
    )

    assert result["ok"] is True
    assert (
        runtime.calls[-1][0]
        == "resolve_gate"
    )
    receipt_path = next(
        (
            store.base
            / "action_decisions"
        ).glob("*.json")
    )
    receipt = json.loads(
        receipt_path.read_text(
            encoding="utf-8"
        )
    )
    assert (
        receipt["target"]["gate_id"]
        == "gate_1"
    )
    assert (
        receipt["approved_digest"]
        == receipt[
            "authoritative_digest"
        ]
    )


def test_stale_bound_gate_is_durable_policy_refusal(tmp_path):
    surface, runtime, store = setup_surface(tmp_path)
    runtime.inspect = lambda operator_id: operator_view(
        operator_id,
        status="awaiting_human",
        gate=gate_view(),
    )

    result = surface.handle(
        call(
            "mado_answer_human_gate",
            {
                "operator_id": "opr_fixture",
                "gate_id": "gate_stale",
                "choice": "stay_free",
            },
        )
    )

    assert result["ok"] is False
    assert (
        result["error"]["code"]
        == "action_refused"
    )
    assert "no longer matches" in (
        result["error"]["message"]
    )
    assert not any(
        item[0] == "resolve_gate"
        for item in runtime.calls
    )
    receipt_path = next(
        (
            store.base
            / "action_decisions"
        ).glob("*.json")
    )
    receipt = json.loads(
        receipt_path.read_text(
            encoding="utf-8"
        )
    )
    assert (
        receipt["decision"]["source"]
        == "revalidation_error"
    )
    assert (
        receipt["dispatch_status"]
        == "not_dispatched"
    )
