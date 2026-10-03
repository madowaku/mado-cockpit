import json
from pathlib import Path

import pytest

from mado_cockpit.models import Project
from mado_cockpit.opendots import OpenDotsRuntimeAdapter
from mado_cockpit.opendots_tools import (
    TOOL_CALL_SCHEMA,
    OpenDotsToolError,
    OpenDotsToolSurface,
    tool_catalog,
)
from mado_cockpit.store import CockpitStore


ROOT = Path(__file__).resolve().parents[1]


class GateRuntime:
    def __init__(self):
        self.calls = []

    def _operator(self, operator_id, *, gate=True):
        return {
            "plan": {
                "id": operator_id,
                "mission_id": "MCC-DEMO",
                "objective": "Keep control with the human.",
            },
            "state": {
                "status": (
                    "awaiting_human"
                    if gate
                    else "awaiting_builder"
                ),
            },
            "builder_task": {
                "id": "task_builder",
                "status": "assigned",
                "required_evidence": ["test_result"],
            },
            "builder_workspace": {
                "path": "/private/builder",
            },
            "qa_workspace": {
                "path": "/private/qa",
            },
            "builder_capabilities": [],
            "qa_capabilities": [],
            "builder_session": None,
            "qa_session": None,
            "handoff": None,
            "qa_task": None,
            "human_gate": (
                {
                    "gate": {
                        "id": "gate_current",
                        "question": "Use paid provider?",
                        "reason": "This may create cost.",
                        "materiality": "cost",
                        "choices": [
                            "stay_free",
                            "enable_paid",
                        ],
                        "impacts": {},
                        "recommendation": "stay_free",
                        "safe_default": "stay_free",
                        "allow_choose_for_me": True,
                    },
                    "status": {
                        "status": "open",
                    },
                    "resolution": None,
                }
                if gate
                else None
            ),
            "next_action": (
                "await_human"
                if gate
                else "launch_builder"
            ),
        }

    def inspect(self, operator_id):
        self.calls.append(("inspect", operator_id))
        return self._operator(operator_id)

    def advance(self, operator_id):
        self.calls.append(("advance", operator_id))
        return self._operator(operator_id)

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
            "gate": {
                "resolution": {
                    "gate_id": "gate_current",
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
            "operator": self._operator(
                operator_id,
                gate=False,
            ),
        }


def _surface(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    runtime = GateRuntime()
    surface = OpenDotsToolSurface(
        store,
        runtime_adapter=OpenDotsRuntimeAdapter(
            store,
            runtime=runtime,
        ),
    )
    return surface, runtime


def _gate_call(
    gate_id,
    *,
    tool_call_id="hitl-forward-1",
):
    return {
        "schema": TOOL_CALL_SCHEMA,
        "tool_call_id": tool_call_id,
        "tool_name": "mado_answer_human_gate",
        "context": {
            "dot_id": "scout",
            "space_id": "space-1",
            "thread_id": "thread-1",
        },
        "arguments": {
            "operator_id": "opr_fixture",
            "gate_id": gate_id,
            "choice": "stay_free",
            "choose_for_me": False,
            "note": "Keep the free path.",
        },
    }


def test_gate_id_is_exposed_in_server_tool_catalog():
    answer = next(
        item
        for item in tool_catalog()
        if item["name"]
        == "mado_answer_human_gate"
    )

    assert (
        "gate_id"
        in answer["parameters"]["properties"]
    )


def test_matching_gate_id_is_validated_then_resolved(tmp_path):
    surface, runtime = _surface(tmp_path)

    result = surface.handle(
        _gate_call("gate_current")
    )

    assert result["ok"] is True
    assert result["data"]["resolution"]["choice"] == "stay_free"
    assert runtime.calls == [
        ("inspect", "opr_fixture"),
        (
            "resolve_gate",
            "opr_fixture",
            "stay_free",
            False,
            "Keep the free path.",
        ),
    ]


def test_stale_gate_card_cannot_resolve_new_gate(tmp_path):
    surface, runtime = _surface(tmp_path)

    with pytest.raises(
        OpenDotsToolError,
        match="no longer matches",
    ):
        surface.handle(
            _gate_call(
                "gate_old",
                tool_call_id="stale-card-1",
            )
        )

    assert runtime.calls == [
        ("inspect", "opr_fixture")
    ]


def test_m14_renderer_contract_is_two_phase():
    contract = json.loads(
        (
            ROOT
            / "fixtures"
            / "opendots"
            / "mcc-m1.4-renderer-contract.json"
        ).read_text(encoding="utf-8")
    )

    assert contract["renderer_version"] == "MCC-M1.4"
    assert (
        contract["human_gate"]["frontend_tool"]
        == "mado_review_human_gate"
    )
    assert (
        contract["human_gate"]["then_server_tool"]
        == "mado_answer_human_gate"
    )
    assert (
        contract["human_gate"][
            "direct_cockpit_mutation"
        ]
        is False
    )
    assert (
        contract["human_gate"]["requires_gate_id"]
        is True
    )


def test_renderer_registers_cards_and_hitl_without_runtime_bridge():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "mado-cockpit-renderers.tsx"
    ).read_text(encoding="utf-8")

    assert "useRenderTool" in source
    assert "useHumanInTheLoop" in source
    assert "mado_review_human_gate" not in source
    assert "madoHumanGateReviewTool" in source

    for name in [
        "mado_check_mission",
        "mado_advance_mission",
        "mado_answer_human_gate",
        "mado_show_evidence",
        "mado_show_qa_result",
    ]:
        assert name in source

    assert "MadoToolCaller" not in source
    assert "mado.opendots.tool-call.v1" not in source


def test_human_gate_shared_contract_supports_freeform_and_safe_default():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "mado-human-gate.ts"
    ).read_text(encoding="utf-8")

    assert "gate_id" in source
    assert "choices:" in source
    assert "safe_default" in source
    assert "allow_choose_for_me" in source
    assert "mado_review_human_gate" in source
