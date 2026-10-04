from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from .models import Mission, Project
from .operator import OperatorManager
from .opendots_dogfood import (
    OpenDotsDogfoodError,
    OpenDotsDogfoodHarness,
)
from .store import CockpitStore


HARNESS_VERSION = "MCC-M1.6"
SCHEMA = "mado.opendots.browser-e2e.v1"
APP_TS_SHA = "fc9bae5454b509ce325a2e76a9ea1308e7347cdd"

E2E_OVERLAY = (
    (
        "integrations/opendots/e2e/src/server/mado-dogfood-routes.ts",
        "src/server/mado-dogfood-routes.ts",
    ),
    (
        "integrations/opendots/e2e/src/client/MadoDogfoodPage.tsx",
        "src/client/MadoDogfoodPage.tsx",
    ),
    (
        "integrations/opendots/e2e/scripts/mado-browser-e2e.ts",
        "scripts/mado-browser-e2e.ts",
    ),
)


class OpenDotsBrowserE2E:
    def __init__(
        self,
        cockpit_root: Path,
        opendots_root: Path,
        *,
        allow_drift: bool = False,
    ) -> None:
        self.cockpit_root = cockpit_root.resolve()
        self.opendots_root = opendots_root.resolve()
        self.allow_drift = allow_drift
        self.base = OpenDotsDogfoodHarness(
            self.cockpit_root,
            self.opendots_root,
            allow_drift=allow_drift,
        )

    def preflight(self) -> dict[str, Any]:
        base = self.base.preflight()
        app_path = self.opendots_root / "src/server/app.ts"
        if not app_path.is_file():
            raise OpenDotsDogfoodError(
                f"OpenDots app.ts not found: {app_path}"
            )
        actual = self._git_blob_sha(app_path)
        drift = actual != APP_TS_SHA
        if drift and not self.allow_drift:
            raise OpenDotsDogfoodError(
                "OpenDots browser-E2E drift detected for src/server/app.ts: "
                f"expected {APP_TS_SHA}, got {actual}"
            )
        return {
            "base": base,
            "app_ts": {
                "expected": APP_TS_SHA,
                "actual": actual,
                "drift": drift,
            },
        }

    def apply(self) -> dict[str, Any]:
        preflight = self.preflight()
        base = self.base.apply()
        changed: list[str] = []

        for source_rel, target_rel in E2E_OVERLAY:
            source = self.cockpit_root / source_rel
            target = self.opendots_root / target_rel
            if not source.is_file():
                raise OpenDotsDogfoodError(
                    f"M1.6 overlay source is missing: {source}"
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            payload = source.read_bytes()
            if not target.exists() or target.read_bytes() != payload:
                target.write_bytes(payload)
                changed.append(target_rel)

        if self._patch_app():
            changed.append("src/server/app.ts")
        if self._patch_main():
            changed.append("src/client/main.tsx")

        return {
            "preflight": preflight,
            "base_apply": base,
            "changed": changed,
        }

    def create_fixture(self) -> dict[str, str]:
        store = CockpitStore(self.cockpit_root)
        if not store.project_file.exists():
            store.init(
                Project(
                    id="mcc-m1.6-browser-e2e",
                    name="MCC-M1.6 Browser E2E",
                    root=str(self.cockpit_root),
                )
            )
        mission_id = f"MCC-M1.6-E2E-{uuid4().hex[:8]}"
        store.save_mission(
            Mission(
                id=mission_id,
                title="OpenDots Browser E2E",
            )
        )
        manager = OperatorManager(store)
        started = manager.start(
            mission_id,
            "Exercise the OpenDots Human Gate browser clickthrough.",
            required_evidence=["test_result"],
        )
        operator_id = str(started["plan"]["id"])
        requested = manager.request_gate(
            operator_id,
            question="Enable the paid provider for this run?",
            reason="The paid provider may create charges.",
            materiality="cost",
            choices=["stay_free", "enable_paid"],
            impacts={
                "stay_free": "Continue without provider charges.",
                "enable_paid": "May create provider charges.",
            },
            recommendation="stay_free",
            safe_default="stay_free",
        )
        gate_id = str(requested["gate"]["gate"]["id"])
        view = requested["operator"]
        if view["state"]["status"] != "awaiting_human":
            raise OpenDotsDogfoodError(
                "Browser fixture did not enter awaiting_human."
            )
        return {
            "mission_id": mission_id,
            "operator_id": operator_id,
            "gate_id": gate_id,
        }

    def assert_resolved(self, operator_id: str) -> dict[str, Any]:
        view = OperatorManager(
            CockpitStore(self.cockpit_root)
        ).inspect(operator_id)
        if view["state"]["status"] != "awaiting_builder":
            raise OpenDotsDogfoodError(
                "Expected browser fixture to resume at awaiting_builder, "
                f"got {view['state']['status']!r}"
            )
        if view["human_gate"] is not None:
            raise OpenDotsDogfoodError(
                "Expected Human Gate to be cleared after clickthrough."
            )
        return {
            "operator_id": operator_id,
            "status": view["state"]["status"],
            "human_gate": None,
            "next_action": view["next_action"],
        }

    def _patch_app(self) -> bool:
        path = self.opendots_root / "src/server/app.ts"
        text = path.read_text(encoding="utf-8")
        original = text

        if "MADO_COCKPIT_M1_6_DOGFOOD_ROUTE_IMPORT" not in text:
            anchor = "import { workspaceRoutes } from './workspace-routes.js';"
            addition = (
                "\n"
                "// MADO_COCKPIT_M1_6_DOGFOOD_ROUTE_IMPORT\n"
                "import { madoDogfoodRoutes } "
                "from './mado-dogfood-routes.js';"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "app dogfood route import",
            )

        if "// MADO_COCKPIT_M1_6_DOGFOOD_ROUTE\n" not in text:
            anchor = (
                "  if (platform && voice) "
                "app.route('/api', workspaceRoutes(platform, voice));"
            )
            addition = (
                "\n"
                "  // MADO_COCKPIT_M1_6_DOGFOOD_ROUTE\n"
                "  if (process.env.MADO_COCKPIT_E2E === '1')\n"
                "    app.route('/api/mado-dogfood', madoDogfoodRoutes());"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "app dogfood route registration",
            )

        if text != original:
            path.write_text(text, encoding="utf-8")
            return True
        return False

    def _patch_main(self) -> bool:
        path = self.opendots_root / "src/client/main.tsx"
        text = path.read_text(encoding="utf-8")
        original = text

        if "MADO_COCKPIT_M1_6_DOGFOOD_PAGE_IMPORT" not in text:
            anchor = "import { App } from './App';"
            addition = (
                "\n"
                "// MADO_COCKPIT_M1_6_DOGFOOD_PAGE_IMPORT\n"
                "import { MadoDogfoodPage } from './MadoDogfoodPage';"
            )
            text = self._insert_after(
                text,
                anchor,
                addition,
                "main dogfood page import",
            )

        if "// MADO_COCKPIT_M1_6_DOGFOOD_PAGE\n" not in text:
            old = """createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
"""
            new = """// MADO_COCKPIT_M1_6_DOGFOOD_PAGE
createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {location.pathname === '/mado-dogfood' ? <MadoDogfoodPage /> : <App />}
  </React.StrictMode>,
);
"""
            text = self._replace_once(
                text,
                old,
                new,
                "main dogfood page switch",
            )

        if text != original:
            path.write_text(text, encoding="utf-8")
            return True
        return False

    def _git_blob_sha(self, path: Path) -> str:
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.opendots_root),
                "hash-object",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        payload = path.read_bytes()
        header = f"blob {len(payload)}\0".encode()
        return hashlib.sha1(header + payload).hexdigest()

    @staticmethod
    def _insert_after(
        text: str,
        anchor: str,
        addition: str,
        label: str,
    ) -> str:
        count = text.count(anchor)
        if count != 1:
            raise OpenDotsDogfoodError(
                f"{label} anchor expected once, found {count}"
            )
        return text.replace(anchor, anchor + addition, 1)

    @staticmethod
    def _replace_once(
        text: str,
        old: str,
        new: str,
        label: str,
    ) -> str:
        count = text.count(old)
        if count != 1:
            raise OpenDotsDogfoodError(
                f"{label} anchor expected once, found {count}"
            )
        return text.replace(old, new, 1)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mado_cockpit.opendots_browser_e2e"
    )
    parser.add_argument("--opendots-root", required=True)
    parser.add_argument(
        "--cockpit-root",
        default=str(_repo_root()),
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--allow-drift", action="store_true")
    parser.add_argument("--assert-resolved")
    args = parser.parse_args(argv)

    harness = OpenDotsBrowserE2E(
        Path(args.cockpit_root),
        Path(args.opendots_root),
        allow_drift=args.allow_drift,
    )
    try:
        apply_result = (
            harness.apply()
            if args.apply
            else {"preflight": harness.preflight(), "changed": []}
        )
        fixture = harness.create_fixture() if args.fixture else None
        resolved = (
            harness.assert_resolved(args.assert_resolved)
            if args.assert_resolved
            else None
        )
    except OpenDotsDogfoodError as exc:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "harness_version": HARNESS_VERSION,
                    "ok": False,
                    "error": str(exc),
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            {
                "schema": SCHEMA,
                "harness_version": HARNESS_VERSION,
                "ok": True,
                "apply": apply_result,
                "fixture": fixture,
                "resolved": resolved,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
