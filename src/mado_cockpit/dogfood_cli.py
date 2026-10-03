from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .dogfood import SpaceDogfoodManager
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
        prog="mado-cockpit-space-dogfood"
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

    prepare = sub.add_parser(
        "prepare",
        help="Create a zero-quota real Space challenge",
    )
    prepare.add_argument(
        "--title",
        default="Real Space transport dogfood",
    )

    verify_probe = sub.add_parser(
        "verify-probe",
        help="Verify a read-only MCP Tunnel proof",
    )
    verify_probe.add_argument("challenge_id")
    verify_probe.add_argument("proof")

    verify = sub.add_parser(
        "verify",
        help="Verify MCP→Cockpit→Outcome→ACK evidence",
    )
    verify.add_argument("challenge_id")

    inspect = sub.add_parser(
        "inspect",
        help="Inspect dogfood challenge evidence",
    )
    inspect.add_argument("challenge_id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manager = SpaceDogfoodManager(
        CockpitStore(
            Path(args.root).resolve()
        )
    )

    if args.command == "prepare":
        _print(
            manager.prepare(
                title=args.title
            )
        )
        return 0

    if args.command == "verify-probe":
        result = manager.verify_probe(
            args.challenge_id,
            args.proof,
        )
        _print(result)
        return 0 if result["valid"] else 3

    if args.command == "verify":
        result = manager.verify(
            args.challenge_id
        )
        _print(result)
        return 0 if result["complete"] else 2

    if args.command == "inspect":
        _print(
            manager.inspect(
                args.challenge_id
            )
        )
        return 0

    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
