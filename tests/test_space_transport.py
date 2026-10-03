import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.models import Project
from mado_cockpit.space_mcp import (
    build_server,
    main as space_mcp_main,
)
from mado_cockpit.space_transport import (
    SpaceTransportAdapter,
)
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
    mission_id: str = "MCC-M1.0",
) -> dict:
    return {
        "schema_version": (
            "mado.mission-envelope.v1"
        ),
        "mission_id": mission_id,
        "title": "Space Transport Adapter",
        "objective": (
            "Expose the control bridge safely "
            "through MCP."
        ),
        "source": {
            "kind": "space",
            "space_id": "space-fixture",
            "page_id": "page-fixture",
            "revision": "1",
        },
        "priority": "normal",
        "constraints": [
            "Keep the transport replaceable."
        ],
        "deliverables": [
            "MCP tools",
            "transport receipts",
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
    }


def setup_adapter(
    tmp_path: Path,
) -> tuple[CockpitStore, SpaceTransportAdapter]:
    init_repo(tmp_path)
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    return store, SpaceTransportAdapter(store)


def test_transport_request_id_is_idempotent(
    tmp_path,
):
    _, adapter = setup_adapter(tmp_path)
    payload = mission_envelope()

    first = adapter.submit_mission(
        payload,
        request_id="space-submit-001",
    )
    second = adapter.submit_mission(
        payload,
        request_id="space-submit-001",
    )

    assert first == second
    assert first["status"] == "accepted"
    assert (
        len(
            list(
                adapter.requests_dir.glob(
                    "*.json"
                )
            )
        )
        == 1
    )

    changed = mission_envelope()
    changed["objective"] = "Different objective"
    with pytest.raises(
        RuntimeError,
        match="different input",
    ):
        adapter.submit_mission(
            changed,
            request_id="space-submit-001",
        )


def test_start_projection_hides_execution_internals(
    tmp_path,
):
    _, adapter = setup_adapter(tmp_path)
    accepted = adapter.submit_mission(
        mission_envelope()
    )
    envelope_id = accepted["envelope_id"]

    started = adapter.start_mission(
        envelope_id,
        request_id="space-start-001",
    )
    repeated = adapter.start_mission(
        envelope_id,
        request_id="space-start-001",
    )

    assert started == repeated
    assert started["status"] == "started"
    assert (
        started["operator_status"]
        == "awaiting_builder"
    )
    serialized = json.dumps(started)
    assert "builder_workspace" not in serialized
    assert "worktree" not in serialized
    assert str(tmp_path) not in serialized


def test_transport_compiles_and_acknowledges_outcome(
    tmp_path,
):
    _, adapter = setup_adapter(tmp_path)
    accepted = adapter.submit_mission(
        mission_envelope()
    )
    envelope_id = accepted["envelope_id"]
    adapter.start_mission(envelope_id)

    raw = adapter.control.inspect(envelope_id)
    operator_id = raw["status"]["operator_id"]
    run = adapter.control.operators.inspect(
        str(operator_id)
    )

    builder_workspace = Path(
        run["builder_workspace"]["path"]
    )
    (
        builder_workspace
        / "implementation.txt"
    ).write_text(
        "transport implementation\n",
        encoding="utf-8",
    )
    (
        builder_workspace / "tests.txt"
    ).write_text(
        "tests passed\n",
        encoding="utf-8",
    )

    builder = (
        adapter.control.operators.submit_result(
            str(operator_id),
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
    )["operator"]

    qa_workspace = Path(
        builder["qa_workspace"]["path"]
    )
    (
        qa_workspace / "qa-report.txt"
    ).write_text(
        "QA passed.\n",
        encoding="utf-8",
    )

    adapter.control.operators.submit_result(
        str(operator_id),
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
    adapter.control.operators.verdict(
        str(operator_id),
        verdict="pass",
        summary="QA accepts transport.",
    )

    outcome = adapter.refresh_outcome(
        envelope_id
    )
    digest = adapter.outcome_digest(
        outcome
    )
    ack = adapter.acknowledge_outcome(
        envelope_id,
        outcome_digest=digest,
        request_id="space-ack-001",
    )
    repeated = adapter.acknowledge_outcome(
        envelope_id,
        outcome_digest=digest,
        request_id="space-ack-001",
    )

    assert outcome["status"] == "completed"
    assert outcome["qa"]["verdict"] == "pass"
    assert ack == repeated
    assert ack["outcome_digest"] == digest
    assert (
        adapter.acks_dir
        / envelope_id
        / f"{digest}.json"
    ).exists()

    with pytest.raises(
        RuntimeError,
        match="digest mismatch",
    ):
        adapter.acknowledge_outcome(
            envelope_id,
            outcome_digest="deadbeef",
        )


def test_transport_routes_human_attention(
    tmp_path,
):
    _, adapter = setup_adapter(tmp_path)
    accepted = adapter.submit_mission(
        mission_envelope(
            mission_id="MCC-M1.0-GATE"
        )
    )
    envelope_id = accepted["envelope_id"]
    adapter.start_mission(envelope_id)

    raw = adapter.control.inspect(envelope_id)
    operator_id = str(
        raw["status"]["operator_id"]
    )
    adapter.control.operators.request_gate(
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

    waiting = adapter.refresh_outcome(
        envelope_id
    )
    assert waiting["status"] == "awaiting_human"
    assert (
        waiting["human_attention"][
            "safe_default"
        ]
        == "stay_free"
    )

    resolved = (
        adapter.resolve_human_attention(
            envelope_id,
            choose_for_me=True,
            request_id="space-gate-001",
        )
    )
    repeated = (
        adapter.resolve_human_attention(
            envelope_id,
            choose_for_me=True,
            request_id="space-gate-001",
        )
    )

    assert resolved == repeated
    assert resolved["human_attention"] is None
    assert resolved["status"] == "awaiting_builder"


def test_transport_lists_missions(
    tmp_path,
):
    _, adapter = setup_adapter(tmp_path)
    first = adapter.submit_mission(
        mission_envelope(
            mission_id="MCC-M1.0-A"
        )
    )
    adapter.submit_mission(
        mission_envelope(
            mission_id="MCC-M1.0-B"
        )
    )
    adapter.start_mission(
        first["envelope_id"]
    )

    missions = adapter.list_missions()
    assert len(missions) == 2
    assert {
        item["mission_id"]
        for item in missions
    } == {
        "MCC-M1.0-A",
        "MCC-M1.0-B",
    }
    assert (
        len(
            adapter.list_missions(
                status="started"
            )
        )
        == 1
    )


def test_mcp_server_advertises_bounded_tools(
    tmp_path,
):
    _, _ = setup_adapter(tmp_path)
    server = build_server(tmp_path)
    tools = asyncio.run(
        server.list_tools()
    )
    by_name = {
        tool.name: tool
        for tool in tools
    }

    assert set(by_name) == {
        "mado_dogfood_handshake",
        "mado_submit_mission",
        "mado_list_missions",
        "mado_inspect_mission",
        "mado_start_mission",
        "mado_refresh_outcome",
        "mado_resolve_human_attention",
        "mado_acknowledge_outcome",
    }
    assert (
        by_name[
            "mado_list_missions"
        ].annotations.read_only_hint
        is True
    )
    assert (
        by_name[
            "mado_start_mission"
        ].annotations.destructive_hint
        is False
    )
    assert (
        by_name[
            "mado_submit_mission"
        ].annotations.idempotent_hint
        is True
    )


def test_mcp_http_refuses_remote_bind(
    tmp_path,
    monkeypatch,
):
    class FakeServer:
        def run(self, **kwargs):
            raise AssertionError(
                "remote server must not run"
            )

    monkeypatch.setattr(
        "mado_cockpit.space_mcp.build_server",
        lambda root: FakeServer(),
    )

    with pytest.raises(
        RuntimeError,
        match="localhost-only",
    ):
        space_mcp_main(
            [
                "--root",
                str(tmp_path),
                "--host",
                "0.0.0.0",
            ]
        )
