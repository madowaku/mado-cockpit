import json
from pathlib import Path

import pytest

from mado_cockpit.governance_intake import (
    compile_diff,
    load_intake,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    ROOT
    / "fixtures"
    / "openbot"
    / "mcc-m2.1-governance-intake.json"
)


def test_intake_pins_openbot_v010_sources():
    intake = load_intake(FIXTURE)

    assert (
        intake["upstream"]["repository"]
        == "CopilotKit/OpenBot"
    )
    assert (
        intake["upstream"]["commit"]
        == "cb5dc32a44517622c6db4e527e61d3abb389b43c"
    )
    assert (
        intake["upstream"]["release"]
        == "v0.1.0"
    )
    assert len(
        intake["upstream"]["files"]
    ) == 6


def test_diff_identifies_m22_p0_governance_gap_set():
    report = compile_diff(
        load_intake(FIXTURE)
    )

    assert (
        report["next_scope"]["milestone"]
        == "MCC-M2.2 Action Policy Gateway"
    )
    assert set(
        report["next_scope"]["p0_gap_ids"]
    ) == {
        "execution_time_default_deny",
        "deny_precedes_allow",
        "broken_policy_fails_closed",
        "audit_before_act",
        "unknown_mcp_effect_is_write",
        "approval_is_not_execution_authority",
    }
    assert (
        report["summary"][
            "p0_open_gap_count"
        ]
        == 6
    )


def test_intake_preserves_mado_as_source_of_truth():
    intake = load_intake(FIXTURE)
    rules = intake["adoption_rules"]

    assert rules["copy_code"] is False
    assert (
        rules[
            "depend_on_openbot_packages"
        ]
        is False
    )
    assert (
        rules[
            "preserve_mado_source_of_truth"
        ]
        is True
    )
    assert (
        rules[
            "adopt_protocol_patterns_only"
        ]
        is True
    )


def test_diff_keeps_takeover_and_equivalence_out_of_m22():
    report = compile_diff(
        load_intake(FIXTURE)
    )
    deferred = set(
        report["next_scope"][
            "explicitly_deferred"
        ]
    )

    assert (
        "human_control_fences_automation"
        in deferred
    )
    assert (
        "equivalent_action_decline_fencing"
        in deferred
    )
    assert (
        "actor_and_initiator_are_distinct"
        in deferred
    )


def test_loader_rejects_unpinned_evidence(tmp_path):
    payload = json.loads(
        FIXTURE.read_text(
            encoding="utf-8"
        )
    )
    payload["principles"][0][
        "source_files"
    ].append(
        "server/src/unpinned.ts"
    )
    path = tmp_path / "intake.json"
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError,
        match="Unpinned source files",
    ):
        load_intake(path)
