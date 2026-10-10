"""Actual PydanticAI local Agent contract probe (optional extra)."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

pytest.importorskip("pydantic_ai")
from mado_cockpit.control_lease import ControlLeaseManager, ControlScope
from mado_cockpit.pydanticai_probe import (
    LocalProbeError, PROBE_REPORT_SCHEMA, main, run_local_provider_probe,
)
from mado_cockpit.store import CockpitStore

ROOT = Path(__file__).resolve().parents[1]
BASELINE = (ROOT / "fixtures/substrate/mcc-m2.7-agent-substrate-parity.json")
PROBE = (ROOT / "fixtures/substrate/mcc-m2.7.1-pydanticai-testmodel.json")


@pytest.fixture
def inputs():
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    probe = json.loads(PROBE.read_text(encoding="utf-8"))
    return baseline, probe


def failures(report):
    return {item["name"] for item in report["compatibility"]["checks"]
            if not item["passed"]}


def test_real_agent_pydantic_schema_tool_policy_and_parity(inputs, tmp_path):
    baseline, probe = inputs
    report = run_local_provider_probe(baseline, probe, root=tmp_path)
    assert report["schema"] == PROBE_REPORT_SCHEMA
    assert report["status"] == "pass"
    assert report["scope"] == "local_pydanticai_testmodel_contract_probe"
    assert report["agent"]["actual_agent_executed"] is True
    assert report["agent"]["registered_tool_names"] == ["fixture_lookup"]
    assert report["agent"]["observed_tool_count"] == 1
    assert report["agent"]["admitted_tool_count"] == 1
    assert report["agent"]["structured_output_valid"]
    assert report["agent"]["model_requests"] >= 1
    assert report["compatibility"]["status"] == "pass"
    assert report["external_adapters"]["pydanticai"] == "local_testmodel_probe"
    assert report["external_adapters"]["graphiti"] == "not_integrated"
    assert report["provider_cost_usd"] == 0
    assert report["production_promotion_allowed"] is False
    receipts = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (tmp_path / ".mado/cockpit/action_decisions").glob("*.json")
    ]
    # One actual tool call + two parity replay admissions.
    assert len(receipts) == 3
    assert all(r["decision"]["allowed"] is True for r in receipts)


def test_structured_output_difference_blocks_promotion(inputs, tmp_path):
    baseline, probe = inputs
    probe["model_output"]["result"]["items_accepted"] = 99
    report = run_local_provider_probe(baseline, probe, root=tmp_path)
    assert report["status"] == "hold"
    assert "outcome_parity" in failures(report)
    assert report["agent"]["actual_agent_executed"]


def test_content_hash_difference_blocks_promotion(inputs, tmp_path):
    baseline, probe = inputs
    probe["model_output"]["evidence"][0]["sha256"] = "c" * 64
    report = run_local_provider_probe(baseline, probe, root=tmp_path)
    assert report["status"] == "hold"
    assert "outcome_parity" in failures(report)


@pytest.mark.parametrize("edit", [
    lambda p: p["model_output"].update(status="uncertain"),
    lambda p: p["model_output"]["evidence"][0].update(sha256="bad"),
    lambda p: p["model_output"]["evidence"][0].update(secret="LEAK-ME"),
    lambda p: p["model_output"].update(unexpected="LEAK-ME"),
])
def test_invalid_generated_payload_fails_closed_without_leaking(
    inputs, tmp_path, edit,
):
    baseline, probe = inputs
    edit(probe)
    report = run_local_provider_probe(baseline, probe, root=tmp_path)
    assert report["status"] == "hold"
    assert report["production_promotion_allowed"] is False
    assert "LEAK-ME" not in json.dumps(report)
    assert report["agent"]["actual_agent_executed"]


def test_human_control_lease_fences_real_pydanticai_tool(inputs, tmp_path):
    baseline, probe = inputs
    mission_id = baseline["mission"]["id"]
    ControlLeaseManager(CockpitStore(tmp_path)).acquire(
        ControlScope(kind="mission", resource_id=mission_id),
        holder="human", ttl_seconds=300,
    )
    report = run_local_provider_probe(baseline, probe, root=tmp_path)
    assert report["status"] == "hold"
    assert report["agent"]["observed_tool_count"] >= 1
    assert report["agent"]["admitted_tool_count"] == 0
    receipts = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in (tmp_path / ".mado/cockpit/action_decisions").glob("*.json")
    ]
    assert receipts
    assert receipts[0]["decision"]["source"] == "human_control_fenced"
    assert report["production_promotion_allowed"] is False


@pytest.mark.parametrize("edit", [
    lambda p: p.update(mode="openai"),
    lambda p: p.update(schema="unknown"),
    lambda p: p.update(api_key="SHOULD_NOT_BE_USED"),
    lambda p: p.pop("model_output"),
])
def test_unapproved_provider_cannot_start(inputs, tmp_path, edit):
    baseline, probe = inputs
    edit(probe)
    with pytest.raises(LocalProbeError):
        run_local_provider_probe(baseline, probe, root=tmp_path)
    assert not list((tmp_path / ".mado/cockpit/action_decisions").glob("*.json"))


def test_bad_baseline_rejected_before_agent_creation(inputs, tmp_path):
    baseline, probe = inputs
    baseline["runs"].pop()
    with pytest.raises(ValueError):
        run_local_provider_probe(baseline, probe, root=tmp_path)


def test_cli_pass_then_hold_and_exit_codes(inputs, tmp_path, capsys):
    baseline, probe = inputs
    basefile, probefile = tmp_path / "base.json", tmp_path / "probe.json"
    output = tmp_path / "report.json"
    basefile.write_text(json.dumps(baseline), encoding="utf-8")
    probefile.write_text(json.dumps(probe), encoding="utf-8")
    args = ["--baseline", str(basefile), "--probe", str(probefile),
            "--root", str(tmp_path), "--out", str(output)]
    assert main(args) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "pass"
    probe["model_output"]["result"]["decision"] = "mismatch"
    probefile.write_text(json.dumps(probe), encoding="utf-8")
    assert main(args) == 2
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "hold"
    assert '"status": "hold"' in capsys.readouterr().out
