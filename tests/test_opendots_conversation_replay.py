from pathlib import Path

from mado_cockpit.opendots_conversation_replay import (
    OpenDotsConversationReplay,
)


ROOT = Path(__file__).resolve().parents[1]


def test_replay_script_requires_two_agent_runs():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "replay"
        / "scripts"
        / "mado-conversation-replay.ts"
    ).read_text(encoding="utf-8")

    assert "mcc-m1.7-run-1" in source
    assert "mcc-m1.7-run-2" in source
    assert "mado_check_mission" in source
    assert "madoHumanGateReviewTool.name" in source
    assert "mado_answer_human_gate" in source
    assert "human-review-result" in source
    assert "stay_free" in source


def test_replay_fails_closed_on_unexpected_network():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "replay"
        / "scripts"
        / "mado-conversation-replay.ts"
    ).read_text(encoding="utf-8")

    assert "Unexpected network request in deterministic replay" in source
    assert "chat/completions" in source
    assert "network_policy: 'model_fixture_only'" in source


def test_replay_uses_real_dot_agent_and_real_mado_tools():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "replay"
        / "scripts"
        / "mado-conversation-replay.ts"
    ).read_text(encoding="utf-8")

    assert "new DotAgent(" in source
    assert "new Store(':memory:')" in source
    assert "new WorkspaceStore(':memory:'" in source
    assert "madoHumanGateReviewTool" in source
    assert "mado-cockpit-caller" not in source


def test_harness_overlay_target_is_bounded():
    source = (
        ROOT
        / "src"
        / "mado_cockpit"
        / "opendots_conversation_replay.py"
    ).read_text(encoding="utf-8")

    assert 'REPLAY_TARGET = "scripts/mado-conversation-replay.ts"' in source
    assert "self.base.apply()" in source
    assert "awaiting_builder" in source
    assert "human_gate" in source
