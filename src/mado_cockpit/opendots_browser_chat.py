from __future__ import annotations

import argparse
import hashlib
import json
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


HARNESS_VERSION = "MCC-M1.9"
SCHEMA = "mado.opendots.browser-chat-harness.v1"
LOCK_PATH = (
    "fixtures/opendots/mcc-m1.9-upstream-lock.json"
)
OVERLAY = (
    (
        "integrations/opendots/chat-shim/src/server/"
        "mado-deterministic-chat-shim.ts",
        "src/server/mado-deterministic-chat-shim.ts",
    ),
    (
        "integrations/opendots/chat-shim/scripts/"
        "mado-browser-chat-e2e.ts",
        "scripts/mado-browser-chat-e2e.ts",
    ),
)


class OpenDotsBrowserChatHarness:
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
        self.lock = json.loads(
            (self.cockpit_root / LOCK_PATH).read_text(
                encoding="utf-8"
            )
        )

    def preflight(self) -> dict[str, Any]:
        base = self.base.preflight()
        drift = []
        for relative, expected in self.lock[
            "upstream"
        ]["locked_files"].items():
            path = self.opendots_root / relative
            if not path.is_file():
                drift.append(
                    {
                        "path": relative,
                        "expected": expected,
                        "actual": "missing",
                    }
                )
                continue
            if self._already_patched(
                relative,
                path,
            ):
                continue
            actual = self._git_blob_sha(path)
            if actual != expected:
                drift.append(
                    {
                        "path": relative,
                        "expected": expected,
                        "actual": actual,
                    }
                )
        if drift and not self.allow_drift:
            raise OpenDotsDogfoodError(
                "MCC-M1.9 upstream drift detected: "
                + "; ".join(
                    f"{item['path']} expected "
                    f"{item['expected']} got "
                    f"{item['actual']}"
                    for item in drift
                )
            )
        return {
            "base": base,
            "drift": drift,
        }

    def apply(self) -> dict[str, Any]:
        preflight = self.preflight()
        base = self.base.apply()
        changed: list[str] = []

        for source_rel, target_rel in OVERLAY:
            source = self.cockpit_root / source_rel
            target = self.opendots_root / target_rel
            if not source.is_file():
                raise OpenDotsDogfoodError(
                    f"MCC-M1.9 overlay source missing: {source}"
                )
            target.parent.mkdir(
                parents=True,
                exist_ok=True,
            )
            payload = source.read_bytes()
            if (
                not target.exists()
                or target.read_bytes() != payload
            ):
                target.write_bytes(payload)
                changed.append(target_rel)

        if self._patch_platform():
            changed.append(
                "src/server/platform.ts"
            )
        if self._patch_app():
            changed.append(
                "src/server/app.ts"
            )

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
                    id="mcc-m1.9-browser-chat",
                    name="MCC-M1.9 Browser Chat",
                    root=str(self.cockpit_root),
                )
            )
        mission_id = (
            "MCC-M1.9-CHAT-"
            + uuid4().hex[:8]
        )
        store.save_mission(
            Mission(
                id=mission_id,
                title="OpenDots Browser Chat",
            )
        )
        manager = OperatorManager(store)
        run = manager.start(
            mission_id,
            (
                "Exercise the normal OpenDots Chat composer "
                "through a deterministic local runtime."
            ),
            required_evidence=["test_result"],
        )
        operator_id = str(run["plan"]["id"])
        gate = manager.request_gate(
            operator_id,
            question=(
                "Enable the paid provider for this browser chat?"
            ),
            reason=(
                "The paid provider may create charges."
            ),
            materiality="cost",
            choices=[
                "stay_free",
                "enable_paid",
            ],
            impacts={
                "stay_free": (
                    "Continue without provider charges."
                ),
                "enable_paid": (
                    "May create provider charges."
                ),
            },
            recommendation="stay_free",
            safe_default="stay_free",
        )
        gate_id = str(
            gate["gate"]["gate"]["id"]
        )
        if (
            gate["operator"]["state"]["status"]
            != "awaiting_human"
        ):
            raise OpenDotsDogfoodError(
                "MCC-M1.9 fixture did not enter awaiting_human."
            )
        return {
            "mission_id": mission_id,
            "operator_id": operator_id,
            "gate_id": gate_id,
        }

    def assert_resolved(
        self,
        operator_id: str,
    ) -> dict[str, Any]:
        view = OperatorManager(
            CockpitStore(self.cockpit_root)
        ).inspect(operator_id)
        if (
            view["state"]["status"]
            != "awaiting_builder"
        ):
            raise OpenDotsDogfoodError(
                "Expected browser chat to resume at "
                "awaiting_builder, got "
                f"{view['state']['status']!r}"
            )
        if view["human_gate"] is not None:
            raise OpenDotsDogfoodError(
                "Expected browser chat Human Gate to be cleared."
            )
        return {
            "operator_id": operator_id,
            "status": view["state"]["status"],
            "human_gate": None,
            "next_action": view["next_action"],
        }

    def _patch_platform(self) -> bool:
        path = (
            self.opendots_root
            / "src/server/platform.ts"
        )
        text = path.read_text(
            encoding="utf-8"
        )
        original = text

        if (
            "// MADO_COCKPIT_M1_9_LOCAL_RUNTIME_HELPER\n"
            not in text
        ):
            text = self._insert_after(
                text,
                "import { learningSelector } from './learning.js';",
                (
                    "\n"
                    "// MADO_COCKPIT_M1_9_LOCAL_RUNTIME_HELPER\n"
                    "const madoDeterministicChat = () =>\n"
                    "  process.env.MADO_DETERMINISTIC_CHAT === '1';"
                ),
                "platform local runtime helper",
            )

        if (
            "// MADO_COCKPIT_M1_9_LOCAL_RUNTIME\n"
            not in text
        ):
            anchor = (
                "    if (!config.intelligenceKey) return;"
            )
            block = """    // MADO_COCKPIT_M1_9_LOCAL_RUNTIME
    if (madoDeterministicChat()) {
      const runtime = new CopilotRuntime({
        identifyUser: async () => ({
          id: workspace.ownerId,
          name: 'OpenDots owner',
        }),
        agents: async () =>
          Object.fromEntries(
            workspace
              .dots()
              .map((dot) => [
                dot.id,
                new DotAgent(store, workspace, config, dot.id),
              ]),
          ),
        generateThreadNames: false,
      });
      this.handler = createCopilotHonoHandler({
        runtime,
        basePath: '/api/copilotkit',
        cors: { origin: [] },
      });
      return;
    }
"""
            text = self._insert_before(
                text,
                anchor,
                block,
                "platform local runtime",
            )

        if (
            "// MADO_COCKPIT_M1_9_LOCAL_SETUP\n"
            not in text
        ):
            anchor = """  setup() {
    return setupStatus(
"""
            replacement = """  setup() {
    // MADO_COCKPIT_M1_9_LOCAL_SETUP
    if (madoDeterministicChat()) {
      const status = setupStatus(
        {
          ...this.config,
          intelligenceKey: 'mcc-m1.9-local-runtime',
        },
        'not_configured',
        false,
      );
      return {
        ...status,
        intelligence: false,
      };
    }
    return setupStatus(
"""
            text = self._replace_once(
                text,
                anchor,
                replacement,
                "platform setup shim",
            )

        if (
            "// MADO_COCKPIT_M1_9_LOCAL_CONVERSATION\n"
            not in text
        ):
            anchor = """    if (!this.workspace.dot(dotId)) throw new Error('Dot not found.');
    const id = randomUUID();
"""
            replacement = """    if (!this.workspace.dot(dotId)) throw new Error('Dot not found.');
    const id = randomUUID();
    // MADO_COCKPIT_M1_9_LOCAL_CONVERSATION
    if (madoDeterministicChat())
      return this.workspace.bindThread(id, dotId, title);
"""
            text = self._replace_once(
                text,
                anchor,
                replacement,
                "platform local conversation",
            )

        if (
            "// MADO_COCKPIT_M1_9_LOCAL_HISTORY\n"
            not in text
        ):
            anchor = """    this.requireReady();
    this.workspace.requireThread(threadId);
    const history = await this.intelligence!.getThreadMessages({
"""
            replacement = """    this.requireReady();
    this.workspace.requireThread(threadId);
    // MADO_COCKPIT_M1_9_LOCAL_HISTORY
    if (madoDeterministicChat()) return '';
    const history = await this.intelligence!.getThreadMessages({
"""
            text = self._replace_once(
                text,
                anchor,
                replacement,
                "platform local history",
            )

        if text != original:
            path.write_text(
                text,
                encoding="utf-8",
            )
            return True
        return False

    def _patch_app(self) -> bool:
        path = (
            self.opendots_root
            / "src/server/app.ts"
        )
        text = path.read_text(
            encoding="utf-8"
        )
        original = text

        if (
            "// MADO_COCKPIT_M1_9_SHIM_IMPORT\n"
            not in text
        ):
            text = self._insert_after(
                text,
                "import { workspaceRoutes } from './workspace-routes.js';",
                (
                    "\n"
                    "// MADO_COCKPIT_M1_9_SHIM_IMPORT\n"
                    "import { madoDeterministicChatShimRoutes } "
                    "from './mado-deterministic-chat-shim.js';"
                ),
                "app deterministic shim import",
            )

        if (
            "// MADO_COCKPIT_M1_9_SHIM_ROUTE\n"
            not in text
        ):
            anchor = (
                "  if (platform && voice) "
                "app.route('/api', workspaceRoutes(platform, voice));"
            )
            addition = """
  // MADO_COCKPIT_M1_9_SHIM_ROUTE
  if (process.env.MADO_DETERMINISTIC_CHAT === '1')
    app.route(
      '/api/mado-chat-shim',
      madoDeterministicChatShimRoutes(),
    );"""
            text = self._insert_after(
                text,
                anchor,
                addition,
                "app deterministic shim route",
            )

        if text != original:
            path.write_text(
                text,
                encoding="utf-8",
            )
            return True
        return False

    def _already_patched(
        self,
        relative: str,
        path: Path,
    ) -> bool:
        if not path.is_file():
            return False
        text = path.read_text(
            encoding="utf-8",
            errors="replace",
        )
        markers = {
            "src/server/platform.ts": (
                "MADO_COCKPIT_M1_9_LOCAL_RUNTIME"
            ),
            "src/server/app.ts": (
                "MADO_COCKPIT_M1_9_SHIM_ROUTE"
            ),
        }
        marker = markers.get(relative)
        return bool(
            marker
            and marker in text
        )

    def _git_blob_sha(
        self,
        path: Path,
    ) -> str:
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
        header = (
            f"blob {len(payload)}\0"
            .encode("utf-8")
        )
        return hashlib.sha1(
            header + payload
        ).hexdigest()

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
        return text.replace(
            anchor,
            anchor + addition,
            1,
        )

    @staticmethod
    def _insert_before(
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
        return text.replace(
            anchor,
            addition + anchor,
            1,
        )

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
        return text.replace(
            old,
            new,
            1,
        )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "mado_cockpit.opendots_browser_chat"
        )
    )
    parser.add_argument(
        "--opendots-root",
        required=True,
    )
    parser.add_argument(
        "--cockpit-root",
        default=str(_repo_root()),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
    )
    parser.add_argument(
        "--fixture",
        action="store_true",
    )
    parser.add_argument(
        "--allow-drift",
        action="store_true",
    )
    parser.add_argument(
        "--assert-resolved",
    )
    args = parser.parse_args(argv)

    harness = OpenDotsBrowserChatHarness(
        Path(args.cockpit_root),
        Path(args.opendots_root),
        allow_drift=args.allow_drift,
    )

    try:
        applied = (
            harness.apply()
            if args.apply
            else {
                "preflight": harness.preflight()
            }
        )
        fixture = (
            harness.create_fixture()
            if args.fixture
            else None
        )
        resolved = (
            harness.assert_resolved(
                args.assert_resolved
            )
            if args.assert_resolved
            else None
        )
    except OpenDotsDogfoodError as exc:
        print(
            json.dumps(
                {
                    "schema": SCHEMA,
                    "harness_version": (
                        HARNESS_VERSION
                    ),
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
                "harness_version": (
                    HARNESS_VERSION
                ),
                "ok": True,
                "apply": applied,
                "fixture": fixture,
                "resolved": resolved,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
