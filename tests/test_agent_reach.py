import json
import subprocess
from pathlib import Path

import pytest

from mado_cockpit.agent_reach import (
    AgentReachDoctorClient,
    channel_to_descriptor,
    parse_doctor_payload,
    sync_agent_reach_capabilities,
)
from mado_cockpit.capabilities import CapabilityManager
from mado_cockpit.models import (
    CapabilityDescriptor,
    Project,
)
from mado_cockpit.store import CockpitStore


FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "agent_reach"
    / "mcc-m1.7-doctor.json"
)


def fixture_payload():
    return json.loads(
        FIXTURE.read_text(encoding="utf-8")
    )


def test_doctor_client_runs_read_only_machine_contract():
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                fixture_payload(),
                ensure_ascii=False,
            ),
            "",
        )

    snapshot = AgentReachDoctorClient(
        "agent-reach",
        runner=fake_run,
        timeout=7,
    ).doctor()

    assert calls[0][0] == [
        "agent-reach",
        "doctor",
        "--json",
    ]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["timeout"] == 7
    assert (
        snapshot.channels["github"].routable
        is True
    )
    assert (
        snapshot.channels["twitter"].routable
        is False
    )
    assert (
        snapshot.channels["web"].availability
        == "unknown"
    )
    assert snapshot.to_dict()["summary"] == {
        "total": 3,
        "routable": 1,
        "statuses": {
            "error": 1,
            "off": 0,
            "ok": 1,
            "warn": 1,
        },
    }


def test_doctor_schema_drift_fails_closed():
    payload = fixture_payload()
    payload["github"]["status"] = "degraded"

    with pytest.raises(
        RuntimeError,
        match="unsupported status",
    ):
        parse_doctor_payload(payload)


def test_doctor_redacts_success_messages_before_persistence():
    payload = fixture_payload()
    payload["twitter"]["message"] = (
        "failed https://alice:password@example.test/x"
        "?access_token=top-secret "
        "Authorization=Bearer-Secret"
    )

    parsed = parse_doctor_payload(payload)
    message = parsed["twitter"].message

    assert "alice" not in message
    assert "password" not in message
    assert "top-secret" not in message
    assert (
        "https://***@example.test/x"
        in message
    )
    assert "access_token=***" in message


def test_channel_descriptor_requires_real_active_backend():
    parsed = parse_doctor_payload(
        fixture_payload()
    )

    github = channel_to_descriptor(
        parsed["github"]
    )
    twitter = channel_to_descriptor(
        parsed["twitter"]
    )
    web = channel_to_descriptor(
        parsed["web"]
    )

    assert github.availability == "available"
    assert (
        github.metadata["active_backend"]
        == "gh"
    )
    assert (
        twitter.availability
        == "unavailable"
    )
    assert web.availability == "unknown"
    assert github.instructions_ref.endswith(
        "#execution-contract"
    )


def test_sync_preserves_unmanaged_and_replaces_managed(
    tmp_path,
):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    manager = CapabilityManager(store)
    manager.set_registry(
        [
            CapabilityDescriptor(
                id="codex-cli",
                kind="cli",
                name="Codex CLI",
                short_description=(
                    "Implement code changes"
                ),
                availability="available",
                cost_class="low",
            ),
            CapabilityDescriptor(
                id="agent-reach.old",
                kind="adapter",
                name="Old Agent Reach",
                short_description=(
                    "stale managed entry"
                ),
                availability="unavailable",
                cost_class="free",
                metadata={
                    "managed_by": (
                        "mado-cockpit."
                        "agent-reach"
                    ),
                },
            ),
        ]
    )

    snapshot = AgentReachDoctorClient(
        runner=(
            lambda command, **kwargs:
            subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    fixture_payload(),
                    ensure_ascii=False,
                ),
                "",
            )
        )
    ).doctor()
    result = sync_agent_reach_capabilities(
        manager,
        snapshot,
    )

    by_id = {
        capability.id: capability
        for capability
        in manager.list_capabilities()
    }
    assert set(by_id) == {
        "codex-cli",
        "agent-reach.github",
        "agent-reach.twitter",
        "agent-reach.web",
    }
    assert (
        by_id["codex-cli"].name
        == "Codex CLI"
    )
    assert result["replaced_managed"] == 1
    assert result["preserved"] == 1
    assert result["routable"] == 1


def test_sync_refuses_unmanaged_same_id(
    tmp_path,
):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    manager = CapabilityManager(store)
    manager.set_registry(
        [
            CapabilityDescriptor(
                id="agent-reach.github",
                kind="adapter",
                name=(
                    "Human managed GitHub route"
                ),
                short_description=(
                    "Do not replace me"
                ),
                availability="available",
                cost_class="free",
            )
        ]
    )

    snapshot = AgentReachDoctorClient(
        runner=(
            lambda command, **kwargs:
            subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    fixture_payload(),
                    ensure_ascii=False,
                ),
                "",
            )
        )
    ).doctor()

    with pytest.raises(
        RuntimeError,
        match="overwrite unmanaged",
    ):
        sync_agent_reach_capabilities(
            manager,
            snapshot,
        )
