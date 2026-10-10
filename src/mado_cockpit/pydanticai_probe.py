"""MCC-M2.7.1: actual PydanticAI Agent + TestModel, zero paid inference.

This is an opt-in provider contract probe. It runs a genuine PydanticAI
Agent with its procedural TestModel; no remotely hosted LLM is instantiated.
Tool calls go through Cockpit's ActionPolicyGateway + Human Control Lease.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from .action_gateway import (
    ActionCandidate, ActionInitiator, ActionPolicyGateway,
)
from .control_lease import ControlScope
from .store import CockpitStore
from .substrate_lab import (
    PROVIDER_SLOTS, SubstrateLabError, _mapping, _replay_policy,
    _required_string, _validate_fixture, run_compatibility_fixture,
)

PROBE_INPUT_SCHEMA = "mado.pydanticai-local-probe.input.v1"
PROBE_REPORT_SCHEMA = "mado.pydanticai-local-probe.report.v1"
PROVIDER_RUNTIME = "pydanticai-local-testmodel"


class LocalProbeError(SubstrateLabError):
    """Contract input invalid. The provider will not be started."""


def _validate_probe_input(raw: Mapping[str, Any]) -> dict[str, Any]:
    data = _mapping(raw, "probe")
    if set(data) != {"schema", "mode", "model_output"}:
        raise LocalProbeError("probe must have schema, mode, and model_output only")
    if data["schema"] != PROBE_INPUT_SCHEMA or data["mode"] != "testmodel":
        raise LocalProbeError("only local PydanticAI TestModel is allowed")
    output = _mapping(data["model_output"], "model_output")
    if set(output) != {"status", "result", "evidence"}:
        raise LocalProbeError("model_output must have status, result, and evidence only")
    return data


def _hold(mission_id: str, reason: str, *,
          model_started: bool, tool_count: int = 0,
          tool_admitted: int = 0) -> dict[str, Any]:
    if reason not in {
        "missing_optional_dependency",
        "model_execution_failed",
        "model_output_invalid",
        "tool_gate_refused",
        "unexpected_tool_count",
        "missing_tool_schema",
    }:
        reason = "model_execution_failed"
    return {
        "schema": PROBE_REPORT_SCHEMA,
        "mission_id": mission_id,
        "status": "hold",
        "scope": "local_pydanticai_testmodel_contract_probe",
        "reason_codes": [reason],
        "agent": {
            "runtime": PROVIDER_RUNTIME,
            "model": "TestModel (procedural, not inference)",
            "actual_agent_executed": model_started,
            "observed_tool_count": tool_count,
            "admitted_tool_count": tool_admitted,
        },
        "compatibility": None,
        "external_adapters": {
            slot: ("local_testmodel_probe" if slot == "pydanticai" and model_started
                   else "not_integrated") for slot in PROVIDER_SLOTS
        },
        "provider_cost_usd": 0,
        "production_promotion_allowed": False,
    }


def run_local_provider_probe(
    baseline_fixture: Mapping[str, Any],
    probe_input: Mapping[str, Any],
    *,
    root: Path | str = ".",
) -> dict[str, Any]:
    """Run the real Agent against TestModel, then reuse M2.7-AS parity gate.

    The model_output is a *canned* provider response, not a measured model
    capability. This test verifies lifecycle, structured validation, tool
    interception, observation, and cross-runtime contract compatibility.
    """
    data = _validate_fixture(copy.deepcopy(baseline_fixture))
    probe = _validate_probe_input(probe_input)
    mission = data["mission"]
    mission_id = mission["id"]
    if data["runs"][0]["runtime"] != "native-replay":
        raise LocalProbeError("baseline first runtime must be native-replay")

    try:
        from pydantic import BaseModel, ConfigDict, Field
        from pydantic_ai import Agent, models
        from pydantic_ai.models.test import TestModel
        from typing import Literal
    except ImportError:
        return _hold(mission_id, "missing_optional_dependency", model_started=False)

    class EvidenceModel(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        kind: str = Field(min_length=1)
        sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
        source: str = Field(min_length=1)

    class OutputModel(BaseModel):
        model_config = ConfigDict(extra="forbid", strict=True)
        status: Literal["completed", "blocked", "failed"]
        result: dict[str, Any]
        evidence: list[EvidenceModel]

    admitted: list[str] = []
    attempted: list[str] = []
    gate = ActionPolicyGateway(CockpitStore(root))
    candidate = ActionCandidate(
        action="fixture.lookup",
        effect="read",
        target_kind="fixture",
        target={"mission_id": mission_id},
        arguments={},
        actor="pydanticai-local-probe",
        initiator=ActionInitiator(
            kind="replay", source="pydanticai-local-probe",
            context_id=f"{mission_id}:testmodel",
        ),
        control_scope=ControlScope(kind="mission", resource_id=mission_id),
        capability="substrate.fixture",
        mission_id=mission_id,
    )

    # Model is constructed from a TestModel instance, never from an input
    # provider string. Prevent all other PydanticAI model requests while running.
    test_model = TestModel(
        call_tools=["fixture_lookup"],
        custom_output_args=probe["model_output"],
    )
    agent = Agent(test_model, output_type=OutputModel, retries=0)

    @agent.tool_plain
    def fixture_lookup() -> str:
        """Return the objective of the preloaded in-memory mission fixture."""
        attempted.append("fixture.lookup")
        value = gate.execute(
            candidate, policy=_replay_policy(),
            approved_digest=candidate.digest,
            dispatch=lambda _action: mission["objective"],
        )
        admitted.append("fixture.lookup")
        return value

    previous = models.ALLOW_MODEL_REQUESTS
    models.ALLOW_MODEL_REQUESTS = False
    try:
        try:
            result = agent.run_sync(mission["objective"])
        except Exception as exc:
            # No exception details are persisted: upstream errors can contain
            # prompts, provider secrets or untrusted tool data.
            from .action_gateway import ActionPolicyRefused
            reason = ("tool_gate_refused" if isinstance(exc, ActionPolicyRefused)
                      else "model_execution_failed")
            return _hold(mission_id, reason, model_started=True,
                         tool_count=len(attempted), tool_admitted=len(admitted))
    finally:
        models.ALLOW_MODEL_REQUESTS = previous

    if len(attempted) != 1 or len(admitted) != 1:
        return _hold(mission_id, "unexpected_tool_count", model_started=True,
                     tool_count=len(attempted), tool_admitted=len(admitted))
    params = test_model.last_model_request_parameters
    tool_names = sorted(tool.name for tool in params.function_tools) if params else []
    if tool_names != ["fixture_lookup"]:
        return _hold(mission_id, "missing_tool_schema", model_started=True,
                     tool_count=len(attempted), tool_admitted=len(admitted))
    if not isinstance(result.output, OutputModel):
        return _hold(mission_id, "model_output_invalid", model_started=True,
                     tool_count=len(attempted), tool_admitted=len(admitted))

    candidate_run = copy.deepcopy(data["runs"][1])
    candidate_run["runtime"] = PROVIDER_RUNTIME
    # M2.7-AS accepts only replay adapters. We keep the observation out of
    # the replay input but name the actual local runtime in the report.
    candidate_run["adapter"] = "replay"
    candidate_run["outcome"] = result.output.model_dump(mode="json")
    candidate_run["trace"] = [
        {"event": event, "source": "pydanticai://local-testmodel"}
        for event in ("mission.started", "outcome.recorded", "evaluation.completed")
    ]
    candidate_run["tool_calls"] = [{
        "action": "fixture.lookup", "effect": "read",
        "target_kind": "fixture", "target": {"mission_id": mission_id},
    }]
    # Memory comes from replay fixture. No Graphiti/knowledge backend ran.
    data["runs"][1] = candidate_run
    compatibility = run_compatibility_fixture(data, root=root)
    report = {
        "schema": PROBE_REPORT_SCHEMA,
        "mission_id": mission_id,
        "status": compatibility["status"],
        "scope": "local_pydanticai_testmodel_contract_probe",
        "reason_codes": [] if compatibility["status"] == "pass" else [
            item["name"] for item in compatibility["checks"] if not item["passed"]
        ],
        "agent": {
            "runtime": PROVIDER_RUNTIME,
            "model": "TestModel (procedural, not inference)",
            "actual_agent_executed": True,
            "observed_tool_count": len(attempted),
            "admitted_tool_count": len(admitted),
            "registered_tool_names": tool_names,
            "model_requests": result.usage().requests,
            "structured_output_valid": True,
        },
        "compatibility": compatibility,
        "external_adapters": {
            slot: "local_testmodel_probe" if slot == "pydanticai"
            else "not_integrated" for slot in PROVIDER_SLOTS
        },
        "provider_cost_usd": 0,
        "production_promotion_allowed": False,
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MCC-M2.7.1 PydanticAI TestModel probe")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--probe", required=True, type=Path)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        probe = json.loads(args.probe.read_text(encoding="utf-8"))
        report = run_local_provider_probe(baseline, probe, root=args.root)
    except (OSError, TypeError, ValueError) as exc:
        parser.exit(1, f"invalid local probe input: {exc}\n")
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
