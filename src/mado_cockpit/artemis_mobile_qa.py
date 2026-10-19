"""MCC-M2.9: fail-closed, offline-first Artemis Android QA evidence bridge.

No Artemis dependency, device access or network calls at import time.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_MEDIA = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
MAX_BYTES = 100 * 1024 * 1024


class MobileQAGateError(ValueError):
    """Missing, unsafe, or unverified mobile QA evidence."""


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise MobileQAGateError(f"invalid {label}")
    return value


def android_doctor(*, adb: str = "adb") -> dict[str, Any]:
    """Read-only Windows-compatible device probe; never starts an emulator."""
    try:
        proc = subprocess.run(
            [adb, "devices", "-l"], capture_output=True, text=True,
            timeout=12, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "blocked", "reason": type(exc).__name__, "devices": []}
    if proc.returncode:
        return {"status": "blocked", "reason": "adb_failed", "devices": []}
    devices = []
    for line in proc.stdout.splitlines()[1:]:
        columns = line.split()
        if len(columns) >= 2 and not line.startswith("*"):
            devices.append({"serial": columns[0], "state": columns[1],
                            "emulator": columns[0].startswith("emulator-")})
    ready = [d for d in devices if d["state"] == "device" and d["emulator"]]
    return {"status": "ready" if ready else "blocked",
            "reason": None if ready else "no_ready_emulator",
            "devices": devices}


def codex_mcp_config(artemis_root: str | Path) -> str:
    """Generate rather than install MCP configuration; users opt in explicitly."""
    root = Path(artemis_root).expanduser().resolve()
    python = root / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    def quoted(value: str) -> str:
        return json.dumps(value)
    return ("[mcp_servers.artemis]\n"
            f"command = {quoted(str(python))}\n"
            'args = ["-m", "mcp_server"]\n'
            f"cwd = {quoted(str(root))}\n\n"
            "[mcp_servers.artemis.env]\n"
            'PYTHONUNBUFFERED = "1"\n'
            f"PYTHONPATH = {quoted(str(root))}\n")


def _inside(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or Path(name).is_absolute():
        raise MobileQAGateError("evidence path must be relative")
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise MobileQAGateError("evidence missing or outside session directory")
    if path.is_symlink():
        raise MobileQAGateError("symlink evidence is forbidden")
    return path


def intake_mobile_evidence(
    session_dir: str | Path, output_dir: str | Path, *, require_live: bool = True,
) -> dict[str, Any]:
    """Validate a producer-supplied manifest, copy media, hash, and write verdict.

    Manifest contract: schema_version=1, run_id, device_serial, status,
    source (artemis_live or synthetic_fixture), steps, media [{path, kind}],
    trace_id. An error/fixture can never be represented as passing live QA.
    """
    source_root = Path(session_dir).resolve()
    output_root = Path(output_dir).resolve()
    if output_root == source_root or source_root in output_root.parents:
        raise MobileQAGateError("output must not overlap evidence source")
    manifest_file = _inside(source_root, "manifest.json")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise MobileQAGateError("schema_version must be 1")
    run_id = _identifier(manifest.get("run_id"), "run_id")
    serial = _identifier(manifest.get("device_serial"), "device_serial")
    source = manifest.get("source")
    status = manifest.get("status")
    if source not in {"artemis_live", "synthetic_fixture"}:
        raise MobileQAGateError("invalid source")
    if status not in {"passed", "failed", "blocked"}:
        raise MobileQAGateError("invalid status")
    trace = manifest.get("trace_id")
    if not isinstance(trace, str) or not trace.strip():
        raise MobileQAGateError("trace_id is required")
    steps = manifest.get("steps")
    if not isinstance(steps, list) or not steps or not all(
        isinstance(s, dict) and isinstance(s.get("action"), str)
        and isinstance(s.get("result"), str)
        and s["result"] in {"passed", "failed", "blocked"} for s in steps
    ):
        raise MobileQAGateError("steps must contain action and result")
    media = manifest.get("media")
    if not isinstance(media, list) or not media:
        raise MobileQAGateError("at least one screenshot or video is required")
    if len(media) > 100:
        raise MobileQAGateError("too many media files")
    checked = []
    seen = set()
    for item in media:
        if not isinstance(item, dict) or item.get("kind") not in {"screenshot", "video"}:
            raise MobileQAGateError("invalid media entry")
        name = item.get("path")
        if name in seen:
            raise MobileQAGateError("duplicate media path")
        seen.add(name)
        path = _inside(source_root, name)
        if path.suffix.lower() not in SUPPORTED_MEDIA:
            raise MobileQAGateError("unsupported media extension")
        if not 0 < path.stat().st_size <= MAX_BYTES:
            raise MobileQAGateError("empty or oversized evidence")
        checked.append((name, path, item["kind"]))
    live = source == "artemis_live" and serial.startswith("emulator-")
    verified = (live if require_live else True) and status == "passed" and all(
        step["result"] == "passed" for step in steps
    )
    verdict = "passed" if verified else "blocked" if status == "blocked" or (
        require_live and not live
    ) else "failed"
    target = output_root / run_id
    if target.exists():
        raise MobileQAGateError("run output already exists; refusing overwrite")
    target.mkdir(parents=True, exist_ok=False)
    try:
        output_media = []
        for name, original, kind in checked:
            dest = target / "media" / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, dest)
            output_media.append({
                "path": str(dest.relative_to(target)).replace("\\", "/"),
                "kind": kind,
                "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                "bytes": dest.stat().st_size,
            })
        report = {
            "schema_version": 1, "run_id": run_id, "device_serial": serial,
            "source": source, "trace_id": trace, "producer_status": status,
            "gate": verdict, "live_qualified": live, "steps": steps,
            "media": output_media,
            "mgsf_evidence_class": (
                "recorded_gameplay_capture" if live else "synthetic_capture_fixture"
            ),
        }
        (target / "mobile-qa-report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except BaseException:
        shutil.rmtree(target)
        raise
    return report
