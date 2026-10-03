import subprocess
from pathlib import Path

import pytest

from mado_cockpit.dogfood import SpaceDogfoodManager
from mado_cockpit.models import Project
from mado_cockpit.secure_tunnel import SecureTunnelManager
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


def setup_store(tmp_path: Path) -> CockpitStore:
    init_repo(tmp_path)
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture",
            root=str(tmp_path),
        )
    )
    return store


def test_tunnel_plan_uses_stdio_mcp_and_no_secret(
    tmp_path,
):
    store = setup_store(tmp_path)
    manager = SecureTunnelManager(store)

    plan = manager.plan(
        tunnel_id=(
            "tunnel_0123456789abcdef"
        ),
    )
    serialized = str(plan.to_dict())

    assert (
        "mado_cockpit.space_mcp"
        in plan.mcp_command
    )
    assert "--transport" in plan.mcp_command
    assert "stdio" in plan.mcp_command
    assert (
        "CONTROL_PLANE_API_KEY"
        not in serialized
    )


def test_tunnel_init_and_doctor_persist_redacted_evidence(
    tmp_path,
):
    store = setup_store(tmp_path)
    calls = []

    def fake_runner(args, env, cwd):
        calls.append(
            {
                "args": list(args),
                "env": dict(env),
                "cwd": cwd,
            }
        )
        if "doctor" in args:
            return subprocess.CompletedProcess(
                args=list(args),
                returncode=0,
                stdout="healthy and ready\n",
                stderr="",
            )
        return subprocess.CompletedProcess(
            args=list(args),
            returncode=0,
            stdout="initialized\n",
            stderr="",
        )

    manager = SecureTunnelManager(
        store,
        runner=fake_runner,
    )
    env = {
        "CONTROL_PLANE_API_KEY": (
            "sk-fixture-secret"
        )
    }

    initialized = manager.init_profile(
        tunnel_id=(
            "tunnel_0123456789abcdef"
        ),
        env=env,
    )
    doctor = manager.doctor(env=env)

    assert (
        initialized["status"]
        == "initialized"
    )
    assert doctor["healthy"] is True
    assert len(calls) == 2
    assert (
        calls[0]["env"][
            "CONTROL_PLANE_API_KEY"
        ]
        == "sk-fixture-secret"
    )

    persisted = (
        store.base
        / "control"
        / "secure-tunnel"
    )
    text = "".join(
        path.read_text(encoding="utf-8")
        for path in persisted.rglob("*.json")
    )
    assert "sk-fixture-secret" not in text
    assert "healthy and ready" in text


def test_tunnel_requires_runtime_key(
    tmp_path,
):
    store = setup_store(tmp_path)
    manager = SecureTunnelManager(store)

    with pytest.raises(
        RuntimeError,
        match="CONTROL_PLANE_API_KEY",
    ):
        manager.init_profile(
            tunnel_id=(
                "tunnel_0123456789abcdef"
            ),
            env={},
        )


def test_real_space_dogfood_challenge_full_transport_loop(
    tmp_path,
):
    store = setup_store(tmp_path)
    dogfood = SpaceDogfoodManager(store)
    prepared = dogfood.prepare()

    challenge_id = prepared["challenge_id"]
    handshake = dogfood.handshake(
        challenge_id,
        prepared["nonce"],
        client_label="chatgpt-space",
    )

    assert (
        handshake["transport"]
        == "mcp"
    )
    assert handshake["envelope"][
        "metadata"
    ]["zero_quota"] is True

    request_ids = handshake[
        "request_ids"
    ]
    accepted = dogfood.transport.submit_mission(
        handshake["envelope"],
        request_id=request_ids["submit"],
    )
    envelope_id = accepted["envelope_id"]

    started = dogfood.transport.start_mission(
        envelope_id,
        request_id=request_ids["start"],
    )
    assert (
        started["operator_status"]
        == "awaiting_builder"
    )

    outcome = (
        dogfood.transport.refresh_outcome(
            envelope_id
        )
    )
    assert (
        outcome["status"]
        == "awaiting_builder"
    )
    assert outcome["qa"]["verdict"] is None

    digest = (
        dogfood.transport.outcome_digest(
            outcome
        )
    )
    dogfood.transport.acknowledge_outcome(
        envelope_id,
        outcome_digest=digest,
        request_id=request_ids["ack"],
    )

    verified = dogfood.verify(
        challenge_id
    )
    assert verified["complete"] is True
    assert verified["checks"] == {
        "mcp_handshake": True,
        "mission_submitted": True,
        "mission_started": True,
        "outcome_compiled": True,
        "outcome_acknowledged": True,
    }
    assert (
        verified["outcome_status"]
        == "awaiting_builder"
    )


def test_dogfood_nonce_mismatch_rejected(
    tmp_path,
):
    store = setup_store(tmp_path)
    dogfood = SpaceDogfoodManager(store)
    prepared = dogfood.prepare()

    with pytest.raises(
        RuntimeError,
        match="nonce mismatch",
    ):
        dogfood.handshake(
            prepared["challenge_id"],
            "wrong-nonce",
        )


def test_dogfood_verification_is_partial_before_real_client(
    tmp_path,
):
    store = setup_store(tmp_path)
    dogfood = SpaceDogfoodManager(store)
    prepared = dogfood.prepare()

    verified = dogfood.verify(
        prepared["challenge_id"]
    )

    assert verified["complete"] is False
    assert not any(
        verified["checks"].values()
    )
