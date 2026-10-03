from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .secure_tunnel import SecureTunnelManager
from .store import CockpitStore


def _print(payload: object) -> None:
    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mado-cockpit-tunnel"
    )
    parser.add_argument(
        "--root",
        default=os.environ.get(
            "MADO_COCKPIT_ROOT",
            ".",
        ),
    )
    sub = parser.add_subparsers(
        dest="command",
        required=True,
    )

    plan = sub.add_parser(
        "plan",
        help="Show redaction-safe Secure MCP Tunnel commands",
    )
    plan.add_argument("--tunnel-id", required=True)
    plan.add_argument(
        "--profile",
        default="mado-cockpit-space",
    )
    plan.add_argument(
        "--tunnel-client",
        default="tunnel-client",
    )

    init = sub.add_parser(
        "init",
        help="Initialize a local tunnel-client profile",
    )
    init.add_argument("--tunnel-id", required=True)
    init.add_argument(
        "--profile",
        default="mado-cockpit-space",
    )
    init.add_argument(
        "--tunnel-client",
        default="tunnel-client",
    )

    doctor = sub.add_parser(
        "doctor",
        help="Run tunnel-client doctor and persist evidence",
    )
    doctor.add_argument(
        "--profile",
        default="mado-cockpit-space",
    )
    doctor.add_argument(
        "--tunnel-client",
        default="tunnel-client",
    )

    run = sub.add_parser(
        "run",
        help="Run the tunnel client in the foreground",
    )
    run.add_argument(
        "--profile",
        default="mado-cockpit-space",
    )
    run.add_argument(
        "--tunnel-client",
        default="tunnel-client",
    )

    inspect = sub.add_parser(
        "inspect",
        help="Inspect local non-secret tunnel metadata",
    )
    inspect.add_argument(
        "--profile",
        default="mado-cockpit-space",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = CockpitStore(
        Path(args.root).resolve()
    )
    manager = SecureTunnelManager(store)

    if args.command == "plan":
        _print(
            manager.plan(
                tunnel_id=args.tunnel_id,
                profile=args.profile,
                tunnel_client=args.tunnel_client,
            ).to_dict()
        )
        return 0

    if args.command == "init":
        _print(
            manager.init_profile(
                tunnel_id=args.tunnel_id,
                profile=args.profile,
                tunnel_client=args.tunnel_client,
            )
        )
        return 0

    if args.command == "doctor":
        result = manager.doctor(
            profile=args.profile,
            tunnel_client=args.tunnel_client,
        )
        _print(result)
        return 0 if result["healthy"] else 1

    if args.command == "run":
        return manager.run(
            profile=args.profile,
            tunnel_client=args.tunnel_client,
        )

    if args.command == "inspect":
        _print(
            manager.inspect_profile(
                args.profile
            )
        )
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
