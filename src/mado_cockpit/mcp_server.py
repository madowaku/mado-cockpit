from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations

from .opendots_tools import (
    TOOL_CALL_SCHEMA,
    OpenDotsToolError,
    OpenDotsToolSurface,
)
from .store import CockpitStore


MCP_BRIDGE_VERSION = "MCC-M2.0"
MCP_SERVER_NAME = "mado-cockpit"

OperatorId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description="MADO Cockpit Operator ID, for example opr_123.",
    ),
]
GateId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=128,
        description=(
            "The current Human Question Gate ID returned by "
            "mado_check_mission. Pass it back unchanged."
        ),
    ),
]
Choice = Annotated[
    str,
    Field(
        min_length=1,
        max_length=400,
        description="The exact human-selected Gate choice.",
    ),
]
Note = Annotated[
    str,
    Field(
        max_length=2000,
        description="Optional human context for the Gate decision.",
    ),
]


class MadoMcpBridge:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.surface = OpenDotsToolSurface(
            CockpitStore(self.root)
        )

    def invoke(
        self,
        *,
        ctx: Context,
        name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        call_id = f"mcp:{ctx.request_id}"
        try:
            result = self.surface.handle(
                {
                    "schema": TOOL_CALL_SCHEMA,
                    "tool_call_id": call_id,
                    "tool_name": name,
                    "context": {
                        "dot_id": "chatgpt-mcp",
                    },
                    "arguments": arguments,
                }
            )
        except OpenDotsToolError as exc:
            raise ToolError(str(exc)) from exc

        if result.get("ok") is not True:
            error = result.get("error") or {}
            raise ToolError(
                str(
                    error.get(
                        "message",
                        "MADO Cockpit tool failed.",
                    )
                )
            )

        public: dict[str, Any] = {
            "ok": True,
        }
        if "data" in result:
            public["data"] = result["data"]
        if "presentation" in result:
            public["presentation"] = result["presentation"]
        return public


def build_server(root: Path) -> MCPServer:
    bridge = MadoMcpBridge(root)
    mcp = MCPServer(
        MCP_SERVER_NAME,
        title="MADO Cockpit",
        description=(
            "Private mission control tools for reading MADO Cockpit state, "
            "advancing deterministic orchestration, resolving explicit human "
            "decisions, and inspecting evidence and QA."
        ),
        version=MCP_BRIDGE_VERSION,
        instructions=(
            "Read mission state before taking write actions. Never infer a "
            "Human Question Gate decision. Call mado_answer_human_gate only "
            "after the user explicitly chose a listed option or explicitly "
            "asked to use the declared safe default. Do not invent Operator "
            "or Gate IDs."
        ),
    )

    @mcp.tool(
        title="Check mission",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    def mado_check_mission(
        operator_id: OperatorId,
        ctx: Context,
    ) -> dict[str, Any]:
        """Read mission state, next action, and any open Human Question Gate."""
        return bridge.invoke(
            ctx=ctx,
            name="mado_check_mission",
            arguments={"operator_id": operator_id},
        )

    @mcp.tool(
        title="Advance mission",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def mado_advance_mission(
        operator_id: OperatorId,
        ctx: Context,
    ) -> dict[str, Any]:
        """Advance deterministic orchestration only; never launch a model or shell."""
        return bridge.invoke(
            ctx=ctx,
            name="mado_advance_mission",
            arguments={"operator_id": operator_id},
        )

    @mcp.tool(
        title="Answer human decision",
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=False,
            idempotent_hint=False,
            open_world_hint=False,
        ),
    )
    def mado_answer_human_gate(
        operator_id: OperatorId,
        gate_id: GateId,
        ctx: Context,
        choice: Choice | None = None,
        choose_for_me: bool = False,
        note: Note | None = None,
    ) -> dict[str, Any]:
        """Resolve the current Human Question Gate using the user's explicit decision."""
        arguments: dict[str, Any] = {
            "operator_id": operator_id,
            "gate_id": gate_id,
            "choose_for_me": choose_for_me,
        }
        if choice is not None:
            arguments["choice"] = choice
        if note is not None:
            arguments["note"] = note
        return bridge.invoke(
            ctx=ctx,
            name="mado_answer_human_gate",
            arguments=arguments,
        )

    @mcp.tool(
        title="Show mission evidence",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    def mado_show_evidence(
        operator_id: OperatorId,
        ctx: Context,
        scope: Literal[
            "builder",
            "qa",
            "all",
        ] = "all",
    ) -> dict[str, Any]:
        """Show safe Builder/QA evidence metadata without internal filesystem paths."""
        return bridge.invoke(
            ctx=ctx,
            name="mado_show_evidence",
            arguments={
                "operator_id": operator_id,
                "scope": scope,
            },
        )

    @mcp.tool(
        title="Show QA result",
        annotations=ToolAnnotations(
            read_only_hint=True,
            open_world_hint=False,
        ),
    )
    def mado_show_qa_result(
        operator_id: OperatorId,
        ctx: Context,
    ) -> dict[str, Any]:
        """Show the current QA handoff, latest QA result, and verdict."""
        return bridge.invoke(
            ctx=ctx,
            name="mado_show_qa_result",
            arguments={"operator_id": operator_id},
        )

    return mcp


def _csv_env(name: str) -> list[str]:
    value = os.environ.get(name, "")
    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def _transport_security(
    *,
    host: str,
    allowed_hosts: list[str],
    allowed_origins: list[str],
) -> TransportSecuritySettings | None:
    loopback = {
        "127.0.0.1",
        "localhost",
        "::1",
    }
    if host in loopback and not allowed_hosts and not allowed_origins:
        return None
    if not allowed_hosts:
        raise ValueError(
            "Non-loopback MCP serving requires an explicit Host allowlist. "
            "Use --allowed-host or MADO_MCP_ALLOWED_HOSTS."
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="mado-cockpit-mcp"
    )
    parser.add_argument(
        "--root",
        default=".",
        help="MADO Cockpit repository root.",
    )
    parser.add_argument(
        "--transport",
        choices=[
            "stdio",
            "streamable-http",
        ],
        default="streamable-http",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(
            "MADO_MCP_HOST",
            "127.0.0.1",
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(
            os.environ.get(
                "MADO_MCP_PORT",
                "8787",
            )
        ),
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        default=[],
        help=(
            "Allowed HTTP Host header. Repeat for multiple values. "
            "May also be set with MADO_MCP_ALLOWED_HOSTS as CSV."
        ),
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        default=[],
        help=(
            "Allowed browser Origin. Repeat for multiple values. "
            "May also be set with MADO_MCP_ALLOWED_ORIGINS as CSV."
        ),
    )
    args = parser.parse_args(argv)

    mcp = build_server(
        Path(args.root)
    )
    if args.transport == "stdio":
        mcp.run(transport="stdio")
        return 0

    allowed_hosts = [
        *args.allowed_host,
        *_csv_env(
            "MADO_MCP_ALLOWED_HOSTS"
        ),
    ]
    allowed_origins = [
        *args.allowed_origin,
        *_csv_env(
            "MADO_MCP_ALLOWED_ORIGINS"
        ),
    ]
    try:
        security = _transport_security(
            host=args.host,
            allowed_hosts=allowed_hosts,
            allowed_origins=allowed_origins,
        )
    except ValueError as exc:
        parser.error(str(exc))

    mcp.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=security,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
