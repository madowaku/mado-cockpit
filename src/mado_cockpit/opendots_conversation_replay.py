from __future__ import annotations

import argparse
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


HARNESS_VERSION = "MCC-M1.7"
SCHEMA = "mado.opendots.conversation-replay-harness.v1"
REPLAY_SOURCE = (
    "integrations/opendots/replay/scripts/"
    "mado-conversation-replay.ts"
)
REPLAY_TARGET = "scripts/mado-conversation-replay.ts"


class OpenDotsConversationReplay:
    def __init__(
        self,
        cockpit_root: Path,
        opendots_root: Path,
        *,
        allow_drift: bool = False,
    ) -> None:
        self.cockpit_root = cockpit_root.resolve()
        self.opendots_root = opendots_root.resolve()
        self.base = OpenDotsDogfoodHarness(
            self.cockpit_root,
            self.opendots_root,
            allow_drift=allow_drift,
        )

    def apply(self) -> dict[str, Any]:
        base = self.base.apply()
        source = self.cockpit_root / REPLAY_SOURCE
        target = self.opendots_root / REPLAY_TARGET
        if not source.is_file():
            raise OpenDotsDogfoodError(
                f"M1.7 replay source is missing: {source}"
            )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = source.read_bytes()
        changed = False
        if not target.exists() or target.read_bytes() != payload:
            target.write_bytes(payload)
            changed = True
        return {
            "base_apply": base,
            "replay_changed": changed,
            "replay_target": REPLAY_TARGET,
        }

    def create_fixture(self) -> dict[str, str]:
        store = CockpitStore(self.cockpit_root)
        if not store.project_file.exists():
            store.init(
                Project(
                    id="mcc-m1.7-conversation-replay",
                    name="MCC-M1.7 Conversation Replay",
                    root=str(self.cockpit_root),
                )
            )
        mission_id = f"MCC-M1.7-REPLAY-{uuid4().hex[:8]}"
        store.save_mission(
            Mission(
                id=mission_id,
                title="OpenDots Real Conversation Replay",
            )
        )
        manager = OperatorManager(store)
        run = manager.start(
            mission_id,
            "Replay a real OpenDots conversation through the MADO Human Gate.",
            required_evidence=["test_result"],
        )
        operator_id = str(run["plan"]["id"])
        gate = manager.request_gate(
            operator_id,
            question="Enable the paid provider for this replay?",
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
        gate_id = str(gate["gate"]["gate"]["id"])
        if gate["operator"]["state"]["status"] != "awaiting_human":
            raise OpenDotsDogfoodError(
                "M1.7 fixture did not enter awaiting_human."
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
                "Expected replay to resume at awaiting_builder, "
                f"got {view['state']['status']!r}"
            )
        if view["human_gate"] is not None:
            raise OpenDotsDogfoodError(
                "Expected replay Human Gate to be cleared."
            )
        return {
            "operator_id": operator_id,
            "status": view["state"]["status"],
            "human_gate": None,
            "next_action": view["next_action"],
        }


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mado_cockpit.opendots_conversation_replay"
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

    harness = OpenDotsConversationReplay(
        Path(args.cockpit_root),
        Path(args.opendots_root),
        allow_drift=args.allow_drift,
    )
    try:
        applied = (
            harness.apply()
            if args.apply
            else {"preflight": harness.base.preflight()}
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
