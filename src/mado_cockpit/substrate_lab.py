"""MCC-M2.7-AS: offline, fail-closed agent substrate contract laboratory.

This module NEVER executes provider code, network requests, or sandbox workloads.
Its replay gate proves envelope compatibility before any live adapter is considered.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Protocol

from .action_gateway import (
    ActionCandidate,
    ActionInitiator,
    ActionPolicy,
    ActionPolicyGateway,
    ActionPolicyRefused,
    ActionRule,
)
from .control_lease import ControlScope
from .store import CockpitStore

FIXTURE_SCHEMA = "mado.agent-substrate.fixture.v1"
REPORT_SCHEMA = "mado.agent-substrate.report.v1"
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
STAGES = ("mission.started", "outcome.recorded", "evaluation.completed")
PROVIDER_SLOTS = ("pydanticai", "graphiti", "e2b", "langfuse", "deepeval")


class SubstrateLabError(ValueError):
    """An invalid fixture cannot be promoted or partially evaluated."""


def _required_string(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SubstrateLabError(f"{key} must be a nonempty string")
    return value


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise SubstrateLabError(f"{name} must be an object with string keys")
    return value


def _items(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise SubstrateLabError(f"{name} must be an array")
    return value


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str):
        raise SubstrateLabError(f"{name} must be an ISO 8601 timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SubstrateLabError(f"{name} must be an ISO 8601 timestamp") from exc
    if result.tzinfo is None:
        raise SubstrateLabError(f"{name} must include a time zone")
    return result.astimezone(timezone.utc)


def _digest(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                   allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_fixture(data: Any) -> dict[str, Any]:
    fixture = _mapping(data, "fixture")
    if fixture.get("schema") != FIXTURE_SCHEMA:
        raise SubstrateLabError("unsupported fixture schema")
    mission = _mapping(fixture.get("mission"), "mission")
    _required_string(mission, "id")
    _required_string(mission, "objective")
    kinds = _items(mission.get("required_evidence"), "mission.required_evidence")
    if not kinds or any(not isinstance(x, str) or not x.strip() for x in kinds):
        raise SubstrateLabError("required_evidence must contain evidence kinds")
    if len(set(kinds)) != len(kinds):
        raise SubstrateLabError("required_evidence kinds must be unique")
    _timestamp(fixture.get("as_of"), "as_of")
    runs = _items(fixture.get("runs"), "runs")
    if len(runs) != 2:
        raise SubstrateLabError("exactly two runs are required")
    labels: list[str] = []
    for index, raw in enumerate(runs):
        run = _mapping(raw, f"runs[{index}]")
        label = _required_string(run, "runtime")
        labels.append(label)
        if run.get("adapter") != "replay":
            raise SubstrateLabError("only explicit replay adapters are accepted")
        output = _mapping(run.get("outcome"), "outcome")
        if output.get("status") not in ("completed", "blocked", "failed"):
            raise SubstrateLabError("unsupported outcome status")
        # An envelope's actual value must be valid JSON and nonempty.
        _mapping(output.get("result"), "outcome.result")
        evidence = _items(output.get("evidence"), "outcome.evidence")
        seen: set[str] = set()
        for raw_item in evidence:
            item = _mapping(raw_item, "evidence item")
            kind = _required_string(item, "kind")
            _required_string(item, "source")
            if not SHA256_RE.fullmatch(_required_string(item, "sha256")):
                raise SubstrateLabError("evidence requires a SHA-256 hex digest")
            if kind in seen:
                raise SubstrateLabError("duplicate evidence kind")
            seen.add(kind)
        _items(run.get("memory"), "memory")
        for memory_item in run["memory"]:
            fact = _mapping(memory_item, "memory item")
            for k in ("key", "value", "source"):
                _required_string(fact, k)
            start = _timestamp(fact.get("valid_from"), "valid_from")
            end = fact.get("valid_to")
            if end is not None and _timestamp(end, "valid_to") <= start:
                raise SubstrateLabError("valid_to must follow valid_from")
        trace = _items(run.get("trace"), "trace")
        for item in trace:
            event = _mapping(item, "trace item")
            _required_string(event, "event")
            _required_string(event, "source")
        _items(run.get("tool_calls"), "tool_calls")
        for item in run["tool_calls"]:
            call = _mapping(item, "tool call")
            _required_string(call, "action")
            _required_string(call, "target_kind")
            _mapping(call.get("target"), "tool target")
            # Unknown effect is treated as write in the replay admission gate.
        execution = _mapping(run.get("execution"), "execution")
        if not isinstance(execution.get("sandbox"), str):
            raise SubstrateLabError("execution.sandbox must be a string")
        if type(execution.get("network")) is not bool:
            raise SubstrateLabError("execution.network must be boolean")
        if type(execution.get("code_execution")) is not bool:
            raise SubstrateLabError("execution.code_execution must be boolean")
        cost = execution.get("cost_usd")
        if type(cost) not in (float, int) or cost < 0:
            raise SubstrateLabError("execution.cost_usd must be nonnegative")
    if labels[0] == labels[1]:
        raise SubstrateLabError("baseline and candidate runtime labels must differ")
    return fixture


class ReplayAdapter(Protocol):
    """Adapter contract; future live adapters are deliberately not registered."""

    def run(self, mission: Mapping[str, Any]) -> Mapping[str, Any]:
        ...


class FixtureReplayAdapter:
    def __init__(self, snapshot: Mapping[str, Any]) -> None:
        self.snapshot = snapshot

    def run(self, mission: Mapping[str, Any]) -> Mapping[str, Any]:
        # No arbitrary code or input-supplied commands are evaluated here.
        return self.snapshot


def _active_memory(run: Mapping[str, Any], at: datetime) -> tuple[dict[str, str], list[str]]:
    current: dict[str, str] = {}
    errors: list[str] = []
    for entry in run["memory"]:
        start = _timestamp(entry["valid_from"], "valid_from")
        end = entry.get("valid_to")
        if start <= at and (end is None or at < _timestamp(end, "valid_to")):
            key, value = entry["key"], entry["value"]
            if key in current and current[key] != value:
                errors.append(key)
            current[key] = value
    return current, sorted(set(errors))


def _outcome_fingerprint(outcome: Mapping[str, Any]) -> str:
    # Source paths can legitimately differ; content IDs and status must not.
    return _digest({
        "status": outcome["status"],
        "result": outcome["result"],
        "evidence": sorted(
            (item["kind"], item["sha256"]) for item in outcome["evidence"]
        ),
    })


def _replay_policy() -> ActionPolicy:
    return ActionPolicy(allow=(
        ActionRule(
            id="allow:fixture-lookup-only",
            predicate=lambda candidate: (
                candidate.effect == "read"
                and candidate.action == "fixture.lookup"
                and candidate.target_kind == "fixture"
            ),
            reason="Read-only fixture lookup in isolated replay.",
        ),
    ))


def _admit_calls(run: Mapping[str, Any], mission_id: str,
                 gateway: ActionPolicyGateway) -> list[str]:
    refused: list[str] = []
    for index, call in enumerate(run["tool_calls"]):
        candidate = ActionCandidate(
            action=call["action"],
            effect="read" if call.get("effect") == "read" else "write",
            target_kind=call["target_kind"],
            target=call["target"],
            arguments={"fixture_call_index": index},
            actor="substrate-lab",
            initiator=ActionInitiator(
                kind="replay", source="substrate-lab",
                context_id=f"{mission_id}:{run['runtime']}",
            ),
            control_scope=ControlScope(kind="mission", resource_id=mission_id),
            capability="substrate.fixture",
            mission_id=mission_id,
        )
        try:
            gateway.execute(
                candidate,
                policy=_replay_policy(),
                dispatch=lambda _candidate: None,  # explicitly a no-op
                approved_digest=candidate.digest,
            )
        except ActionPolicyRefused:
            refused.append(f"tool_call[{index}]:policy_refused")
    return refused


def run_compatibility_fixture(fixture: Mapping[str, Any], *,
                              root: Path | str = ".") -> dict[str, Any]:
    """Evaluate two read-only fixture snapshots with existing policy + lease gates.

    PASS proves replay contract parity, not actual OSS integration readiness.
    """
    data = _validate_fixture(fixture)
    mission = data["mission"]
    at = _timestamp(data["as_of"], "as_of")
    gateway = ActionPolicyGateway(CockpitStore(root))
    checks: list[dict[str, Any]] = []

    def check(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    views: list[dict[str, Any]] = []
    for raw in data["runs"]:
        run = FixtureReplayAdapter(raw).run(mission)
        label = run["runtime"]
        result = run["outcome"]
        execution = run["execution"]
        sandbox_safe = (
            execution["sandbox"] == "fixture-only"
            and execution["network"] is False
            and execution["code_execution"] is False
            and execution["cost_usd"] == 0
        )
        check(f"{label}:sandbox", sandbox_safe,
              "fixture_only_no_network_no_execution_zero_cost" if sandbox_safe
              else "unsafe_or_billable_execution_claim")
        missing = sorted(set(mission["required_evidence"]) -
                         {item["kind"] for item in result["evidence"]})
        check(f"{label}:evidence", not missing,
              "complete" if not missing else "missing:" + ",".join(missing))
        stages = {item["event"] for item in run["trace"]}
        missing_stages = sorted(set(STAGES) - stages)
        check(f"{label}:trace", not missing_stages,
              "complete" if not missing_stages else "missing:" + ",".join(missing_stages))
        active, conflicts = _active_memory(run, at)
        check(f"{label}:memory", not conflicts,
              "consistent" if not conflicts else "conflicting:" + ",".join(conflicts))
        refused = _admit_calls(run, mission["id"], gateway)
        check(f"{label}:policy", not refused,
              "all_simulated_calls_admitted" if not refused else
              "blocked:" + ",".join(refused))
        views.append({"runtime": label, "outcome_digest": _outcome_fingerprint(result),
                      "status": result["status"], "active_memory_digest": _digest(active),
                      "tool_call_count": len(run["tool_calls"]),
                      "refused_count": len(refused)})
    check("outcome_parity", views[0]["outcome_digest"] == views[1]["outcome_digest"],
          "same" if views[0]["outcome_digest"] == views[1]["outcome_digest"]
          else "diverged")
    check("memory_parity",
          views[0]["active_memory_digest"] == views[1]["active_memory_digest"],
          "same" if views[0]["active_memory_digest"] == views[1]["active_memory_digest"]
          else "diverged")
    check("completed", all(view["status"] == "completed" for view in views),
          "both_completed" if all(view["status"] == "completed" for view in views)
          else "incomplete")
    return {
        "schema": REPORT_SCHEMA,
        "fixture_digest": _digest(data),
        "mission_id": mission["id"],
        "status": "pass" if all(item["passed"] for item in checks) else "hold",
        "scope": "offline_contract_replay_only",
        "runs": views,
        "checks": checks,
        "external_adapters": {
            slot: "not_integrated" for slot in PROVIDER_SLOTS
        },
        "production_promotion_allowed": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Offline agent substrate parity gate")
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--root", type=Path, default=Path("."),
                        help="Cockpit root for policy decision receipts")
    parser.add_argument("--out", type=Path,
                        help="Optional JSON report destination")
    args = parser.parse_args(argv)
    try:
        fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
        report = run_compatibility_fixture(fixture, root=args.root)
    except (OSError, ValueError, TypeError) as exc:
        parser.exit(1, f"invalid substrate fixture: {exc}\n")
    encoded = json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
