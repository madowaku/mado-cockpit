from __future__ import annotations

import argparse
import asyncio
import json

from mcp import Client


async def _run(url: str) -> dict[str, object]:
    async with Client(url) as client:
        listed = await client.list_tools()
        names = [
            tool.name
            for tool in listed.tools
        ]
        expected = [
            "mado_check_mission",
            "mado_advance_mission",
            "mado_answer_human_gate",
            "mado_show_evidence",
            "mado_show_qa_result",
        ]
        if names != expected:
            raise RuntimeError(
                f"Unexpected MCP tools: {names}"
            )

        missing = await client.call_tool(
            "mado_check_mission",
            {
                "operator_id": (
                    "opr_mcc_m2_0_missing_fixture"
                )
            },
        )
        if missing.is_error is not True:
            raise RuntimeError(
                "Expected missing Operator to return a tool error."
            )

        return {
            "schema": (
                "mado.mcp.http-smoke.v1"
            ),
            "version": "MCC-M2.0",
            "ok": True,
            "url": url,
            "tools": names,
            "missing_operator_is_error": True,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8787/mcp",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            asyncio.run(
                _run(args.url)
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
