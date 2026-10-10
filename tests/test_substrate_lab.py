"""MCC-M2.7-AS fixture-only parity, refusal, and safety tests."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mado_cockpit.control_lease import ControlLeaseManager, ControlScope
from mado_cockpit.store import CockpitStore
from mado_cockpit.substrate_lab import (
    FIXTURE_SCHEMA, REPORT_SCHEMA, SubstrateLabError,
    main, run_compatibility_fixture,
)

FIXTURE_PATH = (Path(__file__).resolve().parents[1]
                / "fixtures/substrate/mcc-m2.7-agent-substrate-parity.json")


@pytest.fixture
def sample():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_parity_pass_is_replay_only_and_writes_gateway_receipts(sample, tmp_path):
    result = run_compatibility_fixture(sample, root=tmp_path)
    assert result["schema"] == REPORT_SCHEMA
    assert result["status"] == "pass"
    assert result["production_promotion_allowed"] is False
    assert result["scope"] == "offline_contract_replay_only"
    assert all(value == "not_integrated"
               for value in result["external_adapters"].values())
    receipts = list((tmp_path / ".mado/cockpit/action_decisions").glob("*.json"))
    assert len(receipts) == 2
    for path in receipts:
        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert recorded["decision"]["allowed"] is True
        assert recorded["dispatch_status"] == "dispatched"


def test_report_is_deterministic_despite_receipt_ids(sample, tmp_path):
    first = run_compatibility_fixture(sample, root=tmp_path)
    second = run_compatibility_fixture(sample, root=tmp_path)
    assert first == second


def test_outcome_divergence_holds(sample, tmp_path):
    sample["runs"][1]["outcome"]["result"]["items_accepted"] = 100
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert report["status"] == "hold"
    assert "outcome_parity" in failed(report)


def test_missing_evidence_holds(sample, tmp_path):
    sample["runs"][0]["outcome"]["evidence"].pop()
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "native-replay:evidence" in failed(report)


def test_missing_trace_holds(sample, tmp_path):
    sample["runs"][1]["trace"].pop()
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "candidate-replay:trace" in failed(report)


def test_temporal_conflict_holds(sample, tmp_path):
    sample["runs"][1]["memory"].append({
        "key": "provider_mode", "value": "unexpected",
        "valid_from": "2026-10-09T00:00:00Z",
        "valid_to": None, "source": "fixture://memory/conflict",
    })
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "candidate-replay:memory" in failed(report)



def test_historical_temporal_conflict_holds(sample, tmp_path):
    # Two contradictory values overlap, even though neither is current as_of.
    sample["runs"][0]["memory"].append({
        "key": "provider_mode", "value": "outdated-contradiction",
        "valid_from": "2026-10-03T00:00:00Z",
        "valid_to": "2026-10-07T00:00:00Z",
        "source": "fixture://memory/conflicted-past",
    })
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "native-replay:memory" in failed(report)


def test_memory_parity_holds_on_drift(sample, tmp_path):
    sample["runs"][1]["memory"][1]["value"] = "new-provider"
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "memory_parity" in failed(report)


@pytest.mark.parametrize("effect", ["write", "unknown", None])
def test_write_or_ambiguous_effect_fails_closed(sample, tmp_path, effect):
    sample["runs"][0]["tool_calls"][0]["effect"] = effect
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "native-replay:policy" in failed(report)
    receipts = list((tmp_path / ".mado/cockpit/action_decisions").glob("*.json"))
    assert any(json.loads(p.read_text(encoding="utf-8"))["decision"]["allowed"] is False
               for p in receipts)


def test_tool_allowlist_is_enforced(sample, tmp_path):
    sample["runs"][1]["tool_calls"][0]["action"] = "browser.navigate"
    assert "candidate-replay:policy" in failed(
        run_compatibility_fixture(sample, root=tmp_path)
    )


def test_human_control_lease_fences_replay(sample, tmp_path):
    leases = ControlLeaseManager(CockpitStore(tmp_path))
    leases.acquire(ControlScope(kind="mission", resource_id=sample["mission"]["id"]),
                   holder="human", ttl_seconds=300)
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert report["status"] == "hold"
    assert all(item in failed(report)
               for item in ("native-replay:policy", "candidate-replay:policy"))


@pytest.mark.parametrize("change", [
    {"network": True}, {"code_execution": True},
    {"cost_usd": 0.01}, {"sandbox": "cloud"},
])
def test_unsafe_execution_claim_holds(sample, tmp_path, change):
    sample["runs"][1]["execution"].update(change)
    report = run_compatibility_fixture(sample, root=tmp_path)
    assert "candidate-replay:sandbox" in failed(report)


def test_noncompleted_status_holds(sample, tmp_path):
    for run in sample["runs"]:
        run["outcome"]["status"] = "blocked"
    assert "completed" in failed(run_compatibility_fixture(sample, root=tmp_path))


@pytest.mark.parametrize("edit", [
    lambda f: f.update(schema="unknown"),
    lambda f: f["runs"].pop(),
    lambda f: f["runs"][1].update(adapter="pydanticai-live"),
    lambda f: f["mission"].update(required_evidence=[]),
    lambda f: f["runs"][0]["memory"][1].update(valid_to="2020-01-01T00:00:00Z"),
    lambda f: f["runs"][0]["outcome"]["evidence"].append(
        copy.deepcopy(f["runs"][0]["outcome"]["evidence"][0])),
    lambda f: f.update(as_of="2026-10-10"),
    lambda f: f["runs"][1]["execution"].update(network="no"),
    lambda f: f["runs"][1]["execution"].update(cost_usd=float("nan")),
])
def test_bad_fixture_fails_before_dispatch(sample, tmp_path, edit):
    edit(sample)
    with pytest.raises(SubstrateLabError):
        run_compatibility_fixture(sample, root=tmp_path)
    assert not list((tmp_path / ".mado/cockpit/action_decisions").glob("*.json"))


def test_cli_pass_writes_report(sample, tmp_path, capsys):
    p = tmp_path / "fixture.json"
    out = tmp_path / "report.json"
    p.write_text(json.dumps(sample), encoding="utf-8")
    exit_code = main([str(p), "--root", str(tmp_path), "--out", str(out)])
    assert exit_code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["status"] == "pass"
    assert '"status": "pass"' in capsys.readouterr().out


def test_cli_hold_returns_nonzero(sample, tmp_path, capsys):
    sample["runs"][1]["outcome"]["result"]["decision"] = "changed"
    p = tmp_path / "fixture.json"
    p.write_text(json.dumps(sample), encoding="utf-8")
    assert main([str(p), "--root", str(tmp_path)]) == 2
    assert '"status": "hold"' in capsys.readouterr().out


def failed(result):
    return {item["name"] for item in result["checks"] if not item["passed"]}
