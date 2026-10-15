"""Run one real-Chromium capture for every fixture-only candidate.

This is NOT a comparison of external AI design skills. All three screenshots
are the same locally authored smoke-test page and are marked fixture_smoke.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from threading import Thread

from mado_cockpit.design_bakeoff import ScreenshotEvidenceBridge
from mado_cockpit.design_discovery import DesignDiscoveryHub
from mado_cockpit.design_intelligence_lab import DesignIntelligenceLab
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Local fixture-only browser smoke test")
    parser.add_argument("--output-root", type=Path, default=Path(".mado/bakeoff-proof"))
    parser.add_argument("--browser-channel", choices=("chrome", "chromium", "msedge"))
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    root = args.output_root.resolve()
    if (root / ".mado").exists():
        parser.error("Output workspace already exists: use an empty output root")
    fixture = Path("fixtures/design_bakeoff/approval-console-smoke.html").resolve()
    brief = Path("fixtures/design_intelligence/mcc-m2.6.2e-approval-console.json").resolve()
    if not fixture.is_file() or not brief.is_file():
        parser.error("Run this script from the repository root")

    root.mkdir(parents=True, exist_ok=True)
    CockpitStore(root).init(Project(id="bakeoff-browser-smoke", name="Browser smoke", root=str(root)))
    hub = DesignDiscoveryHub(root)
    hub.bootstrap()
    lab = DesignIntelligenceLab(root)
    plan = lab.plan(brief)
    exp = plan["experiment"]
    bridge = ScreenshotEvidenceBridge(root)
    handler = partial(QuietHandler, directory=str(fixture.parent))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    runner = Thread(target=server.serve_forever, daemon=True)
    runner.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/{fixture.name}"
        for candidate in ("superdesign", "better-design", "design-taste"):
            result = bridge.capture(
                exp, candidate, url=url, source_file=fixture,
                provenance="fixture_smoke",
                browser_channel=args.browser_channel,
                browser_executable=args.browser_executable,
                ready_selector="[data-bakeoff-ready]",
                timeout_ms=30000,
            )
            assert result["status"] == "captured_unreviewed", result
            assert bridge.verify(exp, candidate)["provenance"] == "fixture_smoke"
        sheets = [bridge.sheet(exp, state=state) for state in ("light", "dark", "mobile")]
        comparison = bridge.compare(exp)
        assert comparison["complete"] is False
        assert comparison["capture_complete"] is False
        assert comparison["release_approved"] is False
        assert all(x["screenshot_capture"] == "verified_local_browser"
                   for x in comparison["comparison"])
        assert all(x["status"] == "not_evaluated" for x in comparison["comparison"])
        report = {
            "schema": "mado.ui-bakeoff-fixture-proof.v1",
            "real_browser_capture": True,
            "fixture_only_not_agent_generated": True,
            "experiment": exp,
            "candidate_count": 3,
            "rendered_screenshot_count": 9,
            "sheets": sheets,
            "reviewed": False,
            "release_approved": False,
        }
        (root / "smoke-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
        return 0
    finally:
        server.shutdown()
        runner.join(timeout=10)
        server.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
