"""MCC-M2.8.1: opt-in browser dogfood for a real ChatGPT Site.

This tool performs read-only visits. It does NOT deploy, authenticate, share,
alter a Site or assert an audience from the operator's login session.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

VIEWPORTS = {"desktop": (1440, 900), "tablet": (820, 1180), "mobile": (390, 844)}
MAX_REDIRECTS = 4


class LiveSitesError(ValueError):
    pass


def validate_site_url(url: str) -> str:
    if not isinstance(url, str) or len(url) > 350:
        raise LiveSitesError("URL must be a short ChatGPT Sites HTTPS URL")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or not parts.hostname.endswith(".chatgpt.site")
        or parts.hostname == "chatgpt.site"
        or parts.username is not None
        or parts.password is not None
        or parts.port is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise LiveSitesError("Only root HTTPS *.chatgpt.site URLs are accepted")
    return f"https://{parts.hostname}/"


def evaluate_checks(observations: dict) -> dict:
    """Only measured observations are eligible to be marked as passed."""
    required = ("title", "h1", "main", "search", "filters", "project_cards",
                "no_horizontal_overflow", "no_js_errors")
    results = {}
    for viewport in VIEWPORTS:
        record = observations.get(viewport)
        if not isinstance(record, dict):
            results[viewport] = {"status": "not_observed", "checks": {}}
            continue
        checks = {name: record.get(name) is True for name in required}
        results[viewport] = {
            "status": "passed" if all(checks.values()) else "failed",
            "checks": checks,
        }
    return results


def decision_gate(report: dict) -> dict:
    visual = report.get("visual_checks", {})
    all_pass = len(visual) == len(VIEWPORTS) and all(
        visual.get(v, {}).get("status") == "passed" for v in VIEWPORTS
    )
    # Browser success cannot prove external public access, authorized audience,
    # or matching source revision. These require independent verification.
    return {
        "ui_candidate": "passed" if all_pass else "hold",
        "public_access": "unverified",
        "audience": "unverified",
        "source_revision": "unverified",
        "release_approved": False,
    }


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_capture(url: str, output: Path) -> dict:
    url = validate_site_url(url)
    if output.exists() and any(output.iterdir()):
        raise LiveSitesError("Refusing to overwrite an existing evidence directory")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise LiveSitesError("Install Playwright and Chromium separately before browser capture") from exc
    observations = {}
    screenshots = {}
    errors = {}
    output.mkdir(parents=True, exist_ok=True)
    # New unauthenticated browser context. No user profile, cookies, or tokens.
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            for name, (width, height) in VIEWPORTS.items():
                context = browser.new_context(
                    viewport={"width": width, "height": height},
                    device_scale_factor=1,
                    color_scheme="dark",
                    reduced_motion="reduce",
                    service_workers="block",
                )
                page = context.new_page()
                js_errors = []
                page.on("pageerror", lambda error: js_errors.append(str(error)[:500]))
                try:
                    response = page.goto(url, wait_until="domcontentloaded", timeout=20000)
                    page.wait_for_timeout(900)
                    if not page.url.startswith(url):
                        raise LiveSitesError("Site redirected away from the approved root")
                    status = response.status if response else None
                    if status != 200:
                        raise LiveSitesError(f"Unexpected HTTP status: {status}")
                    observed = page.evaluate("""() => {
                      const has = selector => Boolean(document.querySelector(selector));
                      const visible = selector => {
                        const n = document.querySelector(selector);
                        return Boolean(n && n.getBoundingClientRect().width > 0 && n.getBoundingClientRect().height > 0);
                      };
                      return {
                        title: document.title.includes("MADO"),
                        h1: visible("h1"),
                        main: has("main"),
                        search: visible("input[type=search]"),
                        filters: has("#filters button[aria-pressed]"),
                        project_cards: document.querySelectorAll(".project-card").length >= 1,
                        no_horizontal_overflow: document.documentElement.scrollWidth <= window.innerWidth + 2
                      };
                    }""")
                    observed["no_js_errors"] = not js_errors
                    observations[name] = observed
                    path = output / f"live-{name}.png"
                    page.screenshot(path=str(path), full_page=True, animations="disabled")
                    screenshots[name] = {"file": path.name, "sha256": _sha(path)}
                except Exception as exc:
                    errors[name] = str(exc)[:400]
                finally:
                    context.close()
        finally:
            browser.close()
    report = {
        "schema": "mado.sites-live-dogfood.v1",
        "url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "environment": "fresh_unauthenticated_chromium",
        "visual_checks": evaluate_checks(observations),
        "screenshots": screenshots,
        "errors": errors,
        "observation_not_proof_of_publication": True,
    }
    report["gate"] = decision_gate(report)
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only live ChatGPT Sites browser dogfood")
    parser.add_argument("--url", required=True, help="Approved root https://*.chatgpt.site/")
    parser.add_argument("--output", type=Path, required=True, help="New or empty evidence directory")
    args = parser.parse_args()
    try:
        print(json.dumps(run_capture(args.url, args.output), ensure_ascii=False, indent=2))
    except LiveSitesError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
