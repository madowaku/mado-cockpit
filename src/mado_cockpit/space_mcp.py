from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from .dogfood import SpaceDogfoodManager
from .space_transport import SpaceTransportAdapter
from .store import CockpitStore


_LOCAL_HOSTS = {
    "127.0.0.1",
    "localhost",
    "::1",
}


def build_server(
    root: Path | str = ".",
):
    try:
        from mcp.server import MCPServer
        from mcp.types import ToolAnnotations
    except ImportError as exc:
        raise RuntimeError(
            "Space MCP support requires the optional "
            "dependency. Install with: "
            'pip install -e ".[space]"'
        ) from exc

    store = CockpitStore(
        Path(root).resolve()
    )
    adapter = SpaceTransportAdapter(store)
    dogfood = SpaceDogfoodManager(store)
    mcp = MCPServer(
        "mado-cockpit-space",
        instructions=(
            "MADO Cockpit is an execution plane. "
            "Use submit_mission to send structured intent, "
            "start_mission only when execution is requested, "
            "refresh_outcome for current execution state, and "
            "resolve_human_attention only with the user's "
            "explicit choice or the Gate's declared safe default. "
            "Never infer elevated paid/publish/delete/external "
            "authority from prose. Use mado_dogfood_handshake "
            "only for a locally prepared dogfood challenge."
        ),
    )

    @mcp.tool(
        name="mado_dogfood_handshake",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def dogfood_handshake(
        challenge_id: str,
        nonce: str,
        client_label: str = "chatgpt-space",
    ) -> dict[str, Any]:
        """Prove a real MCP client reached the private Cockpit server.

        The challenge and nonce must have been generated locally by
        mado-cockpit-space-dogfood prepare. The returned envelope and
        stable request IDs drive a zero-quota submit/start/outcome/ack
        transport dogfood.
        """
        return dogfood.handshake(
            challenge_id,
            nonce,
            client_label=client_label,
        )

    @mcp.tool(
        name="mado_submit_mission",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def submit_mission(
        mission: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Submit a validated Mission Envelope to MADO Cockpit.

        The mission must use schema mado.mission-envelope.v1.
        Reusing request_id with the same input is safe and returns
        the recorded result. Reusing it with different input fails.
        """
        return adapter.submit_mission(
            mission,
            request_id=request_id,
        )

    @mcp.tool(
        name="mado_list_missions",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def list_missions(
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List Space-facing mission summaries without local paths."""
        return adapter.list_missions(
            status=status
        )

    @mcp.tool(
        name="mado_inspect_mission",
        annotations=ToolAnnotations(
            readOnlyHint=True,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def inspect_mission(
        envelope_id: str,
    ) -> dict[str, Any]:
        """Inspect one mission and its cached Outcome Envelope."""
        return adapter.inspect_mission(
            envelope_id
        )

    @mcp.tool(
        name="mado_start_mission",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def start_mission(
        envelope_id: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Start Cockpit execution for an accepted Mission Envelope.

        This provisions the existing deterministic Operator path.
        It does not itself launch a paid model turn, publish, delete,
        or send an external message.
        """
        return adapter.start_mission(
            envelope_id,
            request_id=request_id,
        )

    @mcp.tool(
        name="mado_refresh_outcome",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=False,
            openWorldHint=False,
        ),
    )
    def refresh_outcome(
        envelope_id: str,
    ) -> dict[str, Any]:
        """Compile the latest human-facing Outcome Envelope.

        The result excludes raw agent traces, worktree paths, and
        internal Operator state.
        """
        outcome = adapter.refresh_outcome(
            envelope_id
        )
        return {
            **outcome,
            "outcome_digest": (
                adapter.outcome_digest(
                    outcome
                )
            ),
        }

    @mcp.tool(
        name="mado_resolve_human_attention",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def resolve_human_attention(
        envelope_id: str,
        choice: str | None = None,
        choose_for_me: bool = False,
        note: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Resolve an open Human Question Gate.

        Supply exactly one of choice or choose_for_me. choose_for_me
        can only select the Gate's declared safe default; it does not
        grant arbitrary authority.
        """
        outcome = (
            adapter.resolve_human_attention(
                envelope_id,
                choice=choice,
                choose_for_me=choose_for_me,
                note=note,
                request_id=request_id,
            )
        )
        return {
            **outcome,
            "outcome_digest": (
                adapter.outcome_digest(
                    outcome
                )
            ),
        }

    @mcp.tool(
        name="mado_acknowledge_outcome",
        annotations=ToolAnnotations(
            readOnlyHint=False,
            destructiveHint=False,
            idempotentHint=True,
            openWorldHint=False,
        ),
    )
    def acknowledge_outcome(
        envelope_id: str,
        outcome_digest: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge that Space consumed a specific outcome revision.

        The digest must match the currently compiled Outcome Envelope,
        preventing acknowledgement of stale or substituted content.
        """
        return adapter.acknowledge_outcome(
            envelope_id,
            outcome_digest=outcome_digest,
            request_id=request_id,
        )

    return mcp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mado-cockpit-space-mcp"
    )
    parser.add_argument(
        "--root",
        default=os.environ.get(
            "MADO_COCKPIT_ROOT",
            ".",
        ),
        help=(
            "Cockpit repository root. Defaults to "
            "MADO_COCKPIT_ROOT or the current directory."
        ),
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
        default="127.0.0.1",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8780,
    )
    return parser


def main(
    argv: list[str] | None = None,
) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    server = build_server(root)

    if args.transport == "stdio":
        server.run(transport="stdio")
        return 0

    if args.host not in _LOCAL_HOSTS:
        raise RuntimeError(
            "M1.0 Space MCP is localhost-only. "
            "Use Secure MCP Tunnel for developer-mode "
            "testing or add an authenticated remote gateway "
            "in a later milestone."
        )

    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
