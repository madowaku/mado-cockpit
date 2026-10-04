from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from mado_cockpit.action_gateway import (
    ActionPolicy,
    ActionRule,
    mado_internal_action_policy,
)
from mado_cockpit.models import (
    Mission,
    Project,
)
from mado_cockpit.opendots_tools import (
    TOOL_CALL_SCHEMA,
    OpenDotsToolSurface,
)
from mado_cockpit.operator import (
    OperatorManager,
)
from mado_cockpit.store import (
    CockpitStore,
)


SMOKE_VERSION = "MCC-M2.3"


def _git_fixture(root: Path) -> None:
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
            "m2.3@example.test",
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
            "MCC M2.3",
        ],
        check=True,
    )
    (root / "README.md").write_text(
        "MCC-M2.3 fixture\n",
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


def _call(
    *,
    operator_id: str,
    tool_call_id: str,
    thread_id: str,
) -> dict[str, object]:
    return {
        "schema": TOOL_CALL_SCHEMA,
        "tool_call_id": tool_call_id,
        "tool_name": (
            "mado_advance_mission"
        ),
        "context": {
            "dot_id": "scout",
            "space_id": "space-m2.3",
            "thread_id": thread_id,
        },
        "arguments": {
            "operator_id": operator_id,
        },
    }


def _receipt_by_call_order(
    store: CockpitStore,
) -> list[dict[str, object]]:
    receipts = [
        json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
        for path in (
            store.base
            / "action_decisions"
        ).glob("*.json")
    ]
    return sorted(
        receipts,
        key=lambda item: str(
            item["recorded_at"]
        ),
    )


def run(root: Path) -> dict[str, object]:
    _git_fixture(root)
    store = CockpitStore(root)
    store.init(
        Project(
            id="mcc-m2.3-shadow",
            name="MCC-M2.3 Shadow",
            root=str(root),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M2.3-SHADOW",
            title=(
                "Policy Shadow and "
                "Action Equivalence"
            ),
        )
    )
    operator = OperatorManager(store)
    started = operator.start(
        "MCC-M2.3-SHADOW",
        (
            "Exercise policy shadow, "
            "equivalence fencing, and "
            "initiator context."
        ),
        required_evidence=[
            "test_result"
        ],
    )
    operator_id = str(
        started["plan"]["id"]
    )

    shadow_policy = ActionPolicy(
        deny=(
            ActionRule(
                id="shadow:deny-advance",
                predicate=lambda candidate: (
                    candidate.action
                    == "mado_advance_mission"
                ),
                reason=(
                    "Candidate policy would "
                    "deny deterministic advance."
                ),
            ),
        ),
    )
    shadow_surface = (
        OpenDotsToolSurface(
            store,
            shadow_action_policy=(
                shadow_policy
            ),
        )
    )
    shadow_result = shadow_surface.handle(
        _call(
            operator_id=operator_id,
            tool_call_id="m2.3-shadow-live",
            thread_id="thread-shadow",
        )
    )
    if shadow_result["ok"] is not True:
        raise RuntimeError(
            "Live action was incorrectly "
            "blocked by shadow policy."
        )

    refusing_surface = (
        OpenDotsToolSurface(
            store,
            action_policy=ActionPolicy(),
        )
    )
    refused = refusing_surface.handle(
        _call(
            operator_id=operator_id,
            tool_call_id="m2.3-refused-1",
            thread_id="thread-fence",
        )
    )
    if (
        refused["ok"] is not False
        or refused["error"]["code"]
        != "action_refused"
    ):
        raise RuntimeError(
            "Expected first fence action "
            "to be refused."
        )

    permissive_surface = (
        OpenDotsToolSurface(
            store,
            action_policy=(
                mado_internal_action_policy()
            ),
        )
    )
    fenced = permissive_surface.handle(
        _call(
            operator_id=operator_id,
            tool_call_id="m2.3-refused-2",
            thread_id="thread-fence",
        )
    )
    if (
        fenced["ok"] is not False
        or "equivalent action"
        not in fenced["error"]["message"]
    ):
        raise RuntimeError(
            "Equivalent retry was not fenced."
        )

    retry = permissive_surface.handle(
        _call(
            operator_id=operator_id,
            tool_call_id="m2.3-retry-new-context",
            thread_id="thread-retry",
        )
    )
    if retry["ok"] is not True:
        raise RuntimeError(
            "New initiator context did not "
            "permit intentional retry."
        )

    receipts = _receipt_by_call_order(
        store
    )
    if len(receipts) != 4:
        raise RuntimeError(
            "Expected four action decision "
            f"receipts, got {len(receipts)}."
        )

    shadow_receipt = next(
        item
        for item in receipts
        if item["fence_scope"]
        == (
            "chat:opendots:scout:"
            "thread-shadow"
        )
    )
    refused_receipt = next(
        item
        for item in receipts
        if (
            item["fence_scope"]
            == (
                "chat:opendots:scout:"
                "thread-fence"
            )
            and item["decision"][
                "source"
            ]
            == "default"
        )
    )
    fenced_receipt = next(
        item
        for item in receipts
        if item["decision"][
            "source"
        ]
        == "equivalent_fenced"
    )
    retry_receipt = next(
        item
        for item in receipts
        if item["fence_scope"]
        == (
            "chat:opendots:scout:"
            "thread-retry"
        )
    )

    if (
        shadow_receipt[
            "shadow_delta"
        ]
        != "would_deny"
        or shadow_receipt[
            "dispatch_status"
        ]
        != "dispatched"
    ):
        raise RuntimeError(
            "Shadow policy was not "
            "non-enforcing."
        )
    if (
        fenced_receipt[
            "equivalent_to_receipt_id"
        ]
        != refused_receipt["id"]
    ):
        raise RuntimeError(
            "Equivalent retry did not point "
            "to the refused receipt."
        )
    if (
        retry_receipt[
            "dispatch_status"
        ]
        != "dispatched"
    ):
        raise RuntimeError(
            "Intentional retry did not dispatch."
        )

    shadow_events = [
        event
        for event in store.list_events(
            limit=500
        )
        if event["type"]
        == "action.shadow.evaluated"
    ]
    if len(shadow_events) != 1:
        raise RuntimeError(
            "Expected one shadow event."
        )

    return {
        "schema": (
            "mado.policy-shadow-smoke.v1"
        ),
        "version": SMOKE_VERSION,
        "ok": True,
        "operator_id": operator_id,
        "shadow": {
            "receipt_id": (
                shadow_receipt["id"]
            ),
            "live_allowed": (
                shadow_receipt[
                    "decision"
                ]["allowed"]
            ),
            "shadow_allowed": (
                shadow_receipt[
                    "shadow_decision"
                ]["allowed"]
            ),
            "shadow_delta": (
                shadow_receipt[
                    "shadow_delta"
                ]
            ),
            "dispatch_status": (
                shadow_receipt[
                    "dispatch_status"
                ]
            ),
        },
        "equivalence": {
            "digest": (
                refused_receipt[
                    "equivalence_digest"
                ]
            ),
            "refused_receipt_id": (
                refused_receipt["id"]
            ),
            "fenced_receipt_id": (
                fenced_receipt["id"]
            ),
            "equivalent_to_receipt_id": (
                fenced_receipt[
                    "equivalent_to_receipt_id"
                ]
            ),
            "same_context_fenced": True,
            "new_context_dispatched": True,
        },
        "initiator": {
            "actor": (
                shadow_receipt[
                    "actor"
                ]
            ),
            "context": (
                shadow_receipt[
                    "initiator"
                ]
            ),
            "fence_scope": (
                shadow_receipt[
                    "fence_scope"
                ]
            ),
        },
        "shadow_event_count": len(
            shadow_events
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        required=True,
    )
    args = parser.parse_args()
    result = run(
        Path(args.root).resolve()
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
