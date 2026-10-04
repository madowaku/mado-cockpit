import asyncio
import json
import subprocess

import pytest

from mcp import Client

from mado_cockpit.mcp_server import (
    MCP_BRIDGE_VERSION,
    _transport_security,
    build_server,
)
from mado_cockpit.models import Mission, Project
from mado_cockpit.operator import OperatorManager
from mado_cockpit.store import CockpitStore


def _fixture(tmp_path):
    subprocess.run(
        ["git", "init", "-b", "main", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "m2@example.test"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "MCC M2 Fixture"],
        check=True,
    )
    (tmp_path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "README.md"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "commit", "-m", "fixture"],
        check=True,
        capture_output=True,
        text=True,
    )

    store = CockpitStore(tmp_path)
    store.init(
        Project(
            id="mcp-fixture",
            name="MCP Fixture",
            root=str(tmp_path),
        )
    )
    store.save_mission(
        Mission(
            id="MCC-M2.0-FIXTURE",
            title="MCP Bridge Fixture",
        )
    )
    manager = OperatorManager(store)
    started = manager.start(
        "MCC-M2.0-FIXTURE",
        "Exercise the ChatGPT MCP bridge.",
        required_evidence=["test_result"],
    )
    operator_id = started["plan"]["id"]
    requested = manager.request_gate(
        operator_id,
        question="Use the free path?",
        reason="The alternate path may create cost.",
        materiality="cost",
        choices=[
            "stay_free",
            "enable_paid",
        ],
        impacts={
            "stay_free": "No provider charge.",
            "enable_paid": "May create provider charges.",
        },
        recommendation="stay_free",
        safe_default="stay_free",
    )
    gate_id = requested["gate"]["gate"]["id"]
    return store, manager, operator_id, gate_id


def test_mcp_catalog_exposes_five_bounded_tools(tmp_path):
    _fixture(tmp_path)
    server = build_server(tmp_path)

    async def run():
        async with Client(
            server,
            raise_exceptions=True,
        ) as client:
            listed = await client.list_tools()

        assert [tool.name for tool in listed.tools] == [
            "mado_check_mission",
            "mado_advance_mission",
            "mado_answer_human_gate",
            "mado_show_evidence",
            "mado_show_qa_result",
        ]
        tools = {
            tool.name: tool
            for tool in listed.tools
        }
        assert (
            tools[
                "mado_check_mission"
            ].annotations.read_only_hint
            is True
        )
        assert (
            tools[
                "mado_advance_mission"
            ].annotations.read_only_hint
            is False
        )
        assert (
            tools[
                "mado_advance_mission"
            ].annotations.destructive_hint
            is False
        )
        assert (
            tools[
                "mado_answer_human_gate"
            ].annotations.open_world_hint
            is False
        )
        gate_schema = tools[
            "mado_answer_human_gate"
        ].input_schema
        assert "gate_id" in gate_schema["required"]

    asyncio.run(run())


def test_mcp_reads_real_operator_without_transport_ids(tmp_path):
    _, _, operator_id, gate_id = _fixture(tmp_path)
    server = build_server(tmp_path)

    async def run():
        async with Client(
            server,
            raise_exceptions=True,
        ) as client:
            result = await client.call_tool(
                "mado_check_mission",
                {"operator_id": operator_id},
            )

        assert result.is_error is False
        payload = result.structured_content
        assert payload["ok"] is True
        assert (
            payload["data"]["status"]
            == "awaiting_human"
        )
        assert (
            payload["data"]["human_gate"]["id"]
            == gate_id
        )
        serialized = json.dumps(payload)
        assert "tool_call_id" not in serialized
        assert "request_id" not in serialized
        assert ".mado/" not in serialized

    asyncio.run(run())


def test_mcp_human_gate_requires_current_gate_id(tmp_path):
    _, manager, operator_id, gate_id = _fixture(tmp_path)
    server = build_server(tmp_path)

    async def run():
        async with Client(
            server,
            raise_exceptions=True,
        ) as client:
            result = await client.call_tool(
                "mado_answer_human_gate",
                {
                    "operator_id": operator_id,
                    "gate_id": gate_id,
                    "choice": "stay_free",
                    "choose_for_me": False,
                },
            )

        assert result.is_error is False
        assert (
            result.structured_content[
                "data"
            ]["resolution"]["choice"]
            == "stay_free"
        )

    asyncio.run(run())

    view = manager.inspect(operator_id)
    assert (
        view["state"]["status"]
        == "awaiting_builder"
    )
    assert view["human_gate"] is None


def test_mcp_stale_gate_is_model_visible_error(tmp_path):
    _, _, operator_id, _ = _fixture(tmp_path)
    server = build_server(tmp_path)

    async def run():
        async with Client(server) as client:
            result = await client.call_tool(
                "mado_answer_human_gate",
                {
                    "operator_id": operator_id,
                    "gate_id": "gate_stale",
                    "choice": "stay_free",
                },
            )
        assert result.is_error is True
        text = "\n".join(
            block.text
            for block in result.content
            if hasattr(block, "text")
        )
        assert "no longer matches" in text

    asyncio.run(run())


def test_non_loopback_http_requires_host_allowlist():
    with pytest.raises(
        ValueError,
        match="Host allowlist",
    ):
        _transport_security(
            host="0.0.0.0",
            allowed_hosts=[],
            allowed_origins=[],
        )


def test_loopback_can_use_sdk_default_security():
    assert (
        _transport_security(
            host="127.0.0.1",
            allowed_hosts=[],
            allowed_origins=[],
        )
        is None
    )
