import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.control import ControlPlaneBridge
from mado_cockpit.models import Project
from mado_cockpit.store import CockpitStore


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def init_repo(path: Path) -> None:
    git(path, "init", "-b", "main")
    git(
        path,
        "config",
        "user.email",
        "fixture@example.com",
    )
    git(
        path,
        "config",
        "user.name",
        "Fixture",
    )
    (path / ".gitignore").write_text(
        ".mado/\n",
        encoding="utf-8",
    )
    (path / "README.md").write_text(
        "fixture\n",
        encoding="utf-8",
    )
    git(path, "add", ".")
    git(path, "commit", "-m", "fixture")


def mission_envelope(
    *,
    mission_id: str = "MCC-M0.9",
    revision: str | None = None,
) -> dict:
    return {
        "schema_version": (
            "mado.mission-envelope.v1"
        ),
        "mission_id": mission_id,
        "title": "Space Control Plane Bridge",
        "objective": (
            "Connect control intent to Cockpit "
            "execution safely."
        ),
        "source": {
            "kind": "space",
            "space_id": "space-fixture",
            "page_id": "page-fixture",
            "revision": revision,
        },
        "priority": "normal",
        "constraints": [
            "Keep the bridge transport-neutral."
        ],
        "deliverables": [
            "Mission Envelope support",
            "Outcome Envelope support",
        ],
        "required_evidence": [
            "git_diff",
            "test_result",
        ],
        "human_decisions": [],
        "execution_policy": {
            "allow_paid": False,
            "allow_publish": False,
            "allow_delete": False,
            "allow_external_message": False,
        },
        "future_field": {
            "preserved": True,
        },
    }


def setup_bridge(
    tmp_path: Path,
) -> tuple[CockpitStore, ControlPlaneBridge]:
    init_repo(tmp_path)
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    return store, ControlPlaneBridge(store)


def test_receive_is_idempotent_and_preserves_unknown_metadata(
    tmp_path,
):
    _, bridge = setup_bridge(tmp_path)

    first = bridge.receive(mission_envelope())
    second = bridge.receive(mission_envelope())

    assert (
        first["status"]["envelope_id"]
        == second["status"]["envelope_id"]
    )
    assert (
        first["envelope"]["metadata"][
            "future_field"
        ]["preserved"]
        is True
    )
    assert (
        len(
            list(
                bridge.inbox_dir.glob(
                    "*/mission.json"
                )
            )
        )
        == 1
    )


def test_changed_mission_requires_new_revision(
    tmp_path,
):
    _, bridge = setup_bridge(tmp_path)
    bridge.receive(mission_envelope())

    changed = mission_envelope()
    changed["objective"] = "Changed objective"

    with pytest.raises(
        RuntimeError,
        match="requires source.revision",
    ):
        bridge.receive(changed)

    changed["source"]["revision"] = "2"
    accepted = bridge.receive(changed)
    assert (
        accepted["status"]["revision"]
        == "2"
    )

    collision = mission_envelope(
        revision="2"
    )
    collision["objective"] = "Another change"

    with pytest.raises(
        RuntimeError,
        match="revision already exists",
    ):
        bridge.receive(collision)


def test_receive_rejects_missing_evidence_and_authority_escalation(
    tmp_path,
):
    _, bridge = setup_bridge(tmp_path)

    missing = mission_envelope()
    missing["required_evidence"] = []
    with pytest.raises(
        RuntimeError,
        match="at least one evidence kind",
    ):
        bridge.receive(missing)

    elevated = mission_envelope()
    elevated["execution_policy"][
        "allow_paid"
    ] = True
    with pytest.raises(
        RuntimeError,
        match="does not grant elevated execution",
    ):
        bridge.receive(elevated)


def test_envelope_drives_operator_and_compiles_completed_outcome(
    tmp_path,
):
    store, bridge = setup_bridge(tmp_path)
    received = bridge.receive(
        mission_envelope()
    )
    envelope_id = received["status"][
        "envelope_id"
    ]

    started = bridge.start(envelope_id)
    operator = started["operator"]
    operator_id = operator["plan"]["id"]

    assert (
        "Keep the bridge transport-neutral."
        in operator["builder_task"]["constraints"]
    )
    assert (
        "Outcome Envelope support"
        in operator["builder_task"]["deliverables"]
    )

    builder_workspace = Path(
        operator["builder_workspace"]["path"]
    )
    (
        builder_workspace
        / "implementation.txt"
    ).write_text(
        "bridge implementation\n",
        encoding="utf-8",
    )
    (
        builder_workspace / "tests.txt"
    ).write_text(
        "tests passed\n",
        encoding="utf-8",
    )

    builder_submission = (
        bridge.operators.submit_result(
            operator_id,
            "builder",
            status="completed",
            summary="Builder complete.",
            evidence_files=[
                (
                    "test_result",
                    "tests.txt",
                )
            ],
        )
    )
    after_builder = builder_submission[
        "operator"
    ]
    assert (
        after_builder["state"]["status"]
        == "awaiting_qa"
    )

    qa_workspace = Path(
        after_builder["qa_workspace"]["path"]
    )
    (
        qa_workspace / "qa-report.txt"
    ).write_text(
        "Independent QA passed.\n",
        encoding="utf-8",
    )

    qa_submission = (
        bridge.operators.submit_result(
            operator_id,
            "qa",
            status="completed",
            summary="QA complete.",
            evidence_files=[
                (
                    "qa_report",
                    "qa-report.txt",
                )
            ],
        )
    )
    assert (
        qa_submission["operator"]["state"][
            "status"
        ]
        == "awaiting_verdict"
    )

    bridge.operators.verdict(
        operator_id,
        verdict="pass",
        summary="QA accepts the bridge.",
    )

    outcome = bridge.outcome(envelope_id)

    assert (
        outcome["schema_version"]
        == "mado.outcome-envelope.v1"
    )
    assert outcome["status"] == "completed"
    assert outcome["qa"]["verdict"] == "pass"
    assert set(
        outcome["evidence"]["kinds"]
    ) >= {
        "git_diff",
        "test_result",
        "qa_report",
    }
    assert outcome["human_attention"] is None
    assert "session" not in json.dumps(
        outcome,
        ensure_ascii=False,
    )
    assert (
        outcome["implementation"][
            "workspace_kind"
        ]
        == "git_worktree"
    )

    inspected = bridge.inspect(envelope_id)
    assert (
        inspected["outcome"]["status"]
        == "completed"
    )
    assert (
        inspected["status"]["outcome_status"]
        == "completed"
    )

    event_types = [
        event["type"]
        for event in store.list_events()
    ]
    assert "control.mission.received" in event_types
    assert "control.mission.accepted" in event_types
    assert "control.outcome.compiled" in event_types


def test_outcome_projects_human_attention_without_internal_state(
    tmp_path,
):
    _, bridge = setup_bridge(tmp_path)
    received = bridge.receive(
        mission_envelope(
            mission_id="MCC-M0.9-GATE"
        )
    )
    envelope_id = received["status"][
        "envelope_id"
    ]
    started = bridge.start(envelope_id)
    operator_id = started["operator"]["plan"][
        "id"
    ]

    opened = bridge.operators.request_gate(
        operator_id,
        question=(
            "Enable the paid path or stay free?"
        ),
        reason="The paid path may create charges.",
        materiality="cost",
        choices=[
            "enable_paid",
            "stay_free",
        ],
        impacts={
            "enable_paid": "May create charges.",
            "stay_free": "Keeps the free path.",
        },
        safe_default="stay_free",
        consent_required=True,
    )
    assert (
        opened["operator"]["state"]["status"]
        == "awaiting_human"
    )

    outcome = bridge.outcome(envelope_id)
    attention = outcome["human_attention"]

    assert outcome["status"] == "awaiting_human"
    assert attention is not None
    assert attention["materiality"] == "cost"
    assert attention["safe_default"] == "stay_free"
    assert "operator_id" not in attention
    assert "recovery_attempts" not in attention
