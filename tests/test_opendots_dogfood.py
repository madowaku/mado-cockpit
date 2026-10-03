import json
from pathlib import Path

import pytest

from mado_cockpit.opendots_dogfood import (
    OpenDotsDogfoodError,
    OpenDotsDogfoodHarness,
)


ROOT = Path(__file__).resolve().parents[1]


DOT_AGENT = """import { pageReviewTool } from '../shared/page-review.js';
const serverTools = [
          ...tools,
          ...pageTools(pages),
          ...(computer.configured
            ? computerTools(computer, dot.id, check, controller.signal)
            : []),
        ];
const prompt = `When the user requests review before saving, use review_space_page if available and wait for its result.`;
this.inner.run({
            ...input,
            tools:
              !this.channel &&
              input.tools.some((tool) => tool.name === pageReviewTool.name)
                ? [pageReviewTool]
                : [],
            forwardedProps: {},
});
"""

CHAT = """import { CallView } from './CallView';
export function Chat() {
  const voice = useVoice(thread.id, onSaved, agent.messages.at(-1)?.id);
  const visible = agent.messages.filter(
    (message) =>
      message.toolCalls?.some(
        (call) =>
              call.function.name.startsWith('computer_') ||
              call.function.name === pageReviewTool.name,
      ),
  );
  return <div />;
}
"""

MAIN = """import './style.css';
import './editor.css';
"""


def _blob_sha(payload: str) -> str:
    import hashlib

    raw = payload.encode("utf-8")
    return hashlib.sha1(
        f"blob {len(raw)}\0".encode("utf-8")
        + raw
    ).hexdigest()


def _checkout(tmp_path):
    root = tmp_path / "OpenDots"
    (root / "src/server").mkdir(parents=True)
    (root / "src/client").mkdir(parents=True)
    (root / "src/shared").mkdir(parents=True)
    package = {
        "name": "opendots",
        "version": "0.1.0",
        "engines": {"node": ">=24.0.0"},
    }
    (root / "package.json").write_text(
        json.dumps(package) + "\n",
        encoding="utf-8",
    )
    (root / "src/server/dot-agent.ts").write_text(
        DOT_AGENT,
        encoding="utf-8",
    )
    (root / "src/client/Chat.tsx").write_text(
        CHAT,
        encoding="utf-8",
    )
    (root / "src/client/main.tsx").write_text(
        MAIN,
        encoding="utf-8",
    )
    return root


def _harness(tmp_path):
    checkout = _checkout(tmp_path)
    harness = OpenDotsDogfoodHarness(
        ROOT,
        checkout,
        allow_drift=True,
    )
    return harness, checkout


def test_apply_materializes_overlay_and_patches_once(tmp_path):
    harness, checkout = _harness(tmp_path)

    first = harness.apply()
    second = harness.apply()

    assert first["changed"]
    assert second["changed"] == []

    for target in [
        "src/server/mado-cockpit-tools.ts",
        "src/server/mado-cockpit-caller.ts",
        "src/shared/mado-human-gate.ts",
        "src/client/mado-cockpit-renderers.tsx",
        "src/client/mado-cockpit-renderers.css",
    ]:
        assert (checkout / target).is_file()

    dot_agent = (
        checkout / "src/server/dot-agent.ts"
    ).read_text(encoding="utf-8")
    assert "MADO_COCKPIT_M1_5_IMPORTS" in dot_agent
    assert "madoCockpitTools(" in dot_agent
    assert "mado_review_human_gate" in dot_agent
    assert "madoHumanGateReviewTool.name" in dot_agent

    chat = (
        checkout / "src/client/Chat.tsx"
    ).read_text(encoding="utf-8")
    assert "useMadoCockpitRenderers" in chat
    assert "startsWith('mado_')" in chat

    main = (
        checkout / "src/client/main.tsx"
    ).read_text(encoding="utf-8")
    assert "mado-cockpit-renderers.css" in main


def test_drift_fails_closed_without_override(tmp_path):
    checkout = _checkout(tmp_path)
    harness = OpenDotsDogfoodHarness(
        ROOT,
        checkout,
        allow_drift=False,
    )

    with pytest.raises(
        OpenDotsDogfoodError,
        match="drift detected",
    ):
        harness.preflight()


def test_patch_anchor_drift_fails_instead_of_guessing(tmp_path):
    harness, checkout = _harness(tmp_path)
    path = checkout / "src/client/Chat.tsx"
    path.write_text(
        "export function Chat(){ return null; }\n",
        encoding="utf-8",
    )

    with pytest.raises(
        OpenDotsDogfoodError,
        match="anchor expected once",
    ):
        harness.apply()


def test_overlay_caller_is_local_process_only():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "overlay"
        / "src"
        / "server"
        / "mado-cockpit-caller.ts"
    ).read_text(encoding="utf-8")

    assert "spawn(" in source
    assert "shell: false" in source
    assert "MADO_COCKPIT_ROOT" in source
    assert "PYTHONPATH" in source
    assert "http://" not in source
    assert "https://" not in source
    assert "Authorization" not in source


def test_lock_fixture_pins_real_upstream_files():
    lock = json.loads(
        (
            ROOT
            / "fixtures"
            / "opendots"
            / "mcc-m1.5-upstream-lock.json"
        ).read_text(encoding="utf-8")
    )

    assert lock["harness_version"] == "MCC-M1.5"
    assert (
        lock["upstream"]["repository"]
        == "CopilotKit/OpenDots"
    )
    assert lock["upstream"]["locked_files"] == {
        "package.json": (
            "3020c50b19e0325c6a85422eacf83b223259e641"
        ),
        "src/server/dot-agent.ts": (
            "9da6ce6d5c9c841f64ea98fab80b7f5633fa9e31"
        ),
        "src/client/Chat.tsx": (
            "4797aaf369afed1b774fcefa04a14892801be694"
        ),
        "src/client/main.tsx": (
            "f384a752f12740ad11fc5142780fbf30da83c3ef"
        ),
    }


def test_caller_output_limit_and_timeout_are_bounded():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "overlay"
        / "src"
        / "server"
        / "mado-cockpit-caller.ts"
    ).read_text(encoding="utf-8")

    assert "MAX_OUTPUT_BYTES" in source
    assert "DEFAULT_TIMEOUT_MS" in source
    assert "child.kill()" in source
