"""MCC-M2.6.2f: explicit local-browser screenshot capture and evidence bridge.

Playwright is an optional operator-installed runtime. No network services,
design agents or third-party code are downloaded or automatically launched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import re
import shutil
import struct
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
import zlib
from typing import Any

from .component_foundry import ComponentGateError, _decode_png
from .design_intelligence_lab import (
    DesignIntelligenceLab, DesignLabError, _canonical, _read, _sha,
    _write_immutable,
)
from .models import Event

CAPTURE_SCHEMA = "mado.ui-bakeoff-browser-capture.v1"
SHEET_SCHEMA = "mado.ui-bakeoff-contact-sheet.v1"
CAPTURE_STATES = ("light", "dark", "mobile")
MOBILE = (390, 844)
PNG_LIMIT = 24 * 1024 * 1024


class BakeoffError(DesignLabError):
    """Invalid capture provenance, safety policy, or evidence."""


def _loopback_url(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str) or len(raw) > 2048:
        raise BakeoffError("URL must be a bounded local HTTP address")
    try:
        u = urlsplit(raw)
        port = u.port
    except ValueError as exc:
        raise BakeoffError("Malformed capture URL") from exc
    if (u.scheme != "http" or u.hostname not in ("localhost", "127.0.0.1", "::1")
            or port is None or port < 1024 or u.username or u.password
            or u.query or u.fragment or not u.netloc
            or "\\" in raw or any(c.isspace() for c in raw)):
        raise BakeoffError("Only credential-free, query-free explicit-port loopback HTTP URLs are permitted")
    # Return literal source URL and exact origin for the network allowlist.
    return raw, f"{u.scheme}://{u.netloc}"


def _screenshot_dimensions(raw: bytes) -> tuple[int, int]:
    try:
        w, h, _ = _decode_png(raw)
    except ComponentGateError as exc:
        raise BakeoffError("Invalid screenshot PNG or CRC") from exc
    return w, h


def _report_file(path: Path) -> dict[str, Any]:
    try:
        wrapper = json.loads(_read(path, 256 * 1024))
    except (ValueError, UnicodeError) as exc:
        raise BakeoffError("Invalid capture receipt JSON") from exc
    if (not isinstance(wrapper, dict) or set(wrapper) != {"sha256", "data"}
            or not isinstance(wrapper["data"], dict)
            or _sha(_canonical(wrapper["data"])) != wrapper["sha256"]):
        raise BakeoffError("Capture receipt integrity mismatch")
    return wrapper


def _browser_capture(*, url: str, origin: str, viewport: tuple[int, int],
                     browser_channel: str | None, browser_executable: str | None,
                     timeout_ms: int, ready_selector: str | None,
                     staging: Path) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise BakeoffError(
            "Playwright not installed. Opt in with: pip install playwright; "
            "install a browser separately before capture."
        ) from exc

    if browser_executable:
        executable = Path(browser_executable)
        if not executable.is_file() or executable.is_symlink():
            raise BakeoffError("Browser executable must be a preinstalled local file")
    else:
        executable = None
    blocked: list[str] = []
    console_errors: list[str] = []
    page_errors: list[str] = []
    status_code: int | None = None
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            channel=browser_channel if executable is None else None,
            executable_path=str(executable) if executable else None,
            args=["--no-first-run"],
        )
        try:
            ctx = browser.new_context(
                viewport={"width": viewport[0], "height": viewport[1]},
                screen={"width": viewport[0], "height": viewport[1]},
                device_scale_factor=1, color_scheme="light",
                reduced_motion="reduce", locale="en-US", timezone_id="UTC",
                service_workers="block", accept_downloads=False,
            )
            page = ctx.new_page()
            page.on("pageerror", lambda error: page_errors.append(str(error)[:400]))
            page.on("console", lambda msg: console_errors.append(msg.text[:400]) if msg.type == "error" else None)

            def route_handler(route: Any) -> None:
                target = route.request.url
                # Strict same-origin HTTP, no arbitrary external network.
                if target == origin or target.startswith(origin + "/"):
                    route.continue_()
                else:
                    blocked.append(target[:400])
                    route.abort()

            page.route("**/*", route_handler)
            response = page.goto(url, wait_until="load", timeout=timeout_ms)
            status_code = response.status if response else None
            if status_code is None or not 200 <= status_code < 400:
                raise BakeoffError("Local page did not return a successful HTTP response")
            if ready_selector:
                page.locator(ready_selector).first.wait_for(state="visible", timeout=timeout_ms)
            page.wait_for_function("document.fonts.status === 'loaded'", timeout=timeout_ms)
            if blocked or page_errors:
                raise BakeoffError("Page issued blocked external requests or script errors; inspect local build")

            snapshots = []
            for state in CAPTURE_STATES:
                if state == "light":
                    page.set_viewport_size({"width": viewport[0], "height": viewport[1]})
                    page.emulate_media(color_scheme="light", reduced_motion="reduce")
                    dims = viewport
                elif state == "dark":
                    page.emulate_media(color_scheme="dark", reduced_motion="reduce")
                    dims = viewport
                else:
                    page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
                    page.emulate_media(color_scheme="light", reduced_motion="reduce")
                    dims = MOBILE
                page.screenshot(path=str(staging / (state + ".png")),
                                full_page=False, animations="disabled", caret="hide",
                                timeout=timeout_ms)
                snapshots.append({"state": state, "width": dims[0], "height": dims[1]})
            if blocked or page_errors:
                raise BakeoffError("Browser errors or external requests occurred while capturing states")
            result = {
                "browser_engine": "chromium", "browser_version": browser.version,
                "browser_channel": browser_channel or "explicit_executable_or_bundled",
                "http_status": status_code, "locale": "en-US", "timezone": "UTC",
                "dpr": 1, "reduced_motion": "reduce", "animations": "disabled",
                "external_requests_blocked": len(blocked),
                "javascript_errors": len(page_errors),
                "console_errors": len(console_errors),
                "capture_states": snapshots,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            }
            ctx.close()
            return result
        finally:
            browser.close()


class ScreenshotEvidenceBridge:
    def __init__(self, root: str | Path = ".") -> None:
        self.lab = DesignIntelligenceLab(root)
        self.store = self.lab.store

    def _folder(self, experiment: str, candidate: str) -> tuple[Path, dict[str, Any], str]:
        folder, plan, digest = self.lab._experiment(experiment)
        if candidate not in plan["candidates"]:
            raise BakeoffError("Candidate is not part of the pinned experiment")
        return folder, plan, digest

    def capture(self, experiment: str, candidate: str, *, url: str,
                source_file: Path, provenance: str = "operator_supplied_build",
                browser_channel: str | None = None,
                browser_executable: str | None = None,
                timeout_ms: int = 15000, ready_selector: str | None = None) -> dict[str, Any]:
        folder, plan, digest = self._folder(experiment, candidate)
        url, origin = _loopback_url(url)
        if provenance not in {"fixture_smoke", "operator_supplied_build"}:
            raise BakeoffError("Invalid capture provenance classification")
        if browser_channel not in (None, "chrome", "chromium", "msedge"):
            raise BakeoffError("Unsupported browser channel")
        if type(timeout_ms) is not int or not 1000 <= timeout_ms <= 60000:
            raise BakeoffError("Timeout must be 1000–60000ms")
        if ready_selector and (len(ready_selector) > 160 or any(ord(c) < 32 for c in ready_selector)):
            raise BakeoffError("Invalid readiness selector")
        source = _read(source_file, 5 * 1024 * 1024)
        source_digest = _sha(source)
        evidence_dir = folder / "evidence"
        receipt_path = evidence_dir / f"{candidate}.capture.json"
        if receipt_path.exists():
            receipt = self.verify(experiment, candidate)
            if (receipt["source_file_sha256"] != source_digest
                    or receipt["url"] != url or receipt["provenance"] != provenance):
                raise BakeoffError("Existing capture disagrees with current source or origin")
            return {"status": "existing", "candidate": candidate,
                    "receipt": str(receipt_path), "sha256": _sha(_canonical(receipt))}
        names = [candidate + suffix for suffix in (".png", "-dark.png", "-mobile.png")]
        if any((evidence_dir / name).exists() for name in names):
            raise BakeoffError("Orphan screenshot evidence exists; manual review required")
        folder.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".capture-stage-", dir=folder) as tmp:
            staged = Path(tmp)
            runtime = _browser_capture(
                url=url, origin=origin, viewport=tuple(plan["brief"]["viewport"]),
                browser_channel=browser_channel, browser_executable=browser_executable,
                timeout_ms=timeout_ms, ready_selector=ready_selector, staging=staged)
            dimensions = [tuple(plan["brief"]["viewport"]),
                          tuple(plan["brief"]["viewport"]), MOBILE]
            images = []
            for (state, name, expected) in zip(CAPTURE_STATES, names, dimensions):
                raw = _read(staged / (state + ".png"), PNG_LIMIT)
                if _screenshot_dimensions(raw) != expected:
                    raise BakeoffError(f"{state} screenshot dimensions do not match capture contract")
                images.append({"state": state, "file": name, "sha256": _sha(raw),
                               "bytes": len(raw), "width": expected[0], "height": expected[1]})
            data = {
                "schema": CAPTURE_SCHEMA, "experiment": experiment, "candidate": candidate,
                "plan_sha256": digest, "candidate_upstream": next(
                    x for x in plan["upstreams"] if x["id"] == candidate),
                "url": url, "provenance": provenance,
                "source_file_sha256": source_digest,
                "source_file_name": source_file.name,
                "runtime": runtime, "images": images,
                "review_status": "not_human_reviewed",
            }
            receipt = {"sha256": _sha(_canonical(data)), "data": data}
            payload = _canonical(receipt) + b"\n"
            evidence_dir.mkdir(exist_ok=True)
            # Fail closed: artifact names are immutable; receipt is committed last.
            written: list[Path] = []
            try:
                for state, name in zip(CAPTURE_STATES, names):
                    dest = evidence_dir / name
                    if dest.exists() or dest.is_symlink():
                        raise BakeoffError("Capture output already exists")
                    (staged / (state + ".png")).replace(dest)
                    written.append(dest)
                if receipt_path.exists() or receipt_path.is_symlink():
                    raise BakeoffError("Capture receipt already exists")
                receipt_path.write_bytes(payload)
                written.append(receipt_path)
            except BaseException:
                for dest in written:
                    dest.unlink(missing_ok=True)
                raise
        self.store.append_event(Event(
            type="design.bakeoff.screenshot.captured",
            subject={"experiment": experiment, "candidate": candidate,
                     "plan_sha256": digest, "capture_sha256": receipt["sha256"],
                     "provenance": provenance, "source_file_sha256": source_digest},
        ))
        return {"status": "captured_unreviewed", "candidate": candidate,
                "receipt": str(receipt_path), "sha256": receipt["sha256"],
                "screenshots": names}

    def verify(self, experiment: str, candidate: str) -> dict[str, Any]:
        folder, plan, digest = self._folder(experiment, candidate)
        record = _report_file(folder / "evidence" / f"{candidate}.capture.json")
        data = record["data"]
        if (data.get("schema") != CAPTURE_SCHEMA or data.get("experiment") != experiment
                or data.get("candidate") != candidate or data.get("plan_sha256") != digest
                or data.get("candidate_upstream") != next(x for x in plan["upstreams"] if x["id"] == candidate)
                or data.get("provenance") not in {"fixture_smoke", "operator_supplied_build"}):
            raise BakeoffError("Capture provenance or experiment identity mismatch")
        _loopback_url(data["url"])
        runtime = data.get("runtime", {})
        if (runtime.get("browser_engine") != "chromium" or runtime.get("dpr") != 1
                or runtime.get("external_requests_blocked") != 0
                or runtime.get("javascript_errors") != 0
                or runtime.get("reduced_motion") != "reduce"):
            raise BakeoffError("Capture runtime contract mismatch")
        images = data.get("images")
        if not isinstance(images, list) or len(images) != 3:
            raise BakeoffError("Capture must include exactly three states")
        expect = [tuple(plan["brief"]["viewport"]), tuple(plan["brief"]["viewport"]), MOBILE]
        for image, state, dims in zip(images, CAPTURE_STATES, expect):
            suffix = {"light": ".png", "dark": "-dark.png", "mobile": "-mobile.png"}[state]
            name = candidate + suffix
            if (image.get("state") != state or image.get("file") != name
                    or (image.get("width"), image.get("height")) != dims):
                raise BakeoffError("Capture screenshot identity or viewport mismatch")
            image_bytes = _read(folder / "evidence" / name, PNG_LIMIT)
            if (image.get("bytes") != len(image_bytes)
                    or image.get("sha256") != _sha(image_bytes)
                    or _screenshot_dimensions(image_bytes) != dims):
                raise BakeoffError("Screenshot hash or structural integrity mismatch")
        return data

    def review(self, experiment: str, candidate: str, *, evaluation_file: str) -> dict[str, Any]:
        data = self.verify(experiment, candidate)
        if data["provenance"] != "operator_supplied_build":
            raise BakeoffError("Fixture-smoke captures cannot be scored as an actual agent run")
        if evaluation_file != candidate + ".json":
            raise BakeoffError("Human evaluation filename must match candidate")
        return self.lab.record(experiment, candidate, screenshot=candidate + ".png",
                               evaluation_file=evaluation_file)

    def compare(self, experiment: str) -> dict[str, Any]:
        folder, plan, _ = self.lab._experiment(experiment)
        result = self.lab.compare(experiment)
        by_id = {c["candidate"]: c for c in result["comparison"]}
        for cid in plan["candidates"]:
            path = folder / "evidence" / (cid + ".capture.json")
            if path.exists():
                data = self.verify(experiment, cid)
                by_id[cid]["screenshot_capture"] = "verified_local_browser"
                by_id[cid]["provenance"] = data["provenance"]
                by_id[cid]["capture_sha256"] = _report_file(path)["sha256"]
            else:
                by_id[cid]["screenshot_capture"] = "not_captured"
        result["capture_complete"] = all(by_id[c]["screenshot_capture"] == "verified_local_browser"
                                         and by_id[c]["provenance"] == "operator_supplied_build"
                                         for c in plan["candidates"])
        result["release_approved"] = False
        result["limitations"].extend([
            "Screenshots prove local browser rendering, not which design model authored the source.",
            "Fixture-smoke captures are not eligible for actual design-skill score comparison.",
            "Screenshots and self-asserted human reviews do not replace real access control or production QA.",
        ])
        return result

    def sheet(self, experiment: str, *, state: str = "light") -> dict[str, Any]:
        folder, plan, digest = self.lab._experiment(experiment)
        if state not in CAPTURE_STATES:
            raise BakeoffError("Unknown screenshot state")
        captures = [(cid, self.verify(experiment, cid)) for cid in plan["candidates"]]
        # The generated sheet is a view of existing immutable evidence, not a new capture.
        widths = {image["width"] for _, receipt in captures for image in receipt["images"] if image["state"] == state}
        heights = {image["height"] for _, receipt in captures for image in receipt["images"] if image["state"] == state}
        if len(widths) != 1 or len(heights) != 1:
            raise BakeoffError("Screenshots have different viewports")
        tile_w, tile_h = widths.pop(), heights.pop()
        cols = 2 if tile_w * 2 + 12 <= 4096 else 1
        rows = math.ceil(len(captures) / cols)
        pad = 12
        sheet_w = cols * tile_w + (cols - 1) * pad
        sheet_h = rows * tile_h + (rows - 1) * pad
        if sheet_w > 4096 or sheet_h > 4096 or sheet_w * sheet_h * 4 > 80 * 1024 * 1024:
            raise BakeoffError("Sheet exceeds 4096px / 80MiB budget; inspect source captures directly")
        pixels = bytearray(bytes((24, 27, 37, 255)) * (sheet_w * sheet_h))
        source_digests = {}
        for pos, (candidate, receipt) in enumerate(captures):
            image = next(x for x in receipt["images"] if x["state"] == state)
            source_digests[candidate] = image["sha256"]
            raw = _read(folder / "evidence" / image["file"], PNG_LIMIT)
            _, _, tile = _decode_png(raw)
            left = (pos % cols) * (tile_w + pad)
            top = (pos // cols) * (tile_h + pad)
            for y in range(tile_h):
                dst = ((top + y) * sheet_w + left) * 4
                src = y * tile_w * 4
                pixels[dst:dst + tile_w * 4] = tile[src:src + tile_w * 4]

        def chunk(kind: bytes, payload: bytes) -> bytes:
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(
                ">I", zlib.crc32(kind + payload) & 0xffffffff)

        scanlines = bytearray()
        for y in range(sheet_h):
            scanlines.append(0)
            scanlines.extend(pixels[y * sheet_w * 4:(y + 1) * sheet_w * 4])
        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", sheet_w, sheet_h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(bytes(scanlines), level=6))
               + chunk(b"IEND", b""))
        metadata = {
            "schema": SHEET_SCHEMA, "experiment": experiment, "plan_sha256": digest,
            "state": state, "candidates": list(plan["candidates"]),
            "source_sha256": source_digests, "sheet_sha256": _sha(png),
            "layout": {"columns": cols, "rows": rows, "tile_width": tile_w,
                       "tile_height": tile_h, "gutter": pad, "width": sheet_w, "height": sheet_h},
            "status": "visual_contact_sheet_not_quality_assessment",
        }
        output = folder / "comparison"
        sheet_path = output / (state + ".png")
        receipt_path = output / (state + ".json")
        if sheet_path.exists() and sheet_path.read_bytes() != png:
            raise BakeoffError("Prior contact sheet differs; evidence must not be overwritten")
        if receipt_path.exists() and receipt_path.read_bytes() != _canonical(metadata) + b"\n":
            raise BakeoffError("Prior sheet metadata differs; evidence must not be overwritten")
        _write_immutable(sheet_path, png)
        _write_immutable(receipt_path, _canonical(metadata) + b"\n")
        return {"status": metadata["status"], "path": str(sheet_path),
                "metadata": str(receipt_path), "sha256": metadata["sheet_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit local Playwright screenshot evidence bridge")
    parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("experiment")
    capture.add_argument("candidate")
    capture.add_argument("--url", required=True)
    capture.add_argument("--source-file", required=True, type=Path)
    capture.add_argument("--provenance", default="operator_supplied_build",
                         choices=["operator_supplied_build", "fixture_smoke"])
    capture.add_argument("--browser-channel", choices=["chrome", "chromium", "msedge"])
    capture.add_argument("--browser-executable")
    capture.add_argument("--timeout-ms", type=int, default=15000)
    capture.add_argument("--ready-selector")
    verify = sub.add_parser("verify")
    verify.add_argument("experiment")
    verify.add_argument("candidate")
    review = sub.add_parser("review")
    review.add_argument("experiment")
    review.add_argument("candidate")
    review.add_argument("--evaluation-file", required=True)
    compare = sub.add_parser("compare")
    compare.add_argument("experiment")
    sheet = sub.add_parser("sheet")
    sheet.add_argument("experiment")
    sheet.add_argument("--state", choices=CAPTURE_STATES, default="light")
    args = parser.parse_args(argv)
    try:
        bridge = ScreenshotEvidenceBridge(args.root)
        if args.command == "capture":
            out = bridge.capture(args.experiment, args.candidate, url=args.url,
                                 source_file=args.source_file, provenance=args.provenance,
                                 browser_channel=args.browser_channel,
                                 browser_executable=args.browser_executable,
                                 timeout_ms=args.timeout_ms, ready_selector=args.ready_selector)
        elif args.command == "verify":
            out = {"status": "verified", "capture": bridge.verify(args.experiment, args.candidate)}
        elif args.command == "review":
            out = bridge.review(args.experiment, args.candidate, evaluation_file=args.evaluation_file)
        elif args.command == "compare":
            out = bridge.compare(args.experiment)
        else:
            out = bridge.sheet(args.experiment, state=args.state)
        print(json.dumps(out, indent=2, ensure_ascii=False, sort_keys=True))
        return 0
    except (BakeoffError, DesignLabError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f"design bakeoff: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
