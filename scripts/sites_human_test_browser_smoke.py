"""MCC-M2.9: real Chromium UI interactions against a local static build.

This exercises a synthetic local test flow, never a real playable game or Site.
"""
from __future__ import annotations

import argparse
import json
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from mado_cockpit.sites_portal import build_site


def run(output: Path) -> dict:
    if output.exists():
        raise ValueError("Refusing to replace browser smoke evidence")
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=False)
    checks = []
    with TemporaryDirectory(prefix="mado-human-test-") as tmp:
        site = Path(tmp) / "site"
        build_site(output=site)
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0),
            partial(SimpleHTTPRequestHandler, directory=str(site)),
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    for label, size in [
                        ("desktop", {"width": 1440, "height": 900}),
                        ("mobile", {"width": 390, "height": 844}),
                    ]:
                        context = browser.new_context(
                            viewport=size, accept_downloads=True,
                            reduced_motion="reduce", service_workers="block",
                        )
                        page = context.new_page()
                        try:
                            url = f"http://127.0.0.1:{server.server_port}/test-flight.html?project=mado-game-service-factory"
                            page.goto(url, wait_until="load")
                            page.locator("#flightContent:not([hidden])").wait_for()
                            assert "初見プレイ" in page.locator("#missionTitle").inner_text()
                            assert page.locator("#stepList input").count() == 3
                            assert page.locator("#openPreview").is_disabled()
                            assert page.evaluate("localStorage.length") == 0
                            # URL controls reject both script and remote non-HTTPS schemes.
                            page.locator("#previewUrl").fill("javascript:alert(1)")
                            assert page.locator("#openPreview").is_disabled()
                            page.locator("#previewUrl").fill("http://example.net/")
                            assert page.locator("#openPreview").is_disabled()
                            page.locator("#previewUrl").fill("http://localhost:7788")
                            assert page.locator("#openPreview").is_enabled()
                            assert "NOT VERIFIED" in page.locator("#previewState").inner_text()
                            page.locator("#stepList input").first.check()
                            page.locator('#ratings button[data-rating="stuck"]').click()
                            page.locator("#note").fill("移動ボタンを見つけるのに迷った")
                            page.locator("#buildRef").fill("synthetic-build-1")
                            page.locator("#saveDraft").click()
                            assert "保存しました" in page.locator("#feedbackStatus").inner_text()
                            assert page.evaluate("localStorage.length") == 1
                            page.reload()
                            page.locator("#flightContent:not([hidden])").wait_for()
                            assert page.locator("#note").input_value() == "移動ボタンを見つけるのに迷った"
                            assert page.locator("#stepList input").first.is_checked()
                            assert page.locator('#ratings button[data-rating="stuck"]').get_attribute("aria-pressed") == "true"
                            with page.expect_download() as event:
                                page.locator("#exportDraft").click()
                            receipt = output / f"human-test-{label}.json"
                            event.value.save_as(receipt)
                            report = json.loads(receipt.read_text(encoding="utf-8"))
                            assert report["schema"] == "mado.human-feedback.v1"
                            assert report["rating"] == "stuck"
                            assert report["completed_step_indexes"] == [0]
                            assert "preview_url" not in report
                            assert report["preview_url_included"] is False
                            page.evaluate("window.open = url => {window.__issueDraftUrl = url; return null;}")
                            page.once("dialog", lambda dialog: dialog.accept())
                            page.locator("#openIssue").click()
                            issue_url = page.evaluate("window.__issueDraftUrl")
                            assert issue_url.startswith("https://github.com/madowaku/mado-game-service-factory/issues/new?")
                            assert "body=" in issue_url
                            assert "移動ボタン" in page.locator("#issuePreview").inner_text()
                            page.once("dialog", lambda dialog: dialog.accept())
                            page.locator("#clearDraft").click()
                            assert page.evaluate("localStorage.length") == 0
                            assert not page.locator("#stepList input").first.is_checked()
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
                            image = output / f"human-test-{label}-fixture.png"
                            page.screenshot(path=str(image), full_page=True, animations="disabled")
                            checks.append({"viewport":label, "result":"passed", "screenshot":image.name})
                        finally:
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=10)
    result = {
        "schema": "mado.human-test-browser-fixture.v1",
        "checks": checks,
        "synthetic_local_flow_only": True,
        "actual_gameplay_tested": False,
        "actual_human_review_performed": False,
        "github_issue_submitted": False,
        "live_site_verified": False,
    }
    (output / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Local Chromium synthetic human-test flight smoke")
    parser.add_argument("--output", type=Path, default=Path(".mado/human-test-browser-fixture"))
    args = parser.parse_args()
    print(json.dumps(run(args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
