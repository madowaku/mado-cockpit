"""MCC-M2.6.2g: real-build provenance and non-authorizing design decision gate.

Accept externally produced local build outputs, inspect them as inert files, and
request opt-in browser capture from MCC-M2.6.2f. No design service, agent, npm,
build step or external URL is invoked. Human selection never authorizes release.
"""
from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from threading import Thread
from typing import Any

from .design_bakeoff import ScreenshotEvidenceBridge, BakeoffError
from .design_intelligence_lab import (
    CANDIDATE_MAP, DesignIntelligenceLab, DesignLabError,
    _ACTOR_RE, _canonical, _data, _read, _sha, _write_immutable,
)
from .models import Event

RUN_SCHEMA = "mado.ui-real-run.v1"
RUN_RECEIPT_SCHEMA = "mado.ui-real-run-receipt.v1"
REPORT_SCHEMA = "mado.ui-design-decision-report.v1"
CHOICE_SCHEMA = "mado.ui-design-human-selection.v1"
_SHA40 = re.compile(r"[0-9a-f]{40}\Z")
_RUN_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._:-]{7,119}\Z")
_RUN_MODES = {
    "superdesign": "superdesign_cli",
    "better-design": "better_design_mcp",
    "design-taste": "design_taste_skill",
}
_PASS_SCORE = 75.0
_MAX_FILES = 1000
_MAX_FILE_BYTES = 20 * 1024 * 1024
_MAX_TOTAL_BYTES = 80 * 1024 * 1024


class QualityGateError(DesignLabError):
    """Missing, inconsistent, unreviewed or misattributed real UI evidence."""


def _safe_build_tree(bundle: Path) -> dict[str, Any]:
    if bundle.is_symlink() or not bundle.is_dir():
        raise QualityGateError("Build root must be a real local directory")
    files = []
    total = 0
    for base, dirs, filenames in os.walk(bundle, followlinks=False):
        for name in dirs:
            d = Path(base) / name
            if d.is_symlink() or name == ".git" or name == "node_modules":
                raise QualityGateError("Symlink or development-source directory inside release build")
        for name in filenames:
            p = Path(base) / name
            if p.is_symlink() or not p.is_file():
                raise QualityGateError("Build contains symlink or non-regular file")
            relative = p.relative_to(bundle).as_posix()
            if (name.startswith(".env") or name.endswith((".pem", ".key", ".p12"))
                    or relative.startswith(".git/")):
                raise QualityGateError("Secret-looking file prohibited in browser build")
            size = p.stat().st_size
            if size > _MAX_FILE_BYTES:
                raise QualityGateError("Build file exceeds 20 MiB")
            total += size
            if total > _MAX_TOTAL_BYTES or len(files) >= _MAX_FILES:
                raise QualityGateError("Build exceeds bounded intake limits")
            files.append({"path": relative, "sha256": _sha(p.read_bytes()), "bytes": size})
    files.sort(key=lambda x: x["path"])
    if not files:
        raise QualityGateError("Build directory has no files")
    html = next((item for item in files if item["path"] == "index.html"), None)
    if html is None:
        raise QualityGateError("Static capture requires an index.html at the build root")
    return {"files": files, "entrypoint": "index.html",
            "entrypoint_sha256": html["sha256"], "file_count": len(files),
            "total_bytes": total, "tree_sha256": _sha(_canonical(files))}


def _read_run_declaration(path: Path, *, experiment: str, candidate: str,
                          task_sha: str, upstream_sha: str) -> dict[str, Any]:
    data = _data(path)
    expected = {"schema", "experiment", "candidate", "task_sha256",
                "upstream_commit", "execution_mode", "run_id", "operator",
                "command_summary", "output_revision", "cost_usd", "duration_seconds",
                "status"}
    if set(data) != expected or data.get("schema") != RUN_SCHEMA:
        raise QualityGateError("Run declaration contract mismatch")
    if (data["experiment"] != experiment or data["candidate"] != candidate
            or data["task_sha256"] != task_sha
            or data["upstream_commit"] != upstream_sha):
        raise QualityGateError("Run declaration is not bound to the task or pinned upstream")
    mode = data["execution_mode"]
    if mode not in {_RUN_MODES[candidate], "manual_baseline"}:
        raise QualityGateError("Execution mode mismatches selected provider")
    if not isinstance(data["run_id"], str) or not _RUN_ID.fullmatch(data["run_id"]):
        raise QualityGateError("Run ID must be a stable external reference")
    if not isinstance(data["operator"], str) or not _ACTOR_RE.fullmatch(data["operator"]):
        raise QualityGateError("Operator must use human:<id>; this is not authentication")
    if (not isinstance(data["command_summary"], str)
            or not 12 <= len(data["command_summary"]) <= 800
            or any(ord(ch) < 32 for ch in data["command_summary"])):
        raise QualityGateError("Missing or unsafe execution summary")
    if not isinstance(data["output_revision"], str) or not _SHA40.fullmatch(data["output_revision"]):
        raise QualityGateError("Output revision must be a 40-character Git SHA assertion")
    cost, duration = data["cost_usd"], data["duration_seconds"]
    if cost is not None and (type(cost) not in (int, float)
                             or not 0 <= cost <= 100000):
        raise QualityGateError("Cost must be nonnegative or null if unknown")
    if type(duration) not in (int, float) or not 0 < duration <= 86400:
        raise QualityGateError("Actual duration in seconds must be 0–86400")
    if data["status"] != "completed":
        raise QualityGateError("Incomplete external runs cannot enter the bake-off")
    return data


def _receipt(path: Path) -> tuple[dict[str, Any], str]:
    wrapper = _data(path)
    if (set(wrapper) != {"sha256", "data"} or not isinstance(wrapper["data"], dict)
            or _sha(_canonical(wrapper["data"])) != wrapper["sha256"]):
        raise QualityGateError("Run receipt integrity mismatch")
    if wrapper["data"].get("schema") != RUN_RECEIPT_SCHEMA:
        raise QualityGateError("Unrecognized run receipt")
    return wrapper["data"], wrapper["sha256"]


class _StaticHandler(SimpleHTTPRequestHandler):
    """A test-only static server, never an arbitrary application subprocess."""
    def log_message(self, *args: Any) -> None:
        return

    def list_directory(self, path: str) -> None:
        self.send_error(403, "Directory listing disabled")

    def translate_path(self, path: str) -> str:
        candidate = Path(super().translate_path(path))
        root = Path(self.directory).resolve()
        if not candidate.resolve().is_relative_to(root):
            return str(root / "__denied__")
        if any(part in (".env", ".git", "node_modules") for part in candidate.parts):
            return str(root / "__denied__")
        return str(candidate)


class RealUIDecisionGate:
    def __init__(self, root: str | Path = ".") -> None:
        self.lab = DesignIntelligenceLab(root)
        self.bridge = ScreenshotEvidenceBridge(root)
        self.store = self.lab.store

    def _experiment(self, exp: str, candidate: str) -> tuple[Path, dict[str, Any], str]:
        folder, plan, digest = self.lab._experiment(exp)
        if plan["track"] != "design_skill" or candidate not in plan["candidates"]:
            raise QualityGateError("Real UI design gate needs a design_skill experiment candidate")
        return folder, plan, digest

    def intake(self, exp: str, candidate: str, *, declaration_file: Path,
               bundle: Path, trace_file: Path) -> dict[str, Any]:
        folder, plan, digest = self._experiment(exp, candidate)
        task_file = folder / "tasks" / (candidate + ".json")
        task_digest = _sha(_read(task_file))
        upstream_sha = CANDIDATE_MAP[candidate]["commit"]
        declaration = _read_run_declaration(declaration_file, experiment=exp,
                                             candidate=candidate, task_sha=task_digest,
                                             upstream_sha=upstream_sha)
        trace = _read(trace_file, 1024 * 1024)
        if not 40 <= len(trace) <= 1024 * 1024:
            raise QualityGateError("Execution trace must be at least 40 bytes and at most 1 MiB")
        tree = _safe_build_tree(bundle)
        root_path = str(bundle.resolve())
        data = {
            "schema": RUN_RECEIPT_SCHEMA, "experiment": exp, "plan_sha256": digest,
            "candidate": candidate, "upstream_repository": CANDIDATE_MAP[candidate]["repository"],
            "upstream_commit": upstream_sha, "task_sha256": task_digest,
            "declaration_sha256": _sha(_read(declaration_file)),
            "declaration_path": str(declaration_file.resolve()),
            "declaration": declaration,
            "trace": {"sha256": _sha(trace), "path": str(trace_file.resolve()),
                      "bytes": len(trace)},
            "build": {"root": root_path, **tree},
            "provenance_status": "operator_attested_not_independently_verified",
        }
        receipt_path = folder / "runs" / (candidate + ".json")
        payload = _canonical({"sha256": _sha(_canonical(data)), "data": data}) + b"\n"
        fresh = _write_immutable(receipt_path, payload)
        if fresh:
            self.store.append_event(Event(type="design.bakeoff.real_run.intaken", actor=declaration["operator"],
                                          subject={"experiment": exp, "candidate": candidate,
                                                   "run_sha256": _sha(_canonical(data)),
                                                   "provenance": declaration["execution_mode"]}))
        return {"status": "intaken" if fresh else "existing", "experiment": exp,
                "candidate": candidate, "run_receipt": str(receipt_path),
                "build_sha256": tree["tree_sha256"],
                "provenance": data["provenance_status"]}

    def verify_run(self, exp: str, candidate: str) -> tuple[dict[str, Any], str]:
        folder, plan, digest = self._experiment(exp, candidate)
        data, rec_sha = _receipt(folder / "runs" / (candidate + ".json"))
        task_file = folder / "tasks" / (candidate + ".json")
        if (data.get("experiment") != exp or data.get("candidate") != candidate
                or data.get("plan_sha256") != digest
                or data.get("task_sha256") != _sha(_read(task_file))
                or data.get("upstream_commit") != CANDIDATE_MAP[candidate]["commit"]
                or data.get("upstream_repository") != CANDIDATE_MAP[candidate]["repository"]):
            raise QualityGateError("Run receipt no longer matches the pinned experiment")
        decl = data["declaration"]
        declaration_path = Path(data["declaration_path"])
        if _sha(_read(declaration_path)) != data["declaration_sha256"]:
            raise QualityGateError("Run declaration file changed after intake")
        original = _read_run_declaration(
            declaration_path, experiment=exp, candidate=candidate,
            task_sha=_sha(_read(task_file)),
            upstream_sha=CANDIDATE_MAP[candidate]["commit"])
        if original != decl:
            raise QualityGateError("Run declaration modified")
        trace = data["trace"]
        if _sha(_read(Path(trace["path"]), 1024 * 1024)) != trace["sha256"]:
            raise QualityGateError("Execution trace changed after intake")
        tree = _safe_build_tree(Path(data["build"]["root"]))
        for key in ("tree_sha256", "entrypoint_sha256", "total_bytes", "file_count", "files"):
            if tree[key] != data["build"][key]:
                raise QualityGateError("Local build changed after run intake")
        return data, rec_sha

    def capture_local(self, exp: str, candidate: str, *, browser_channel: str | None = None,
                      browser_executable: str | None = None,
                      timeout_ms: int = 30000) -> dict[str, Any]:
        run, _ = self.verify_run(exp, candidate)
        folder, plan, digest = self._experiment(exp, candidate)
        bundle = Path(run["build"]["root"])
        entrypoint = bundle / run["build"]["entrypoint"]
        handler = partial(_StaticHandler, directory=str(bundle))
        http = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            mode = run["declaration"]["execution_mode"]
            provenance = "fixture_smoke" if mode == "manual_baseline" else "operator_supplied_build"
            captured = self.bridge.capture(
                exp, candidate, url=f"http://127.0.0.1:{http.server_port}/index.html",
                source_file=entrypoint, provenance=provenance,
                browser_channel=browser_channel, browser_executable=browser_executable,
                timeout_ms=timeout_ms, ready_selector="body",
                expected_served_html_sha256=run["build"]["entrypoint_sha256"],
            )
            verified = self.bridge.verify(exp, candidate)
            if verified["runtime"].get("served_html_sha256") != run["build"]["entrypoint_sha256"]:
                raise QualityGateError("Served browser HTML did not match declared build entrypoint")
            self.verify_run(exp, candidate)
            return {**captured, "run_receipt_sha256": _receipt(
                folder / "runs" / (candidate + ".json"))[1],
                    "served_entrypoint_sha256": verified["runtime"]["served_html_sha256"]}
        finally:
            http.shutdown()
            thread.join(timeout=10)
            http.server_close()

    def _browser_audit(self, runtime: dict[str, Any]) -> list[str]:
        errors = []
        records = runtime.get("dom_audits", [])
        if len(records) != 3 or [r.get("state") for r in records] != ["light", "dark", "mobile"]:
            return ["missing_per_state_dom_audit"]
        for item in records:
            state = item["state"]
            if not item.get("lang_present") or item.get("main_count", 0) < 1 or item.get("heading_count", 0) < 1:
                errors.append(f"{state}:missing_landmark_or_page_language")
            if item.get("focusable_count", 0) < 1 or item.get("unnamed_controls") != 0:
                errors.append(f"{state}:missing_named_keyboard_controls")
            if item.get("horizontal_overflow_px", 9999) > 2:
                errors.append(f"{state}:horizontal_overflow")
            if item.get("reduced_motion_active") is not True:
                errors.append(f"{state}:reduced_motion_not_active")
        return errors

    def evaluate(self, exp: str) -> dict[str, Any]:
        folder, plan, digest = self.lab._experiment(exp)
        if plan["track"] != "design_skill":
            raise QualityGateError("Quality decision gate only compares design skills")
        # This triggers prior Lab assessment and screenshot hash verification.
        baseline = self.lab.compare(exp)
        lookup = {x["candidate"]: x for x in baseline["comparison"]}
        rows: list[dict[str, Any]] = []
        candidate_screenshots: dict[str, str] = {}
        for cid in plan["candidates"]:
            reasons: list[str] = []
            row: dict[str, Any] = {"candidate": cid, "score_percent": None,
                                   "cost_usd": None, "duration_seconds": None,
                                   "status": "not_evaluated", "reasons": reasons}
            run_path = folder / "runs" / (cid + ".json")
            capture_path = folder / "evidence" / (cid + ".capture.json")
            assessment_path = folder / "assessments" / (cid + ".json")
            run = None
            if not run_path.is_file():
                reasons.append("missing_real_run")
            else:
                run, receipt_sha = self.verify_run(exp, cid)
                row["run_receipt_sha256"] = receipt_sha
                decl = run["declaration"]
                row["cost_usd"] = decl["cost_usd"]
                row["duration_seconds"] = decl["duration_seconds"]
                row["execution_mode"] = decl["execution_mode"]
                if decl["execution_mode"] == "manual_baseline":
                    reasons.append("manually_authored_baseline_not_provider_run")
                if decl["cost_usd"] is None:
                    reasons.append("cost_unreported")
            capture = None
            if not capture_path.is_file():
                reasons.append("missing_browser_capture")
            else:
                capture = self.bridge.verify(exp, cid)
                if capture["provenance"] != "operator_supplied_build":
                    reasons.append("fixture_capture_not_provider_run")
                if run is None:
                    reasons.append("capture_without_run")
                else:
                    if capture["source_file_sha256"] != run["build"]["entrypoint_sha256"]:
                        reasons.append("source_vs_capture_digest_mismatch")
                    if capture["runtime"].get("served_html_sha256") != run["build"]["entrypoint_sha256"]:
                        reasons.append("served_html_not_bound_to_build")
                reasons.extend(self._browser_audit(capture["runtime"]))
                candidate_screenshots[cid] = capture["images"][0]["sha256"]
                row["capture_sha256"] = _sha(_canonical(capture))
            if not assessment_path.is_file():
                reasons.append("missing_human_review")
            else:
                score = lookup[cid]
                if score["status"] != "human_asserted_evaluation":
                    reasons.append("invalid_human_review")
                else:
                    review = _data(folder / "evidence" / (cid + ".json"))
                    row["score_percent"] = score["score_percent"]
                    if not score["all_qa_checks_passed"]:
                        reasons.append("human_qa_checks_failed")
                    if score["score_percent"] < _PASS_SCORE:
                        reasons.append("quality_floor_below_75")
                    if review["scores"]["accessibility"] < 3 or review["scores"]["brand_fidelity"] < 3:
                        reasons.append("accessibility_or_brand_below_3")
                    if run is not None and (review["cost_usd"] is None or
                                            review["cost_usd"] != run["declaration"]["cost_usd"]):
                        reasons.append("review_cost_missing_or_inconsistent")
            row["status"] = "eligible_for_human_selection" if not reasons else "not_eligible"
            rows.append(row)
        # Identical light captures under multiple candidate labels are suspicious,
        # and a local smoke fixture must never masquerade as three external runs.
        hashes: dict[str, list[str]] = {}
        for cid, hash_value in candidate_screenshots.items():
            hashes.setdefault(hash_value, []).append(cid)
        duplicates = [group for group in hashes.values() if len(group) > 1]
        if duplicates:
            for row in rows:
                if any(row["candidate"] in group for group in duplicates):
                    row["reasons"].append("identical_screenshot_across_candidates")
                    row["status"] = "not_eligible"
        qualified = [x for x in rows if x["status"] == "eligible_for_human_selection"]
        complete = all("missing_real_run" not in r["reasons"]
                       and "missing_browser_capture" not in r["reasons"]
                       and "missing_human_review" not in r["reasons"] for r in rows)
        if not complete:
            status, recommended = "hold_missing_evidence", None
        elif duplicates:
            status, recommended = "hold_duplicate_visual_evidence", None
        elif not qualified:
            status, recommended = "hold_no_eligible_candidate", None
        else:
            ordered = sorted(qualified, key=lambda r: (-r["score_percent"], r["cost_usd"], r["candidate"]))
            if len(ordered) == 1:
                recommended = ordered[0]["candidate"]
            else:
                leader, second = ordered[:2]
                advantage = leader["score_percent"] - second["score_percent"]
                # Difference smaller than 5 points demands explicit human tradeoff.
                # Even a clear quality winner is not recommended automatically when
                # its cost is higher than the next candidate.
                recommended = leader["candidate"] if (
                    advantage >= 5 and leader["cost_usd"] <= second["cost_usd"]
                ) else None
            status = "ready_for_human_selection" if recommended else "human_tradeoff_required"
        output = {
            "schema": REPORT_SCHEMA, "experiment": exp, "plan_sha256": digest,
            "status": status, "recommendation": recommended,
            "candidates": rows, "complete": complete,
            "quality_floor": _PASS_SCORE, "score_gap_for_recommendation": 5.0,
            "license_and_release_approved": False, "model_authorship_verified": False,
            "limitations": [
                "Run logs, model/provider identity, commit IDs and costs are operator assertions, not authenticated provider receipts.",
                "The automated DOM audit is a smoke check and cannot certify WCAG compliance.",
                "Screenshot provenance ties the served entrypoint HTML to a local build hash, but is not a signed build attestation.",
                "Human review in this lab is not an authenticated Human Control Lease.",
                "All selections remain prototype preferences, never production deployment authority.",
            ],
        }
        return output

    def seal(self, exp: str) -> dict[str, Any]:
        report = self.evaluate(exp)
        folder, _, _ = self.lab._experiment(exp)
        digest = _sha(_canonical(report))
        path = folder / "decisions" / "reports" / (digest + ".json")
        created = _write_immutable(path, _canonical({"sha256": digest, "data": report}) + b"\n")
        if created:
            self.store.append_event(Event(
                type="design.bakeoff.quality.report.sealed",
                subject={"experiment": exp, "status": report["status"], "report_sha256": digest},
            ))
        return {"status": "created" if created else "existing", "decision_status": report["status"],
                "recommended": report["recommendation"], "sha256": digest, "path": str(path)}

    def select(self, exp: str, *, candidate: str, actor: str, note: str) -> dict[str, Any]:
        report = self.evaluate(exp)
        if report["status"] not in ("ready_for_human_selection", "human_tradeoff_required"):
            raise QualityGateError("No complete, eligible real UI evidence for human preference")
        if candidate not in [r["candidate"] for r in report["candidates"]
                             if r["status"] == "eligible_for_human_selection"]:
            raise QualityGateError("Human selection must name a currently eligible candidate")
        if not isinstance(actor, str) or not _ACTOR_RE.fullmatch(actor):
            raise QualityGateError("Human reviewer label must use human:<id>")
        if not isinstance(note, str) or not 24 <= len(note.strip()) <= 2000:
            raise QualityGateError("Human preference requires a meaningful explanatory note")
        sealed = self.seal(exp)
        folder, _, _ = self.lab._experiment(exp)
        data = {"schema": CHOICE_SCHEMA, "experiment": exp,
                "quality_report_sha256": sealed["sha256"], "candidate": candidate,
                "actor": actor, "note": note.strip(), "status": "human_preference_only",
                "authenticated": False, "release_approved": False}
        path = folder / "decisions" / "human-selection.json"
        created = _write_immutable(path, _canonical({"sha256": _sha(_canonical(data)), "data": data}) + b"\n")
        if created:
            self.store.append_event(Event(
                type="design.bakeoff.quality.human_preference",
                actor=actor, subject={"experiment": exp, "candidate": candidate,
                                      "report_sha256": sealed["sha256"], "release_approved": False},
            ))
        return {"status": "recorded" if created else "existing", "candidate": candidate,
                "path": str(path), "release_approved": False}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Real candidate build evidence and non-authorizing design decision gate")
    p.add_argument("--root", default=".")
    sub = p.add_subparsers(dest="command", required=True)
    enroll = sub.add_parser("intake")
    enroll.add_argument("experiment")
    enroll.add_argument("candidate")
    enroll.add_argument("--declaration", type=Path, required=True)
    enroll.add_argument("--bundle", type=Path, required=True)
    enroll.add_argument("--trace", type=Path, required=True)
    verify = sub.add_parser("verify-run")
    verify.add_argument("experiment")
    verify.add_argument("candidate")
    capture = sub.add_parser("capture-local")
    capture.add_argument("experiment")
    capture.add_argument("candidate")
    capture.add_argument("--browser-channel", choices=("chrome", "chromium", "msedge"))
    capture.add_argument("--browser-executable")
    capture.add_argument("--timeout-ms", type=int, default=30000)
    report = sub.add_parser("report")
    report.add_argument("experiment")
    seal = sub.add_parser("seal")
    seal.add_argument("experiment")
    choice = sub.add_parser("select")
    choice.add_argument("experiment")
    choice.add_argument("--candidate", required=True)
    choice.add_argument("--actor", required=True)
    choice.add_argument("--note", required=True)
    args = p.parse_args(argv)
    try:
        gate = RealUIDecisionGate(args.root)
        if args.command == "intake":
            result = gate.intake(args.experiment, args.candidate,
                                 declaration_file=args.declaration,
                                 bundle=args.bundle, trace_file=args.trace)
        elif args.command == "verify-run":
            data, digest = gate.verify_run(args.experiment, args.candidate)
            result = {"status": "verified_operator_attestation", "sha256": digest, "run": data}
        elif args.command == "capture-local":
            result = gate.capture_local(args.experiment, args.candidate,
                                        browser_channel=args.browser_channel,
                                        browser_executable=args.browser_executable,
                                        timeout_ms=args.timeout_ms)
        elif args.command == "report":
            result = gate.evaluate(args.experiment)
        elif args.command == "seal":
            result = gate.seal(args.experiment)
        else:
            result = gate.select(args.experiment, candidate=args.candidate,
                                 actor=args.actor, note=args.note)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (QualityGateError, DesignLabError, BakeoffError, OSError, ValueError, KeyError, TypeError) as exc:
        p.exit(2, f"real ui decision: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
