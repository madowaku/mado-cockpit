from pathlib import Path

import pytest

from mado_cockpit.opendots_browser_e2e import (
    OpenDotsBrowserE2E,
)
from mado_cockpit.opendots_dogfood import (
    OpenDotsDogfoodError,
)


ROOT = Path(__file__).resolve().parents[1]


def _checkout(tmp_path):
    root = tmp_path / "OpenDots"
    (root / "src/server").mkdir(parents=True)
    (root / "src/client").mkdir(parents=True)
    (root / "src/shared").mkdir(parents=True)

    (root / "package.json").write_text(
        '{"name":"opendots","version":"0.1.0","engines":{"node":">=24"}}\n',
        encoding="utf-8",
    )
    (root / "src/server/dot-agent.ts").write_text(
        """import { pageReviewTool } from '../shared/page-review.js';
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
""",
        encoding="utf-8",
    )
    (root / "src/client/Chat.tsx").write_text(
        """import { CallView } from './CallView';
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
""",
        encoding="utf-8",
    )
    (root / "src/client/main.tsx").write_text(
        """import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './style.css';
import './editor.css';
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
""",
        encoding="utf-8",
    )
    (root / "src/server/app.ts").write_text(
        """import { workspaceRoutes } from './workspace-routes.js';
export function createApp({ platform, voice }) {
  const app = new Hono();
  if (platform && voice) app.route('/api', workspaceRoutes(platform, voice));
  app.get('/api/state', (c) => c.json({}));
  return app;
}
""",
        encoding="utf-8",
    )
    return root


def test_browser_overlay_is_idempotent(tmp_path):
    checkout = _checkout(tmp_path)
    harness = OpenDotsBrowserE2E(
        ROOT,
        checkout,
        allow_drift=True,
    )

    first = harness.apply()
    second = harness.apply()

    assert first["changed"]
    assert second["changed"] == []

    app = (checkout / "src/server/app.ts").read_text(encoding="utf-8")
    assert "MADO_COCKPIT_M1_6_DOGFOOD_ROUTE" in app
    assert "MADO_COCKPIT_E2E === '1'" in app

    main = (checkout / "src/client/main.tsx").read_text(encoding="utf-8")
    assert "MadoDogfoodPage" in main
    assert "location.pathname === '/mado-dogfood'" in main

    assert (checkout / "scripts/mado-browser-e2e.ts").is_file()


def test_browser_route_is_environment_guarded():
    source = (
        ROOT
        / "src"
        / "mado_cockpit"
        / "opendots_browser_e2e.py"
    ).read_text(encoding="utf-8")

    assert "MADO_COCKPIT_E2E === '1'" in source
    assert "/api/mado-dogfood" in source


def test_browser_page_uses_real_m14_cards():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "e2e"
        / "src"
        / "client"
        / "MadoDogfoodPage.tsx"
    ).read_text(encoding="utf-8")

    assert "MadoToolCard" in source
    assert "MadoHumanGateCard" in source
    assert "/api/mado-dogfood/resolve" in source
    assert "Human Gate cleared" in source


def test_playwright_script_clicks_explicit_choice():
    source = (
        ROOT
        / "integrations"
        / "opendots"
        / "e2e"
        / "scripts"
        / "mado-browser-e2e.ts"
    ).read_text(encoding="utf-8")

    assert "chromium.launch" in source
    assert "stay_free" in source
    assert "awaiting_human" in source
    assert "awaiting_builder" in source
    assert "human_gate !== null" in source


def test_app_drift_fails_closed(tmp_path):
    checkout = _checkout(tmp_path)
    harness = OpenDotsBrowserE2E(
        ROOT,
        checkout,
        allow_drift=False,
    )

    with pytest.raises(OpenDotsDogfoodError, match="drift"):
        harness.preflight()
