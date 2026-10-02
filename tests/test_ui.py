import json
import threading
import urllib.error
import urllib.request

import pytest

from mado_cockpit.cli import build_parser
from mado_cockpit.gates import HumanQuestionGateManager
from mado_cockpit.models import Mission, Project, Worker
from mado_cockpit.store import CockpitStore
from mado_cockpit.ui import CockpitDashboard, create_ui_server


def setup_store(tmp_path):
    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="fixture",
            name="Fixture Cockpit",
            root=str(tmp_path),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M0.8",
            title="Cockpit UI",
        )
    )
    store.save_worker(
        Worker(
            id="observer",
            role="reviewer",
            mission_id="MCC-M0.8",
            provider="unassigned",
        )
    )
    return store


def open_gate(store):
    return HumanQuestionGateManager(
        store
    ).request(
        question=(
            "Should this fixture stay private "
            "or become public?"
        ),
        reason=(
            "Visibility changes who can see it."
        ),
        materiality="privacy",
        mission_id="MCC-M0.8",
        choices=[
            "private",
            "public",
        ],
        impacts={
            "private": (
                "Only the intended people can see it."
            ),
            "public": (
                "Anyone can see it."
            ),
        },
        recommendation="private",
        safe_default="private",
        materially_changes_result=True,
        user_has_context_to_answer=True,
    )


def request_json(
    url,
    *,
    method="GET",
    payload=None,
    token=None,
):
    data = (
        json.dumps(payload).encode(
            "utf-8"
        )
        if payload is not None
        else None
    )
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **(
                {
                    "X-Mado-Cockpit-Token": token
                }
                if token
                else {}
            ),
        },
    )
    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:
        return (
            response.status,
            json.loads(
                response.read().decode(
                    "utf-8"
                )
            ),
        )


def test_dashboard_snapshot_combines_control_plane_state(
    tmp_path,
):
    store = setup_store(tmp_path)
    open_gate(store)

    snapshot = CockpitDashboard(
        store
    ).snapshot(
        event_limit=50
    )

    assert snapshot["project"]["name"] == (
        "Fixture Cockpit"
    )
    assert [
        mission["id"]
        for mission in snapshot["missions"]
    ] == ["MCC-M0.8"]
    assert snapshot["workers"][0]["id"] == (
        "observer"
    )
    assert snapshot["gate_summary"][
        "open_gate_count"
    ] == 1
    assert snapshot["evidence"][
        "bundle_count"
    ] == 0
    assert snapshot["operators"] == []
    assert snapshot["handoffs"] == []
    assert len(snapshot["events"]) >= 4


def test_ui_server_serves_dashboard_and_resolves_gate(
    tmp_path,
):
    store = setup_store(tmp_path)
    opened = open_gate(store)
    gate_id = opened["gate"]["id"]

    server, ui = create_ui_server(
        tmp_path,
        host="127.0.0.1",
        port=0,
        token="fixture-token",
    )
    thread = threading.Thread(
        target=server.serve_forever,
        kwargs={
            "poll_interval": 0.01,
        },
        daemon=True,
    )
    thread.start()

    try:
        host, port = server.server_address
        base = f"http://{host}:{port}"

        with urllib.request.urlopen(
            base + "/",
            timeout=5,
        ) as response:
            html = response.read().decode(
                "utf-8"
            )
            assert response.status == 200
            assert "MADO Cockpit" in html
            assert "fixture-token" in html
            assert (
                "Human Gates"
                in html
            )

        status, dashboard = request_json(
            base + "/api/dashboard"
        )
        assert status == 200
        assert dashboard[
            "gate_summary"
        ]["open_gate_count"] == 1

        with pytest.raises(
            urllib.error.HTTPError
        ) as exc:
            request_json(
                base + "/api/gate/resolve",
                method="POST",
                payload={
                    "gate_id": gate_id,
                    "choice": "private",
                },
            )
        assert exc.value.code == 403

        status, resolved = request_json(
            base + "/api/gate/resolve",
            method="POST",
            payload={
                "gate_id": gate_id,
                "choice": "private",
            },
            token=ui.token,
        )
        assert status == 200
        assert resolved[
            "resolution"
        ]["choice"] == "private"

        _, dashboard = request_json(
            base + "/api/dashboard"
        )
        assert dashboard[
            "gate_summary"
        ]["open_gate_count"] == 0
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ui_refuses_remote_bind_without_explicit_opt_in(
    tmp_path,
):
    setup_store(tmp_path)

    with pytest.raises(
        RuntimeError,
        match="Refusing non-local UI bind",
    ):
        create_ui_server(
            tmp_path,
            host="0.0.0.0",
            port=0,
        )


def test_ui_cli_command_defaults_to_localhost():
    args = build_parser().parse_args(
        ["ui"]
    )

    assert args.command == "ui"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.allow_remote is False
    assert args.open_browser is False
