"""Actual local Chromium interaction smoke, with obviously synthetic image fixtures.

This proves the gallery UI works, NOT that the upstream screenshots were inspected,
licensed, fetched or that a ChatGPT Site is deployed.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from mado_cockpit.sites_portal import build_site


SYNTHETIC_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="700">
<rect width="1200" height="700" fill="#183449"/>
<rect x="42" y="42" width="1116" height="616" fill="#294f5b" stroke="#b1f0d0" stroke-width="5"/>
<text x="85" y="340" font-family="sans-serif" font-size="92" font-weight="bold" fill="#b1f0d0">FIXTURE ONLY</text>
<text x="86" y="425" font-family="sans-serif" font-size="39" fill="#fff">No actual source image displayed</text>
</svg>"""


def run(output: Path) -> dict:
    if output.exists() and any(output.iterdir()):
        raise ValueError("Refusing to overwrite gallery screenshot evidence")
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="mado-sites-gallery-") as tmp:
        site_dir = Path(tmp) / "site"
        build_site(output=site_dir)
        handler = partial(SimpleHTTPRequestHandler, directory=str(site_dir))
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                checks = []
                try:
                    for label, viewport in [
                        ("desktop", {"width": 1440, "height": 900}),
                        ("mobile", {"width": 390, "height": 844}),
                    ]:
                        context = browser.new_context(
                            viewport=viewport, color_scheme="dark",
                            reduced_motion="reduce", device_scale_factor=1,
                            service_workers="block",
                        )
                        page = context.new_page()
                        page.route(
                            "https://raw.githubusercontent.com/**",
                            lambda route: route.fulfill(status=200, content_type="image/svg+xml", body=SYNTHETIC_SVG),
                        )
                        try:
                            url = "http://127.0.0.1:" + str(server.server_port) + "/"
                            page.goto(url, wait_until="load", timeout=30000)
                            page.locator("#galleryGrid .gallery-tile").first.wait_for()
                            assert page.locator("#galleryGrid .gallery-tile").count() == 4
                            assert page.locator("#projectGrid .project-card").count() == 12
                            page.get_by_role("button", name="E2E GOLDENS").click()
                            assert page.locator("#galleryGrid .gallery-tile").count() == 2
                            page.get_by_role("button", name="MARKETING ASSETS").click()
                            assert page.locator("#galleryGrid .gallery-tile").count() == 2
                            page.locator("#galleryGrid .gallery-preview").first.click()
                            assert page.locator("#galleryDialog").evaluate("(d) => d.open") is True
                            href = page.locator("#dialogSource").get_attribute("href")
                            assert href and href.startswith("https://github.com/madowaku/")
                            page.keyboard.press("Escape")
                            assert page.locator("#galleryDialog").evaluate("(d) => d.open") is False
                            page.get_by_role("button", name="ALL SOURCES").click()
                            assert page.locator("#galleryGrid .gallery-tile").count() == 4
                            page.locator("#search").fill("Asset Foundry")
                            assert page.locator("#projectGrid .project-card").count() == 1
                            page.locator("#search").fill("unknown-inventory")
                            assert page.locator("#projectGrid .project-card").count() == 0
                            assert page.locator("#empty").is_visible()
                            page.locator("#reset").click()
                            assert page.locator("#projectGrid .project-card").count() == 12
                            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
                            path = output / ("gallery-" + label + "-fixture.png")
                            page.screenshot(path=str(path), full_page=True, animations="disabled")
                            checks.append({"viewport": label, "result": "passed", "screenshot": path.name})
                        finally:
                            context.close()
                finally:
                    browser.close()
        finally:
            server.shutdown()
            thread.join(timeout=10)
    report = {
        "schema": "mado.gallery-browser-fixture.v1",
        "checks": checks,
        "external_images": "intercepted_with_explicit_fixture_svg",
        "actual_image_pixels_verified": False,
        "real_chatgpt_site_tested": False,
        "release_approved": False,
    }
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Chromium interaction fixture for MCC-M2.8.2")
    parser.add_argument("--output", type=Path, default=Path(".mado/sites-gallery-browser-fixture"))
    args = parser.parse_args()
    print(json.dumps(run(args.output), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
