from pathlib import Path

from mado_cockpit.opendots_browser_chat import (
    OpenDotsBrowserChatHarness,
)


ROOT = Path(__file__).resolve().parents[1]


def test_m19_shim_has_three_stage_tool_flow():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "chat-shim"
        / "src"
        / "server"
        / "mado-deterministic-chat-shim.ts"
    ).read_text(encoding="utf-8")

    assert "mado_check_mission" in source
    assert "mado_review_human_gate" in source
    assert "mado_answer_human_gate" in source
    assert "m1.9-mission-check" in source
    assert "m1.9-human-review" in source
    assert "m1.9-gate-answer" in source
    assert "stay_free" in source


def test_m19_browser_uses_normal_chat_composer():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "chat-shim"
        / "scripts"
        / "mado-browser-chat-e2e.ts"
    ).read_text(encoding="utf-8")

    assert "Start a conversation" in source
    assert "Start conversation" in source
    assert "Human decision required" in source
    assert "stay_free" in source
    assert "Mission resumed on the free path" in source


def test_m19_platform_patch_is_e2e_guarded():
    source = (
        ROOT
        / "src"
        / "mado_cockpit"
        / "opendots_browser_chat.py"
    ).read_text(encoding="utf-8")

    assert "MADO_DETERMINISTIC_CHAT === '1'" in source
    assert "new CopilotRuntime({" in source
    assert "this.workspace.bindThread" in source
    assert "madoDeterministicChatShimRoutes" in source


def test_m19_lock_pins_platform_and_app():
    import json

    lock = json.loads(
        (
            ROOT
            / "fixtures"
            / "opendots"
            / "mcc-m1.9-upstream-lock.json"
        ).read_text(encoding="utf-8")
    )

    assert lock["version"] == "MCC-M1.9"
    assert (
        lock["upstream"]["locked_files"][
            "src/server/platform.ts"
        ]
        == "7d19ad474ba87e6500228980b99476590acaec16"
    )
    assert (
        lock["upstream"]["locked_files"][
            "src/server/app.ts"
        ]
        == "fc9bae5454b509ce325a2e76a9ea1308e7347cdd"
    )


def test_m19_dot_agent_readiness_is_env_guarded():
    source = (
        ROOT
        / "src"
        / "mado_cockpit"
        / "opendots_browser_chat.py"
    ).read_text(encoding="utf-8")

    assert "MADO_COCKPIT_M1_9_DOT_READY" in source
    assert "MADO_DETERMINISTIC_CHAT !== '1'" in source
    assert "!this.config.apiKey" in source
    assert "!this.config.model" in source
