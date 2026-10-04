from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
from pathlib import Path

from mcp import Client

from mado_cockpit.models import (
    Mission,
    Project,
)
from mado_cockpit.operator import (
    OperatorManager,
)
from mado_cockpit.store import (
    CockpitStore,
)


def prepare(root: Path) -> dict[str, str]:
    root.mkdir(
        parents=True,
        exist_ok=True,
    )
    subprocess.run(
        [
            "git",
            "init",
            "-b",
            "main",
            str(root),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "config",
            "user.email",
            "m2.2@example.test",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "config",
            "user.name",
            "MCC M2.2",
        ],
        check=True,
    )
    (root / "README.md").write_text(
        "MCC-M2.2 fixture\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "add",
            "README.md",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    store = CockpitStore(root)
    store.init(
        Project(
            id="mcc-m2.2-http",
            name="MCC-M2.2 HTTP",
            root=str(root),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M2.2-HTTP",
            title=(
                "Action Policy Gateway "
                "HTTP Smoke"
            ),
        )
    )
    manager = OperatorManager(store)
    started = manager.start(
        "MCC-M2.2-HTTP",
        (
            "Prove MCP writes pass through "
            "the Action Policy Gateway."
        ),
        required_evidence=[
            "test_result"
        ],
    )
    operator_id = str(
        started["plan"]["id"]
    )
    gate = manager.request_gate(
        operator_id,
        question="Keep the zero-cost path?",
        reason=(
            "The alternate path may create "
            "provider charges."
        ),
        materiality="cost",
        choices=[
            "stay_free",
            "enable_paid",
        ],
        impacts={
            "stay_free": (
                "No provider charge."
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
    return {
        "root": str(root),
        "operator_id": operator_id,
        "gate_id": gate_id,
    }


async def smoke(
    *,
    root: Path,
    url: str,
    operator_id: str,
    gate_id: str,
) -> dict[str, object]:
    store = CockpitStore(root)

    before_receipts = list(
        (
            store.base
            / "action_decisions"
        ).glob("*.json")
    )
    if before_receipts:
        raise RuntimeError(
            "Fixture unexpectedly has "
            "pre-existing action receipts."
        )

    async with Client(url) as client:
        before = await client.call_tool(
            "mado_check_mission",
            {
                "operator_id": operator_id,
            },
        )
        if before.is_error:
            raise RuntimeError(
                "Initial mission read failed."
            )
        if (
            before.structured_content[
                "data"
            ]["status"]
            != "awaiting_human"
        ):
            raise RuntimeError(
                "Fixture is not awaiting_human."
            )

        resolved = await client.call_tool(
            "mado_answer_human_gate",
            {
                "operator_id": operator_id,
                "gate_id": gate_id,
                "choice": "stay_free",
                "choose_for_me": False,
            },
        )
        if resolved.is_error:
            raise RuntimeError(
                "Human Gate MCP write failed: "
                + "\n".join(
                    block.text
                    for block
                    in resolved.content
                    if hasattr(
                        block,
                        "text",
                    )
                )
            )

        after = await client.call_tool(
            "mado_check_mission",
            {
                "operator_id": operator_id,
            },
        )
        if after.is_error:
            raise RuntimeError(
                "Final mission read failed."
            )

    if (
        after.structured_content[
            "data"
        ]["status"]
        != "awaiting_builder"
    ):
        raise RuntimeError(
            "Cockpit did not resume at "
            "awaiting_builder."
        )

    receipt_paths = sorted(
        (
            store.base
            / "action_decisions"
        ).glob("*.json")
    )
    if len(receipt_paths) != 1:
        raise RuntimeError(
            "Expected exactly one governed "
            f"write receipt, got {len(receipt_paths)}."
        )
    receipt = json.loads(
        receipt_paths[0].read_text(
            encoding="utf-8"
        )
    )
    if (
        receipt["action"]
        != "mado_answer_human_gate"
        or receipt["decision"][
            "allowed"
        ]
        is not True
        or receipt["dispatch_status"]
        != "dispatched"
    ):
        raise RuntimeError(
            "Unexpected Action Policy receipt: "
            + json.dumps(receipt)
        )

    events = store.list_events(
        limit=500
    )
    decision_index = next(
        index
        for index, event
        in enumerate(events)
        if (
            event["type"]
            == "action.decision.recorded"
            and event["subject"][
                "receipt_id"
            ]
            == receipt["id"]
        )
    )
    dispatch_index = next(
        index
        for index, event
        in enumerate(events)
        if (
            event["type"]
            == "action.dispatched"
            and event["subject"][
                "receipt_id"
            ]
            == receipt["id"]
        )
    )
    if decision_index >= dispatch_index:
        raise RuntimeError(
            "Action decision was not recorded "
            "before dispatch."
        )

    return {
        "schema": (
            "mado.action-policy-http-smoke.v1"
        ),
        "version": "MCC-M2.2",
        "ok": True,
        "url": url,
        "operator_id": operator_id,
        "gate_id": gate_id,
        "choice": "stay_free",
        "final_status": (
            after.structured_content[
                "data"
            ]["status"]
        ),
        "receipt": {
            "id": receipt["id"],
            "action": receipt["action"],
            "decision": (
                receipt["decision"]
            ),
            "dispatch_status": (
                receipt[
                    "dispatch_status"
                ]
            ),
            "arguments_digest": (
                receipt[
                    "arguments_digest"
                ]
            ),
        },
        "decision_before_dispatch": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    prepare_parser = sub.add_parser(
        "prepare"
    )
    prepare_parser.add_argument(
        "--root",
        required=True,
    )

    smoke_parser = sub.add_parser(
        "smoke"
    )
    smoke_parser.add_argument(
        "--root",
        required=True,
    )
    smoke_parser.add_argument(
        "--url",
        default=(
            "http://127.0.0.1:8788/mcp"
        ),
    )
    smoke_parser.add_argument(
        "--operator-id",
        required=True,
    )
    smoke_parser.add_argument(
        "--gate-id",
        required=True,
    )

    args = parser.parse_args()

    if args.command == "prepare":
        result = prepare(
            Path(args.root).resolve()
        )
    else:
        result = asyncio.run(
            smoke(
                root=Path(
                    args.root
                ).resolve(),
                url=args.url,
                operator_id=(
                    args.operator_id
                ),
                gate_id=args.gate_id,
            )
        )

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
