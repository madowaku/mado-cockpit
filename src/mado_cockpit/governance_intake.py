from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "mado.governance-diff.v1"
VERSION = "MCC-M2.1"
DEFAULT_FIXTURE = (
    "fixtures/openbot/"
    "mcc-m2.1-governance-intake.json"
)

_VALID_STATES = {
    "present",
    "partial",
    "missing",
}
_VALID_PRIORITIES = {
    "p0",
    "p1",
    "p2",
}


def load_intake(path: Path) -> dict[str, Any]:
    payload = json.loads(
        path.read_text(encoding="utf-8")
    )
    if payload.get("schema") != (
        "mado.openbot-governance-intake.v1"
    ):
        raise RuntimeError(
            "Unsupported governance intake schema"
        )
    if payload.get("version") != VERSION:
        raise RuntimeError(
            "Governance intake version mismatch"
        )

    upstream = payload.get("upstream")
    if not isinstance(upstream, dict):
        raise RuntimeError(
            "Governance intake upstream block is required"
        )
    commit = upstream.get("commit")
    if (
        not isinstance(commit, str)
        or len(commit) != 40
    ):
        raise RuntimeError(
            "Governance intake must pin a 40-character upstream commit"
        )
    files = upstream.get("files")
    if (
        not isinstance(files, dict)
        or not files
    ):
        raise RuntimeError(
            "Governance intake must pin upstream source files"
        )
    for source, sha in files.items():
        if (
            not isinstance(source, str)
            or not source
            or not isinstance(sha, str)
            or len(sha) != 40
        ):
            raise RuntimeError(
                "Invalid upstream source pin"
            )

    principles = payload.get("principles")
    if (
        not isinstance(principles, list)
        or not principles
    ):
        raise RuntimeError(
            "Governance intake principles are required"
        )

    seen: set[str] = set()
    for item in principles:
        if not isinstance(item, dict):
            raise RuntimeError(
                "Governance principle must be an object"
            )
        principle_id = str(
            item.get("id", "")
        )
        if not principle_id or principle_id in seen:
            raise RuntimeError(
                "Governance principle IDs must be unique"
            )
        seen.add(principle_id)

        if item.get("mado_state") not in _VALID_STATES:
            raise RuntimeError(
                f"Invalid MADO state for {principle_id}"
            )
        if item.get("priority") not in _VALID_PRIORITIES:
            raise RuntimeError(
                f"Invalid priority for {principle_id}"
            )
        source_files = item.get(
            "source_files"
        )
        if not isinstance(source_files, list):
            raise RuntimeError(
                f"source_files must be a list for {principle_id}"
            )
        unknown = [
            source
            for source in source_files
            if source not in files
        ]
        if unknown:
            raise RuntimeError(
                f"Unpinned source files for {principle_id}: "
                + ", ".join(unknown)
            )

    adoption = payload.get(
        "adoption_rules"
    )
    if not isinstance(adoption, dict):
        raise RuntimeError(
            "Governance intake adoption rules are required"
        )
    if adoption.get("copy_code") is not False:
        raise RuntimeError(
            "OpenBot intake must not authorize source copying"
        )
    if (
        adoption.get(
            "preserve_mado_source_of_truth"
        )
        is not True
    ):
        raise RuntimeError(
            "MADO must remain the source of truth"
        )
    return payload


def compile_diff(
    intake: dict[str, Any],
) -> dict[str, Any]:
    principles = list(
        intake["principles"]
    )
    state_counts = Counter(
        str(item["mado_state"])
        for item in principles
    )
    priority_counts = Counter(
        str(item["priority"])
        for item in principles
    )

    p0_gaps = [
        {
            "id": item["id"],
            "state": item["mado_state"],
            "gap": item["gap"],
        }
        for item in principles
        if item["priority"] == "p0"
        and item["mado_state"] != "present"
    ]

    next_scope = {
        "milestone": (
            "MCC-M2.2 Action Policy Gateway"
        ),
        "laws": [
            "No side effect executes without an execution-time policy decision.",
            "Deny wins over allow and policy evaluation errors refuse.",
            "A decision receipt is durable before dispatch.",
            "An external tool not positively classified read-only is treated as write.",
            "Human approval does not bypass revalidation of the current action.",
        ],
        "p0_gap_ids": [
            item["id"]
            for item in principles
            if item["priority"] == "p0"
            and item["mado_state"] != "present"
        ],
        "explicitly_deferred": [
            item["id"]
            for item in principles
            if item["target"]
            != "MCC-M2.2"
        ],
    }

    return {
        "schema": SCHEMA,
        "version": VERSION,
        "upstream": intake["upstream"],
        "adoption_rules": (
            intake["adoption_rules"]
        ),
        "summary": {
            "principle_count": len(
                principles
            ),
            "state_counts": {
                state: state_counts[
                    state
                ]
                for state in sorted(
                    _VALID_STATES
                )
            },
            "priority_counts": {
                priority: priority_counts[
                    priority
                ]
                for priority in sorted(
                    _VALID_PRIORITIES
                )
            },
            "p0_open_gap_count": len(
                p0_gaps
            ),
        },
        "p0_open_gaps": p0_gaps,
        "principles": principles,
        "next_scope": next_scope,
    }


def main(
    argv: list[str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog=(
            "python -m "
            "mado_cockpit.governance_intake"
        )
    )
    parser.add_argument(
        "--root",
        default=".",
    )
    parser.add_argument(
        "--fixture",
        default=DEFAULT_FIXTURE,
    )
    parser.add_argument(
        "--output",
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    fixture = Path(args.fixture)
    if not fixture.is_absolute():
        fixture = root / fixture

    report = compile_diff(
        load_intake(fixture)
    )
    rendered = (
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )
    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = root / output
        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        output.write_text(
            rendered,
            encoding="utf-8",
        )
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
