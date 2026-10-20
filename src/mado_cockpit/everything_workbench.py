"""MCC-M2.9: evidence-first, isolated HeyPuter Everything workbench.

No cloning, package installation or network access occurs automatically.
Third-party apps never run until a human explicitly invokes a local probe.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "mado.everything-workbench.v1"
SOURCE = "https://github.com/HeyPuter/everything"
# License assertions are only intake hints, never permission to redistribute.
APPS = {
    "photo-studio": {"path": "src/photo-studio", "license": "MIT", "node": ">=22.12", "lane": "MAF", "commands": [["npm", "test"], ["npm", "run", "build"]]},
    "3d": {"path": "src/3d", "license": "MIT", "node": "24 LTS", "lane": "MGSF", "commands": [["npm", "test"], ["npm", "run", "build"], ["npm", "run", "test:e2e"]]},
    "video-studio": {"path": "src/video-studio", "license": "AGPL-3.0-only", "node": ">=22.12", "lane": "MAF", "commands": [["npm", "test"], ["npm", "run", "build"]]},
    "whiteboard": {"path": "src/whiteboard", "license": "AGPL-3.0-only", "node": ">=22.12", "lane": "MCC", "commands": [["npm", "test"], ["npm", "run", "build"]]},
}
MAX_OUTPUT = 12000


class IntakeError(ValueError):
    pass


def catalog() -> dict:
    return {"schema": SCHEMA, "source": SOURCE, "apps": [{"id": key, **value, "status": "candidate_unverified"} for key, value in APPS.items()]}


def _inside(root: Path, path: Path) -> bool:
    return path.is_relative_to(root)


def inspect(checkout: Path, app_id: str) -> dict:
    if app_id not in APPS:
        raise IntakeError("Unknown app")
    if checkout.is_symlink() or not checkout.is_dir():
        raise IntakeError("Checkout must be a real directory")
    root = checkout.resolve(strict=True)
    app = root / APPS[app_id]["path"]
    if not app.is_dir() or app.is_symlink() or not _inside(root, app.resolve()):
        raise IntakeError("Missing or escaping app directory")
    files = {}
    for name in ("package.json", "LICENSE", "README.md"):
        path = app / name
        if not path.is_file() or path.is_symlink() or not _inside(root, path.resolve()):
            raise IntakeError("Missing or unsafe " + name)
        data = path.read_bytes()
        if len(data) > 2_000_000:
            raise IntakeError("Oversize file: " + name)
        files[name] = hashlib.sha256(data).hexdigest()
    meta = json.loads((app / "package.json").read_text(encoding="utf-8"))
    declared = meta.get("license", "not declared in package.json")
    license_text = (app / "LICENSE").read_text(encoding="utf-8", errors="replace")
    expected = APPS[app_id]["license"]
    marker = "MIT License" if expected == "MIT" else "GNU AFFERO GENERAL PUBLIC LICENSE"
    license_ok = marker in license_text and (declared in (expected, "not declared in package.json"))
    return {"schema": SCHEMA, "app": app_id, "lane": APPS[app_id]["lane"], "source": SOURCE,
            "checkout": str(root), "files_sha256": files, "declared_license": declared,
            "expected_license": expected, "license_check": "pass" if license_ok else "needs_review",
            "status": "inspected_not_executed"}


def probe(checkout: Path, app_id: str, *, approve_execution: bool = False,
          command_index: int = 0, timeout: int = 180) -> dict:
    snapshot = inspect(checkout, app_id)
    if not approve_execution:
        raise IntakeError("Execution requires --approve-execution")
    if snapshot["license_check"] != "pass":
        raise IntakeError("License gate requires review")
    commands = APPS[app_id]["commands"]
    if not 0 <= command_index < len(commands):
        raise IntakeError("Unknown command index")
    if not 1 <= timeout <= 900:
        raise IntakeError("Timeout must be between 1 and 900 seconds")
    app = Path(snapshot["checkout"]) / APPS[app_id]["path"]
    if not (app / "node_modules").is_dir():
        raise IntakeError("Dependencies not installed. Install separately inside a disposable sandbox.")
    argv = commands[command_index]
    env = {key: value for key, value in os.environ.items() if key in ("PATH", "HOME", "USERPROFILE", "SystemRoot", "TEMP", "TMP", "TMPDIR")}
    env.update({"CI": "1", "NO_COLOR": "1"})
    try:
        result = subprocess.run(argv, cwd=app, env=env, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=timeout, check=False)
        evidence = {"status": "pass" if result.returncode == 0 else "fail",
                    "returncode": result.returncode,
                    "stdout_tail": result.stdout[-MAX_OUTPUT:], "stderr_tail": result.stderr[-MAX_OUTPUT:]}
    except subprocess.TimeoutExpired:
        evidence = {"status": "timeout", "returncode": None, "stdout_tail": "", "stderr_tail": ""}
    return {**snapshot, "status": "probe_completed", "command": argv,
            "recorded_at": datetime.now(timezone.utc).isoformat(), "evidence": evidence,
            "visual_evidence": "not_captured", "production_approved": False}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Everything OSS isolated intake")
    parser.add_argument("action", choices=["catalog", "inspect", "probe"])
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--app", choices=sorted(APPS))
    parser.add_argument("--approve-execution", action="store_true")
    parser.add_argument("--command-index", type=int, default=0)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "catalog":
            data = catalog()
        else:
            if args.checkout is None or args.app is None:
                raise IntakeError("--checkout and --app are required")
            data = (inspect(args.checkout, args.app) if args.action == "inspect" else
                    probe(args.checkout, args.app, approve_execution=args.approve_execution,
                          command_index=args.command_index, timeout=args.timeout))
    except (IntakeError, OSError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    rendered = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
